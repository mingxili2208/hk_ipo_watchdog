"""数据库初始化和连接管理。"""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from loguru import logger


class Base(DeclarativeBase):
    pass


_engine = None
_SessionFactory = None


def init_db(database_url: str = "sqlite:///data/hk_ipo_watchdog.db") -> None:
    """初始化数据库连接并创建表。"""
    global _engine, _SessionFactory

    _engine = create_engine(database_url, echo=False)
    _SessionFactory = sessionmaker(bind=_engine)

    Base.metadata.create_all(_engine)
    logger.info(f"Database initialized: {database_url}")


def get_session() -> Session:
    """获取数据库 session。"""
    if _SessionFactory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _SessionFactory()


def get_engine():
    """获取数据库引擎。"""
    return _engine
