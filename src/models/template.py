"""Template database model."""
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from sqlalchemy import String, DateTime, Enum as SQLEnum, Text, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base


class TemplateVisibility(str, Enum):
    """Template visibility values."""
    PRIVATE = "private"
    PUBLIC = "public"


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
    # Owner-Wunsch „bitte veröffentlichen, sobald erste Version approved ist".
    # Wir flippen das Template NICHT direkt auf PUBLIC, wenn der Owner beim
    # Erstellen „öffentlich" wählt — stattdessen bleibt es PRIVATE und dieses
    # Flag merkt sich den Veröffentlichungswunsch. Beim ersten admin-approve
    # einer Version flippt die Service-Logik atomar `visibility → PUBLIC` und
    # `publish_requested → False`. Bei reject wird der Wunsch verworfen;
    # Owner muss erneut über PATCH `visibility: public` anstoßen.
    publish_requested: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        server_default="false",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    owner: Mapped["User"] = relationship("User", back_populates="owned_templates")
    versions: Mapped[list["TemplateVersion"]] = relationship(
        "TemplateVersion",
        back_populates="template",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    category_assignments: Mapped[list["TemplateCategoryAssignment"]] = relationship("TemplateCategoryAssignment", back_populates="template")

    # Hochgeladenes Icon-Bild (optional). Getrennte Tabelle statt Spalte am
    # Template, damit ``SELECT * FROM templates`` keinen 1-5 MB BLOB pro Row
    # mitlädt. ``uselist=False`` weil per Unique-Constraint auf
    # ``template_icons.template_id`` maximal ein Icon pro Template existiert.
    # Die ``content``-Spalte auf ``TemplateIcon`` ist ``deferred``, wird also
    # nur beim Serve-Endpoint tatsächlich aus der DB gezogen.
    icon: Mapped["TemplateIcon | None"] = relationship(
        "TemplateIcon",
        back_populates="template",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )


