"""Database configuration and session management."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from src.core.config import get_settings


class Base(DeclarativeBase):
    """SQLAlchemy declarative base class."""
    pass


def _get_engine():
    """Create database engine lazily."""
    settings = get_settings()
    return create_engine(settings.database_url, echo=settings.debug)


# Database engine (created lazily)
engine = _get_engine()

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """FastAPI dependency to get database session.
    
    Yields a database session and ensures it's closed after use.
    
    Usage:
        @router.get("/items")
        async def get_items(db: Session = Depends(get_db)):
            return db.query(Item).all()
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Initialize database tables.
    
    Imports models here to avoid circular import issues.
    Note: resource_usage_cache is stored in Redis, not PostgreSQL.
    """
    # Import all models to register them with SQLAlchemy metadata
    # fmt: off
    from src.models import (  # noqa: F401
        deployment,
        deployment_instance,
        deployment_instance_access,
        deployment_log,
        template,
        template_category,
        template_category_assignment,
        template_version,
        user,
        course,
        course_member,
        course_group,
        group_member,
        openstack_project,
    )
    # fmt: on
    
    Base.metadata.create_all(bind=engine)
