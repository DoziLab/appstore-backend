"""User database model."""
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base


class UserRole(str, Enum):
    """User role values.
    
    NOTE: Roles are NOT stored in database.
    They are read from Keycloak token on every request.
    This enum is only for type hints and validation.
    """
    ADMIN = "admin"
    LECTURER = "lecturer"
    STUDENT = "student"


class User(Base):
    """Minimal user record for database relationships only.
    
    DESIGN PRINCIPLE:
    =================
    This table stores ONLY what's needed for foreign key relationships.
    All user attributes (email, name, roles) come from Keycloak token.
    
    Why this table exists:
    - Enable foreign keys: courses.lecturer_id → users.id
    - Referential integrity in PostgreSQL
    - Audit trail: Track who created resources
    
    What this table does NOT store:
    - email (read from token)
    - name (read from token)
    - roles (read from token - Keycloak is source of truth)
    - is_active (read from token)
    
    User sync on login:
    - First login → User created with external_id from token
    - Subsequent logins → last_login_at updated
    """
    
    __tablename__ = "users"
    
    # Local UUID for foreign key relationships
    id: Mapped[str] = mapped_column(
        String(36), 
        primary_key=True, 
        default=lambda: str(uuid4()),
        comment="Local user ID for foreign keys"
    )
    
    # Keycloak user ID (token 'sub' claim) - links to Keycloak
    external_id: Mapped[str] = mapped_column(
        String(255), 
        nullable=False, 
        unique=True,
        index=True,
        comment="Keycloak user UUID (sub claim) - IMMUTABLE"
    )
    
    # Audit: When was user first seen?
    created_at: Mapped[datetime] = mapped_column(
        DateTime, 
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="First login timestamp"
    )
    
    # Audit: When did user last login?
    last_login_at: Mapped[datetime] = mapped_column(
        DateTime, 
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="Last successful login timestamp"
    )
    
    # Relationships (reason this table exists)
    course_memberships: Mapped[list["CourseMember"]] = relationship(
        "CourseMember", 
        back_populates="user"
    )
    
    taught_courses: Mapped[list["Course"]] = relationship(
        "Course", 
        back_populates="lecturer", 
        foreign_keys="Course.lecturer_id"
    )
    
    openstack_projects: Mapped[list["OpenstackProject"]] = relationship(
        "OpenstackProject", 
        back_populates="owner_user"
    )
    
    owned_templates: Mapped[list["Template"]] = relationship(
        "Template", 
        back_populates="owner"
    )
