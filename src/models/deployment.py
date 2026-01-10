"""Deployment database model."""
from datetime import datetime
from enum import Enum
from uuid import uuid4

from sqlalchemy import String, DateTime, Text, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

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
    
    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    template_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    course_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    status: Mapped[DeploymentStatus] = mapped_column(
        SQLEnum(DeploymentStatus), 
        default=DeploymentStatus.PENDING,
        nullable=False
    )
    stack_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)
