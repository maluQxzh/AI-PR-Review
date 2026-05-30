from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


engine = create_engine(
    get_settings().database_url,
    connect_args={"check_same_thread": False}
    if get_settings().database_url.startswith("sqlite")
    else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    from app.db import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_lightweight_columns()


def _ensure_lightweight_columns() -> None:
    if not get_settings().database_url.startswith("sqlite"):
        return
    with engine.begin() as connection:
        rows = connection.execute(text("PRAGMA table_info(reports)")).mappings().all()
        existing = {row["name"] for row in rows}
        if rows and "analysis_source" not in existing:
            connection.execute(text("ALTER TABLE reports ADD COLUMN analysis_source VARCHAR"))
        if rows and "analysis_detail" not in existing:
            connection.execute(text("ALTER TABLE reports ADD COLUMN analysis_detail TEXT"))
        if rows and "review_context" not in existing:
            connection.execute(text("ALTER TABLE reports ADD COLUMN review_context JSON"))
        if rows and "context_summary" not in existing:
            connection.execute(text("ALTER TABLE reports ADD COLUMN context_summary JSON"))

        file_rows = connection.execute(text("PRAGMA table_info(changed_files)")).mappings().all()
        file_existing = {row["name"] for row in file_rows}
        if file_rows and "context" not in file_existing:
            connection.execute(text("ALTER TABLE changed_files ADD COLUMN context JSON"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
