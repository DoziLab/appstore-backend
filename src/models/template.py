"""Template database model."""
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from sqlalchemy import String, DateTime, Enum as SQLEnum, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base


class TemplateVisibility(str, Enum):
    """Template visibility values."""
    PRIVATE = "private"
    PUBLIC = "public"


class TemplateApprovalStatus(str, Enum):
    """Template approval status values."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEPRECATED = "deprecated"


class Template(Base):
    """Template database model."""
    
    __tablename__ = "templates"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    repo_url: Mapped[str] = mapped_column(String(500), nullable=False)
    visibility: Mapped[TemplateVisibility] = mapped_column(
        SQLEnum(TemplateVisibility),
        default=TemplateVisibility.PRIVATE
    )
    approval_status: Mapped[TemplateApprovalStatus] = mapped_column(
        SQLEnum(TemplateApprovalStatus),
        default=TemplateApprovalStatus.PENDING
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationships
    owner: Mapped["User"] = relationship("User", back_populates="owned_templates")
    versions: Mapped[list["TemplateVersion"]] = relationship("TemplateVersion", back_populates="template")
    category_assignments: Mapped[list["TemplateCategoryAssignment"]] = relationship("TemplateCategoryAssignment", back_populates="template")

