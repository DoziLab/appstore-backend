"""Template Category Assignment database model (many-to-many)."""
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base


class TemplateCategoryAssignment(Base):
    """Template Category Assignment database model."""
    
    __tablename__ = "template_category_assignments"
    
    template_id: Mapped[str] = mapped_column(String(36), ForeignKey("templates.id"), primary_key=True)
    template_categories_id: Mapped[str] = mapped_column(String(36), ForeignKey("template_categories.id"), primary_key=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    # Relationships
    template: Mapped["Template"] = relationship("Template", back_populates="category_assignments")
    category: Mapped["TemplateCategory"] = relationship("TemplateCategory", back_populates="template_assignments")
