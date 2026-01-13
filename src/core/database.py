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
    # Enable pool_pre_ping to detect and recycle stale/closed connections
    # which prevents "server closed the connection unexpectedly" errors
    return create_engine(
        settings.database_url,
        echo=settings.debug,
        pool_pre_ping=True,
    )


# Database engine (created lazily)
engine = _get_engine()

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


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
        template_content,
        user,
        course,
        course_member,
        course_group,
        group_member,
        openstack_project,
    )
    # fmt: on
    
    Base.metadata.create_all(bind=engine)
