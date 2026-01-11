"""Group Member database model."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import String, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base


class GroupMember(Base):
    """Group Member database model."""
    
    __tablename__ = "group_members"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    group_id: Mapped[str] = mapped_column(String(36), ForeignKey("course_groups.id"), nullable=False)
    course_member_id: Mapped[str] = mapped_column(String(36), ForeignKey("course_members.id"), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    # Relationships
    group: Mapped["CourseGroup"] = relationship("CourseGroup", back_populates="members")
    course_member: Mapped["CourseMember"] = relationship("CourseMember", back_populates="group_memberships")
