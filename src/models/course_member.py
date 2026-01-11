"""Course Member database model."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import String, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base


class CourseMember(Base):
    """Course Member database model."""
    
    __tablename__ = "course_members"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    course_id: Mapped[str] = mapped_column(String(36), ForeignKey("courses.id"), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    left_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    
    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="course_memberships")
    course: Mapped["Course"] = relationship("Course", back_populates="members")
    group_memberships: Mapped[list["GroupMember"]] = relationship("GroupMember", back_populates="course_member")
    deployment_instances: Mapped[list["DeploymentInstance"]] = relationship("DeploymentInstance", back_populates="course_member")
