"""Template Version database model."""
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import String, DateTime, Boolean, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base

if TYPE_CHECKING:
    from src.models.template import Template
    from src.models.deployment import Deployment
    from src.models.template_version_file import TemplateVersionFile


class TemplateVersionApprovalStatus(str, Enum):
    """Approval status values for template versions."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEPRECATED = "deprecated"


class TemplateVersion(Base):
    """Template Version database model."""

    __tablename__ = "template_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    template_id: Mapped[str] = mapped_column(String(36), ForeignKey("templates.id"), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False, comment="Semantic version (e.g., 0.2.0)")
    git_commit_sha: Mapped[str] = mapped_column(String(255), nullable=False, comment="Git commit SHA or tag")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    approval_status: Mapped[TemplateVersionApprovalStatus] = mapped_column(
        SQLEnum(TemplateVersionApprovalStatus, name="templateversionapprovalstatus"),
        default=TemplateVersionApprovalStatus.PENDING,
        nullable=False,
    )
    approved_by_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True,
        comment="Admin who approved/rejected this version",
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    template: Mapped["Template"] = relationship("Template", back_populates="versions")
    deployments: Mapped[list["Deployment"]] = relationship("Deployment", back_populates="template_version")
    files: Mapped[list["TemplateVersionFile"]] = relationship("TemplateVersionFile", back_populates="template_version")
