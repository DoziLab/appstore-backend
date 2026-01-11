"""Deployment database model."""
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from sqlalchemy import String, DateTime, Enum as SQLEnum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base


class DeploymentStatus(str, Enum):
    """Deployment status values."""
    QUEUED = "queued"
    CREATING = "creating"
    RUNNING = "running"
    FAILED = "failed"
    DELETED = "deleted"

class DeploymentMode(str, Enum):
    """Deployment mode values."""
    PER_COURSE = "per_course"
    PER_GROUP = "per_group"
    PER_STUDENT = "per_student"


class Deployment(Base):
    """Deployment database model."""
    
    __tablename__ = "deployments"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    template_version_id: Mapped[str] = mapped_column(String(36), ForeignKey("template_versions.id"), nullable=False)
    course_id: Mapped[str] = mapped_column(String(36), ForeignKey("courses.id"), nullable=False)
    deployment_mode: Mapped[DeploymentMode] = mapped_column(
        SQLEnum(DeploymentMode),
        nullable=False
    )
    status: Mapped[DeploymentStatus] = mapped_column(
        SQLEnum(DeploymentStatus), 
        default=DeploymentStatus.QUEUED
    )
    openstack_stack_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    config_json: Mapped[str | None] = mapped_column(String, nullable=True)
    access_types_json: Mapped[str] = mapped_column(String, nullable=False, default='["ssh"]')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationships
    template_version: Mapped["TemplateVersion"] = relationship("TemplateVersion", back_populates="deployments")
    course: Mapped["Course"] = relationship("Course", back_populates="deployments")
    instances: Mapped[list["DeploymentInstance"]] = relationship("DeploymentInstance", back_populates="deployment")
    logs: Mapped[list["DeploymentLog"]] = relationship("DeploymentLog", back_populates="deployment")
