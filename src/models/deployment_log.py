"""Deployment Log database model."""
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from sqlalchemy import String, DateTime, Enum as SQLEnum, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base


class DeploymentLogLevel(str, Enum):
    """Deployment log level values."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class DeploymentLogEventType(str, Enum):
    """Deployment log event type values."""
    DEPLOYMENT_STARTED = "deployment_started"
    GIT_CLONE = "git_clone"
    TEMPLATE_CREATE = "template_create"
    VM_READY = "vm_ready"
    FAILED = "failed"


class DeploymentLog(Base):
    """Deployment Log database model."""
    
    __tablename__ = "deployment_logs"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    deployment_id: Mapped[str] = mapped_column(String(36), ForeignKey("deployments.id"), nullable=False)
    level: Mapped[DeploymentLogLevel] = mapped_column(
        SQLEnum(DeploymentLogLevel),
        default=DeploymentLogLevel.INFO
    )
    event_type: Mapped[DeploymentLogEventType] = mapped_column(
        SQLEnum(DeploymentLogEventType),
        nullable=False
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    # Relationships
    deployment: Mapped["Deployment"] = relationship("Deployment", back_populates="logs")
