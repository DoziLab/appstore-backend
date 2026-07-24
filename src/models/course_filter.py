"""Course filter (frontend chip/blob) database model.

Admin-verwaltete Strings, mit denen das Frontend Kursnamen filtert. Die Filter
sind reine Such-Begriffe (z. B. „SQL", „Web 2026") — sie werden NICHT einem
Kurs zugewiesen, sondern client-seitig auf ``Course.name`` angewandt.
"""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class CourseFilter(Base):
    """Filter-Tag für Kursnamen (Frontend-Chips)."""

    __tablename__ = "course_filters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        comment="Anzeige-/Such-String, den das Frontend gegen Kursnamen matcht",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
