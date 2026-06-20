"""User database model."""
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import String, DateTime, BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base

if TYPE_CHECKING:
    from src.models.course_member import CourseMember
    from src.models.openstack_project import OpenstackProject
    from src.models.template import Template


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
    """Minimal user record for database relationships + cached display fields.

    DESIGN PRINCIPLE:
    =================
    This table stores what's needed for foreign key relationships, plus a
    small set of CACHED display fields (display_name, email, username) so
    the API can render owner names without round-tripping to Keycloak on
    every request.

    Source of truth for everything user-related is still the Keycloak JWT
    token. Roles in particular are NEVER read from this table — they come
    exclusively from `realm_access.roles` on the token, on every request.
    The cached fields below may be stale until the user logs in again.

    Why this table exists:
    - Enable foreign keys: courses.lecturer_id → users.id
    - Referential integrity in PostgreSQL
    - Audit trail: Track who created resources
    - Cached display fields for owner-name lookups (e.g. Template approval
      cards), refreshed on every login

    What this table does NOT store:
    - roles (read from token - Keycloak is source of truth)
    - is_active (read from token)

    User sync on login:
    - First login → User created with external_id + display fields from token
    - Subsequent logins → last_login_at updated; display fields refreshed
      if the token claims differ
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

    # Cached display fields, refreshed from the JWT on every login.
    # Display-only — never used for authorization. Source of truth is Keycloak.
    display_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Cached full name from Keycloak token 'name' claim; nullable for legacy rows"
    )
    email: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Cached email from Keycloak token; nullable for legacy rows"
    )
    username: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Cached preferred_username from Keycloak token; nullable for legacy rows"
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

    # GitHub App installation linking the user to a GitHub install of our App.
    # Used by /import-from-github to mint short-lived installation tokens with
    # `Contents: Read-only` permission. Not a secret (just an identifier);
    # the actual token is minted server-side and never stored.
    github_installation_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        comment="GitHub App installation ID for this user; null if not connected",
    )
    
    # Relationships (reason this table exists)
    course_memberships: Mapped[list["CourseMember"]] = relationship(
        "CourseMember", 
        back_populates="user"
    )
    
    openstack_projects: Mapped[list["OpenstackProject"]] = relationship(
        "OpenstackProject", 
        back_populates="owner_user"
    )
    
    owned_templates: Mapped[list["Template"]] = relationship(
        "Template", 
        back_populates="owner"
    )
