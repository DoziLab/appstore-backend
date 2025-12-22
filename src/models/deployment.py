"""Deployment database model."""
from datetime import datetime
from enum import Enum
from uuid import uuid4

from sqlalchemy import String, DateTime, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class DeploymentStatus(str, Enum):
    """Deployment status values."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class Deployment(Base):
    """Deployment database model."""
    
    __tablename__ = "deployments"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    template_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[DeploymentStatus] = mapped_column(
        SQLEnum(DeploymentStatus), 
        default=DeploymentStatus.PENDING
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
