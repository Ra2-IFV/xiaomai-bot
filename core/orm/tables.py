from sqlalchemy import Column, Integer, String, Boolean
from core.orm import orm


class MemberPerm(orm.Base):
    """
    -1为全局黑 对应群号为0
    0为单群黑
    16为群员
    32为管理
    64为群主
    128为Admin
    256为Master
    """
    __tablename__ = 'MemberPerm'

    group_id = Column(Integer, primary_key=True)
    qq = Column(Integer, primary_key=True)
    perm = Column(Integer, nullable=False, info={'check': [-1, 0, 16, 32, 64, 128, 256]}, default=16)


class GroupPerm(orm.Base):
    """
    0为非活动群组
    1为正常活动群组
    2为vip群组
    3为测试群组
    """
    __tablename__ = 'GroupPerm'

    group_id = Column(Integer, primary_key=True)
    group_name = Column(String(length=60), nullable=False)
    perm = Column(Integer, nullable=False, info={'check': [0, 1, 2, 3]}, default=1)
    active = Column(Boolean(create_constraint=False), default=True)
