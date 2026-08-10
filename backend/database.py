"""
Database engine/session setup.

V0 note: tables are created at startup with `Base.metadata.create_all()`
(see backend/main.py) rather than through a migration tool. This is fine for
a fresh V0 deployment but will need Alembic (or similar) as soon as the schema
needs to evolve on a database that already has data. Flagged in CLAUDE.md.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

import config

connect_args = {"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(config.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency: yields a DB session, always closed after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
