from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from sqlalchemy import String, DateTime, Enum as SQLEnum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base


class DeploymentInstanceStatus(str, Enum):
    """Deployment instance status values."""
    CREATING = "creating"
    RUNNING = "running"
    FAILED = "failed"
    DELETED = "deleted"



class DeploymentInstance(Base):
    """DeploymentInstance database model."""
    
    __tablename__ = "deployment_instances"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    deployment_id: Mapped[str] = mapped_column(String(36), ForeignKey("deployments.id"), nullable=False)
    group_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("course_groups.id"), nullable=True)
    course_member_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("course_members.id"), nullable=True)
    vm_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    openstack_server_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    status: Mapped[DeploymentInstanceStatus] = mapped_column(
        SQLEnum(DeploymentInstanceStatus), 
        default=DeploymentInstanceStatus.CREATING
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    deployment: Mapped["Deployment"] = relationship("Deployment", back_populates="instances")
    group: Mapped["CourseGroup | None"] = relationship("CourseGroup", back_populates="deployment_instances")
    course_member: Mapped["CourseMember | None"] = relationship("CourseMember", back_populates="deployment_instances")
    access_methods: Mapped[list["DeploymentInstanceAccess"]] = relationship("DeploymentInstanceAccess", back_populates="deployment_instance")
