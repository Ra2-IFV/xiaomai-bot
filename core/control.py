import contextlib
from typing import Union

import sqlalchemy.exc
from creart import create
from graia.amnesia.message import MessageChain
from graia.ariadne import Ariadne
from graia.ariadne.event.message import GroupMessage, FriendMessage
from graia.ariadne.message import Source
from graia.ariadne.model import Group, Friend
from graia.broadcast import ExecutionStop
from graia.broadcast.builtin.decorators import Depend
from sqlalchemy import select

from core.config import GlobalConfig
from core.orm import orm
from core.orm.tables import MemberPerm, GroupPerm
from core.models.saya_model import get_module_data

config = create(GlobalConfig)


class Permission(object):
    """权限判断

    成员权限:
    -1      全局黑
    0       单群黑
    16      群员
    32      管理
    64      群主
    128     Admin
    256     Master

    群权限:
    0       非活动群组
    1       正常活动群组
    2       vip群组
    3       测试群组
    """
    Master = 256
    Admin = 128
    GroupOwner = 64
    GroupAdmin = 32
    User = 16
    Black = 0
    GlobalBlack = -1

    InactiveGroup = 0
    ActiveGroup = 1
    VipGroup = 2
    TestGroup = 3

    @classmethod
    async def get_user_perm(cls, event: Union[GroupMessage, FriendMessage]) -> int:
        """
        根据传入的qq号与群号来判断该用户的权限等级
        """
        sender = event.sender
        # 判断是群还是好友
        group_id = event.sender.group.id if isinstance(event, GroupMessage) else None
        if not group_id:
            # 查询是否在全局黑当中
            result = await orm.fetch_one(
                select(MemberPerm.perm).where(
                    MemberPerm.qq == sender.id,
                    MemberPerm.group_id == 0
                )
            )
            # 如果有查询到数据，则返回用户的权限等级
            if result:
                return result[0]
            else:
                if sender.id == config.Master:
                    return Permission.Master
                elif sender.id in config.Admins:
                    return Permission.Admin
                else:
                    return Permission.User
        # 如果有查询到数据，则返回用户的权限等级
        if result := await orm.fetch_one(
                select(MemberPerm.perm).where(MemberPerm.group_id == group_id, MemberPerm.qq == sender.id)
        ):
            return result[0]
        # 如果没有查询到数据，则返回16(群员),并写入初始权限
        else:
            with contextlib.suppress(sqlalchemy.exc.IntegrityError):
                await orm.insert_or_ignore(
                    table=MemberPerm,
                    condition=[
                        MemberPerm.qq == sender.id,
                        MemberPerm.group_id == group_id
                    ],
                    data={
                        "group_id": group_id,
                        "qq": sender.id,
                        "perm": Permission.User
                    }
                )
                return Permission.User

    @classmethod
    def user_require(cls, perm: int = User, if_noticed: bool = False):
        """
        指定perm及以上的等级才能执行
        :param perm: 设定权限等级
        :param if_noticed: 是否发送权限不足的消息通知
        """

        async def wrapper(app: Ariadne, event: Union[GroupMessage, FriendMessage]):
            # 获取并判断用户的权限等级
            if (user_level := await cls.get_user_perm(event)) < perm:
                if if_noticed:
                    await app.send_message(event.sender.group, MessageChain(
                        f"权限不足!需要权限:{perm}/你的权限:{user_level}"
                    ), quote=event.message_chain.get_first(Source))
                raise ExecutionStop
            return Depend(wrapper)

        return Depend(wrapper)

    @classmethod
    async def get_group_perm(cls, group: Group) -> int:
        """
        根据传入的群号获取群权限
        """
        # 查询数据库
        # 如果有查询到数据，则返回群的权限等级
        if result := await orm.fetch_one(select(GroupPerm.perm).where(
                GroupPerm.group_id == group.id)):
            return result[0]
        # 如果没有查询到数据，则返回1（活跃群）,并写入初始权限1
        else:
            if group.id in config.black_group:
                perm = 0
            elif group.id in config.vip_group:
                perm = 2
            elif group.id == config.test_group:
                perm = 3
            else:
                perm = 1
            with contextlib.suppress(sqlalchemy.exc.IntegrityError):
                await orm.insert_or_update(
                    GroupPerm,
                    {"group_id": group.id, "group_name": group.name, "active": True, "perm": perm},
                    [
                        GroupPerm.group_id == group.id
                    ]
                )
                return Permission.ActiveGroup

    @classmethod
    def group_require(cls, perm: int = ActiveGroup, if_noticed: bool = False):
        """
        指定perm及以上的等级才能执行
        :param perm: 设定权限等级
        :param if_noticed: 是否通知
        """

        async def wrapper(app: Ariadne, event: GroupMessage):
            # 获取并判断群的权限等级
            group = event.sender.group
            if (group_perm := await cls.get_group_perm(group)) < perm:
                if if_noticed:
                    await app.send_message(group, MessageChain(
                        f"权限不足!需要权限:{perm}/当前群{group.id}权限:{group_perm}"
                    ), quote=event.message_chain.get_first(Source))
                raise ExecutionStop
            return Depend(wrapper)

        return Depend(wrapper)


