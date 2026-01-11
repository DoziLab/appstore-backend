"""Course Group database model."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import String, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base


class CourseGroup(Base):
    """Course Group database model."""
    
    __tablename__ = "course_groups"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    course_id: Mapped[str] = mapped_column(String(36), ForeignKey("courses.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationships
    course: Mapped["Course"] = relationship("Course", back_populates="groups")
    members: Mapped[list["GroupMember"]] = relationship("GroupMember", back_populates="group")
    deployment_instances: Mapped[list["DeploymentInstance"]] = relationship("DeploymentInstance", back_populates="group")
