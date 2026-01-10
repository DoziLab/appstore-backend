"""Database configuration and session management."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from src.core.config import get_settings

settings = get_settings()


class Base(DeclarativeBase):
    """SQLAlchemy declarative base class."""
    pass


# Database engine
engine = create_engine(settings.database_url, echo=settings.debug)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Initialize database tables."""
    # Import all models here so they are registered with Base.metadata
    from src.models import deployment, user
    
    Base.metadata.create_all(bind=engine)
