"""Course database model."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import String, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base


class Course(Base):
    """Course database model."""
    
    __tablename__ = "courses"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    semester: Mapped[str] = mapped_column(String(50), nullable=False)
    lecturer_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationships
    lecturer: Mapped["User"] = relationship("User", back_populates="taught_courses", foreign_keys=[lecturer_id])
    members: Mapped[list["CourseMember"]] = relationship("CourseMember", back_populates="course")
    groups: Mapped[list["CourseGroup"]] = relationship("CourseGroup", back_populates="course")
    deployments: Mapped[list["Deployment"]] = relationship("Deployment", back_populates="course")
