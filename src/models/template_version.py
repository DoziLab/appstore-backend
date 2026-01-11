"""Template Version database model."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import String, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base


class TemplateVersion(Base):
    """Template Version database model."""
    
    __tablename__ = "template_versions"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    template_id: Mapped[str] = mapped_column(String(36), ForeignKey("templates.id"), nullable=False)
    git_commit_sha: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    # Relationships
    template: Mapped["Template"] = relationship("Template", back_populates="versions")
    deployments: Mapped[list["Deployment"]] = relationship("Deployment", back_populates="template_version")
    