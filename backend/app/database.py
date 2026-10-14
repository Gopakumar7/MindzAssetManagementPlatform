from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args={'connect_timeout': 5} if settings.database_url.startswith('postgresql') else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_database_health() -> tuple[bool, str]:
    try:
        with engine.connect() as connection:
            connection.execute(text('SELECT 1'))
        return True, 'database connection is healthy'
    except SQLAlchemyError as exc:
        return False, f'database unavailable: {exc}'
