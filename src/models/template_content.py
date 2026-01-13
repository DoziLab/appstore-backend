"""Template Content database model."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import String, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base


class TemplateContent(Base):
    """Template Content database model.
    
    Stores versioned Heat template YAML content for deployments.
    Each template can have multiple versions.
    """
    
    __tablename__ = "template_contents"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    template_id: Mapped[str] = mapped_column(String(36), ForeignKey("templates.id"), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="Heat template YAML content")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationships
    template: Mapped["Template"] = relationship("Template", back_populates="contents")
    
    # Unique constraint: one version per template
    __table_args__ = (
        UniqueConstraint('template_id', 'version', name='uq_template_version'),
    )
