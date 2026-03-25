from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.config import settings


# SQLite is fine for this scale — one process, moderate write volume.
# The check_same_thread=False is needed because FastAPI runs in a threadpool.
# If we ever switch to Postgres, just change DATABASE_URL and remove connect_args.
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
    echo=settings.DEBUG,
)


# WAL mode lets readers and writers work at the same time without blocking each other.
# foreign_keys=ON is off by default in SQLite — always worth enabling.
if "sqlite" in settings.DATABASE_URL:
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency: yields a DB session and closes it afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables on first run."""
    from app.models import db_models  # noqa: F401 – side-effect import
    Base.metadata.create_all(bind=engine)
