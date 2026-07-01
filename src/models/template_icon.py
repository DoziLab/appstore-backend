"""Template Icon database model.

Speichert hochgeladene Icon-Bilder als Binärdaten in einer eigenen Tabelle,
damit große BLOBs nicht in jedem ``SELECT * FROM templates`` mitgeschleppt
werden. Ein Template hat maximal ein Icon (1:0..1 Beziehung, via unique FK
auf ``templates.icon_file_id``); Cascade-Delete räumt die Row auf, wenn das
Template selbst gelöscht wird.

Zulässige Bildformate und die Größenobergrenze werden im Service-Layer
validiert (siehe ``template_icon_service.py``), nicht in der DB.
"""
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, deferred, mapped_column, relationship

from src.core.database import Base

if TYPE_CHECKING:
    from src.models.template import Template


class TemplateIcon(Base):
    """Persistiertes Icon-Bild für ein Template."""

    __tablename__ = "template_icons"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    template_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("templates.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        comment="Owning template — 1:1, jedes Template hat höchstens ein Icon.",
    )
    content: Mapped[bytes] = deferred(
        mapped_column(
            LargeBinary,
            nullable=False,
            comment="Rohbytes des Bildes (PNG/JPEG/WebP).",
        )
    )
    content_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="MIME-Typ, wird beim Ausliefern als Content-Type-Header verwendet.",
    )
    file_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Original-Dateiname (für Content-Disposition).",
    )
    size_bytes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Größe von ``content`` in Bytes — redundant, aber praktisch für Listing/Debug.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    template: Mapped["Template"] = relationship("Template", back_populates="icon")
