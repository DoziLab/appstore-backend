"""Deployment Instance Access database model."""
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from sqlalchemy import String, DateTime, Enum as SQLEnum, Integer, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base
from src.services.secret_encryption_service import EncryptedString


class AccessType(str, Enum):
    """Access type values."""
    SSH = "ssh"
    WEB_URL = "web_url"
    GUACAMOLE = "guacamole"
    RDP = "rdp"
    VNC = "vnc"
    DATABASE = "database"
    # One-time activation/setup link the playbook generates on the VM
    # (e.g. Overleaf account setup). Carried in connection_url; no
    # password / SSH key. Stored as a Postgres enum value of the same
    # name — see the Alembic migration that adds it.
    ACTIVATION_LINK = "activation_link"


class DeploymentInstanceAccess(Base):
    """Deployment Instance Access database model.

    Stores access credentials and connection details for deployment instances.
    Supports multiple access methods per instance (SSH, web, RDP, etc.).
    """

    __tablename__ = "deployment_instance_access"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    deployment_instance_id: Mapped[str] = mapped_column(String(36), ForeignKey("deployment_instances.id"), nullable=False)
    access_type: Mapped[AccessType] = mapped_column(SQLEnum(AccessType), nullable=False)

    # The course_group this access entry belongs to. NULL means the entry is
    # NOT tied to any student group — typically the lecturer's admin
    # credentials. Students can only see rows where they are a member of the
    # referenced group; admin rows (group_id IS NULL) are filtered out for
    # them. See src/api/student.py for the authorization helper.
    group_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("course_groups.id"), nullable=True)

    # Connection details. password and ssh_private_key are Fernet-encrypted at rest
    # via EncryptedString and decrypted transparently on read; never log them.
    connection_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    ssh_private_key: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Access control
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    deployment_instance: Mapped["DeploymentInstance"] = relationship("DeploymentInstance", back_populates="access_methods")
    group: Mapped["CourseGroup | None"] = relationship("CourseGroup")
