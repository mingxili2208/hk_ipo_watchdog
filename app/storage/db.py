"""数据库初始化和连接管理。"""

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from loguru import logger


class Base(DeclarativeBase):
    pass


_engine = None
_SessionFactory = None


def init_db(database_url: str = "sqlite:///data/hk_ipo_watchdog.db") -> None:
    """初始化数据库连接并创建表。"""
    global _engine, _SessionFactory

    # Ensure table metadata is registered even when init-db is the first command run.
    from app.storage import models as _models  # noqa: F401

    _engine = create_engine(database_url, echo=False)
    _SessionFactory = sessionmaker(bind=_engine)

    Base.metadata.create_all(_engine)
    if database_url.startswith("sqlite"):
        inspector = inspect(_engine)
        columns = {column["name"] for column in inspector.get_columns("ipo_items")}
        if "business_overview" not in columns:
            with _engine.begin() as connection:
                connection.execute(text("ALTER TABLE ipo_items ADD COLUMN business_overview TEXT"))
            logger.info("Database migrated: ipo_items.business_overview added")
        llm_columns = {
            column["name"] for column in inspector.get_columns("llm_evaluations")
        }
        for column_name in (
            "business_quality_reason",
            "financial_health_reason",
            "valuation_fairness_reason",
            "growth_prospect_reason",
        ):
            if column_name not in llm_columns:
                with _engine.begin() as connection:
                    connection.execute(
                        text(f"ALTER TABLE llm_evaluations ADD COLUMN {column_name} TEXT")
                    )
                logger.info(f"Database migrated: llm_evaluations.{column_name} added")
    logger.info(f"Database initialized: {database_url}")


def get_session() -> Session:
    """获取数据库 session。"""
    if _SessionFactory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _SessionFactory()


def get_engine():
    """获取数据库引擎。"""
    return _engine
