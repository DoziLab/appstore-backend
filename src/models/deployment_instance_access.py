"""Deployment Instance Access database model."""
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from sqlalchemy import String, DateTime, Enum as SQLEnum, Text, Integer, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base


class AccessType(str, Enum):
    """Access type values."""
    SSH = "ssh"
    WEB_URL = "web_url"
    GUACAMOLE = "guacamole"
    RDP = "rdp"
    VNC = "vnc"


class DeploymentInstanceAccess(Base):
    """Deployment Instance Access database model.
    
    Stores access credentials and connection details for deployment instances.
    Supports multiple access methods per instance (SSH, web, RDP, etc.).
    """
    
    __tablename__ = "deployment_instance_access"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    deployment_instance_id: Mapped[str] = mapped_column(String(36), ForeignKey("deployment_instances.id"), nullable=False)
    access_type: Mapped[AccessType] = mapped_column(SQLEnum(AccessType), nullable=False)
    
    # Connection details
    connection_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password: Mapped[str | None] = mapped_column(Text, nullable=True)  # Should be encrypted in production
    ssh_private_key: Mapped[str | None] = mapped_column(Text, nullable=True)  # Should be encrypted in production
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    
    # Access control
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationships
    deployment_instance: Mapped["DeploymentInstance"] = relationship("DeploymentInstance", back_populates="access_methods")
