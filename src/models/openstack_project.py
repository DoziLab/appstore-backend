"""OpenStack Project database model."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import String, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base


class OpenstackProject(Base):
    """OpenStack Project database model."""
    
    __tablename__ = "openstack_projects"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    openstack_project_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    openstack_project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    
    # OpenStack authentication and connection details
    auth_url: Mapped[str] = mapped_column(String(500), nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    password: Mapped[str] = mapped_column(Text, nullable=False)  # Should be encrypted in production
    user_domain_name: Mapped[str] = mapped_column(String(255), nullable=False, default="Default")
    region_name: Mapped[str] = mapped_column(String(100), nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationships
    owner_user: Mapped["User"] = relationship("User", back_populates="openstack_projects")
