"""Template Version File database model."""
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from sqlalchemy import String, DateTime, Text, ForeignKey, Enum as SQLEnum, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base


class FileType(str, Enum):
    """File type values for template version files."""
    APP_MANIFEST = "APP_MANIFEST"
    HEAT_TEMPLATE = "HEAT_TEMPLATE"
    CLOUD_INIT = "CLOUD_INIT"
    ANSIBLE_PLAYBOOK = "ANSIBLE_PLAYBOOK"
    HELM_CHART = "HELM_CHART"
    SHELL_SCRIPT = "SHELL_SCRIPT"
    CONFIG_FILE = "CONFIG_FILE"
    OTHER = "OTHER"


class TemplateVersionFile(Base):
    """Template Version File database model.
    
    Stores individual content files (heat.yaml, cloud-init, etc.) 
    associated with a specific template version.
    """
    
    __tablename__ = "template_version_files"
    __table_args__ = (
        UniqueConstraint('template_version_id', 'file_path', name='uq_template_version_file_path'),
    )
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    template_version_id: Mapped[str] = mapped_column(String(36), ForeignKey("template_versions.id"), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[FileType] = mapped_column(
        SQLEnum(FileType),
        default=FileType.OTHER,
        nullable=False
    )
    file_path: Mapped[str] = mapped_column(String(500), nullable=False, comment="Relative path in the git repository")
    content: Mapped[str | None] = mapped_column(Text, nullable=True, comment="Cached file content")
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="File size in bytes")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_primary: Mapped[bool] = mapped_column(default=False, comment="Primary file for deployment (e.g., main heat.yaml)")
    order: Mapped[int] = mapped_column(Integer, default=0, comment="Execution order if applicable")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )
    
    # Relationships
    template_version: Mapped["TemplateVersion"] = relationship("TemplateVersion", back_populates="files")
