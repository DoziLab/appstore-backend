"""Template Category database model."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import String, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base


class TemplateCategory(Base):
    """Template Category database model."""
    
    __tablename__ = "template_categories"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationships
    template_assignments: Mapped[list["TemplateCategoryAssignment"]] = relationship("TemplateCategoryAssignment", back_populates="category")