class Function(object):
    """功能判断"""

    @classmethod
    def require(cls, module_name):
        async def judge(app: Ariadne, src: Source or None = None, group: Group or None = None):
            # 如果module_name不在modules_list里面就添加
            modules_data = get_module_data()
            if module_name not in modules_data.modules:
                modules_data.add_module(module_name)
            if not group:
                return
            # 如果group不在modules里面就添加
            if str(group.id) not in modules_data.modules[module_name]:
                modules_data.add_group(group)
            # 如果在维护就停止
            if not modules_data.if_module_available(module_name):
                if modules_data.if_module_notice_on(module_name, group):
                    await app.send_message(group, MessageChain(
                        f"{module_name}插件正在维护~"
                    ), quote=src)
                raise ExecutionStop
            else:
                # 如果群未打开开关就停止
                if not modules_data.if_module_switch_on(module_name, group):
                    if modules_data.if_module_notice_on(module_name, group):
                        await app.send_message(group, MessageChain(
                            f"{module_name}插件已关闭，请联系管理员"
                        ), quote=src)
                    raise ExecutionStop
            return

        return Depend(judge)


temp_dict = {}


# TODO 完善消息分发require
#   需要根据响应类型 随机/指定bot 来响应
#   可以做一个类似于saya_model的response_model来辅助使用
class Distribute(object):

    @classmethod
    def require(cls, response_type: str = "random"):
        """
        用于消息分发
        :return: Depend
        """

        async def wrapper(group: Union[Group, Friend], app: Ariadne, source: Source):
            global temp_dict
            if type(group) == Friend:
                return Depend(wrapper)
            # 第一次要获取群列表，然后添加bot到groupid字典，编号
            # 然后对messageId取余，对应编号bot响应
            if group.id not in temp_dict:
                member_list = await app.get_member_list(group)
                temp_dict[group.id] = {}
                temp_dict[group.id][0] = app.account
                for item in member_list:
                    if item.id in Ariadne.service.connections:
                        temp_dict[group.id][len(temp_dict[group.id])] = item.id
            if temp_dict[group.id][source.id % len(temp_dict[group.id])] != app.account:
                raise ExecutionStop
            # 防止bot中途掉线/风控造成无响应
            if temp_dict[group.id][source.id % len(temp_dict[group.id])] not in Ariadne.service.connections:
                temp_dict.pop(group.id)
            return Depend(wrapper)

        return Depend(wrapper)


# TODO 实现频率限制FrequencyLimitation
class FrequencyLimitation(object):
    """频率限制"""

    @classmethod
    def require(cls, Weights):
        async def limit():
            ...

        return Depend(limit)


# TODO 实现配置前置Config
class Config(object):
    """配置检查"""

    @classmethod
    def require(cls, config_item):
        async def check_config():
            ...

        return Depend(check_config)
