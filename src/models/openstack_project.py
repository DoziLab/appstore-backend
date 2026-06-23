"""OpenStack Project database model."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base
from src.services.secret_encryption_service import EncryptedString


class OpenstackProject(Base):
    """OpenStack Project database model.
    
    IMPORTANT: username and password fields are automatically encrypted/decrypted using EncryptedString type.
    Never log these credential values.
    
    Each user can have exactly one OpenStack project. The combination of (owner_user_id, openstack_project_id)
    must be unique.
    """
    
    __tablename__ = "openstack_projects"
    __table_args__ = (
        UniqueConstraint('owner_user_id', 'openstack_project_id', name='uq_openstack_project_user'),
    )
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    openstack_project_id: Mapped[str] = mapped_column(String(255), nullable=False)
    openstack_project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    
    # OpenStack authentication and connection details
    auth_url: Mapped[str] = mapped_column(String(500), nullable=False)
    # Automatically encrypted at rest, decrypted on read. NEVER log these values.
    username: Mapped[str] = mapped_column(EncryptedString(500), nullable=False)
    password: Mapped[str] = mapped_column(EncryptedString(500), nullable=False)
    user_domain_name: Mapped[str] = mapped_column(String(255), nullable=False, default="Default")
    region_name: Mapped[str] = mapped_column(String(100), nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationships
    owner_user: Mapped["User"] = relationship("User", back_populates="openstack_projects")
    deployments: Mapped[list["Deployment"]] = relationship("Deployment", back_populates="openstack_project")
