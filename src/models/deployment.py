"""Deployment database model."""
from typing import Optional
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
    RESTARTING = "restarting"
    DELETING = "deleting"
    FAILED = "failed"
    DELETED = "deleted"


class Deployment(Base):
    """Deployment database model."""
    
    __tablename__ = "deployments"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="Deployment name for identification")
    template_version_id: Mapped[str] = mapped_column(String(36), ForeignKey("template_versions.id"), nullable=False)
    course_id: Mapped[str] = mapped_column(String(36), ForeignKey("courses.id"), nullable=False, comment="Course ID (auto-created from Keycloak course_id)")
    openstack_project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("openstack_projects.id"),
        nullable=False,
        comment="FK to openstack_projects.id (local DB primary key, NOT the Keystone tenant UUID)",
    )
    status: Mapped[DeploymentStatus] = mapped_column(
        SQLEnum(DeploymentStatus),
        default=DeploymentStatus.QUEUED
    )
    openstack_stack_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    deployment_parameters: Mapped[Optional[str]] = mapped_column(String, nullable=True, comment="Heat parameters, stack_assignments, and teacher info as JSON")
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="When this deployment is hard-deleted by the daily expire_deployments_task; NULL = never expire",
    )
    expiry_warning_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When the UI should start showing the 'expires soon' warning; computed at creation/extend",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    course: Mapped["Course"] = relationship("Course", back_populates="deployments")
    template_version: Mapped["TemplateVersion"] = relationship("TemplateVersion", back_populates="deployments")
    openstack_project: Mapped["OpenstackProject"] = relationship("OpenstackProject", back_populates="deployments")
    instances: Mapped[list["DeploymentInstance"]] = relationship("DeploymentInstance", back_populates="deployment")
    logs: Mapped[list["DeploymentLog"]] = relationship("DeploymentLog", back_populates="deployment")
