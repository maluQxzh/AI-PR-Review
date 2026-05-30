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
        if rows and "generated_artifacts" not in existing:
            connection.execute(text("ALTER TABLE reports ADD COLUMN generated_artifacts JSON"))
        if rows and "mode" not in existing:
            connection.execute(
                text("ALTER TABLE reports ADD COLUMN mode VARCHAR DEFAULT 'standard'")
            )
        if rows and "cancel_requested" not in existing:
            connection.execute(
                text("ALTER TABLE reports ADD COLUMN cancel_requested BOOLEAN DEFAULT 0")
            )
        if rows and "retry_of" not in existing:
            connection.execute(text("ALTER TABLE reports ADD COLUMN retry_of VARCHAR"))
        if rows and "attempt_count" not in existing:
            connection.execute(
                text("ALTER TABLE reports ADD COLUMN attempt_count INTEGER DEFAULT 1")
            )
        if rows and "completed_at" not in existing:
            connection.execute(text("ALTER TABLE reports ADD COLUMN completed_at DATETIME"))
        if rows and "duration_seconds" not in existing:
            connection.execute(text("ALTER TABLE reports ADD COLUMN duration_seconds INTEGER"))
        file_rows = connection.execute(
            text("PRAGMA table_info(changed_files)")
        ).mappings().all()
        file_existing = {row["name"] for row in file_rows}
        if file_rows and "context" not in file_existing:
            connection.execute(text("ALTER TABLE changed_files ADD COLUMN context JSON"))
        if file_rows and "risk_dimensions" not in file_existing:
            connection.execute(text("ALTER TABLE changed_files ADD COLUMN risk_dimensions JSON"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
