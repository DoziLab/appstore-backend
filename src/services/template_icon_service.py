"""Template icon service.

Kapselt Upload, Auslieferung und Löschen des hochgeladenen Icon-Bilds eines
Templates. Der Endpoint-Layer prüft Rollen und Ownership; der Service prüft
Bild-Format und -Größe und delegiert die eigentliche Datenbank-Interaktion
ans Repository.
"""
import logging
from typing import Optional

from sqlalchemy.orm import Session

from src.core.config import get_settings
from src.core.exceptions import BadRequestException, ForbiddenException
from src.models.template import Template
from src.models.template_icon import TemplateIcon
from src.repositories.template_icon_repository import TemplateIconRepository
from src.services.template_service import TemplateService

logger = logging.getLogger(__name__)


class TemplateIconService:
    """Service für den Upload/Serve/Delete-Lebenszyklus eines Template-Icons."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = TemplateIconRepository(db)
        self.template_service = TemplateService(db)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------
    def get_icon(
        self,
        template_id: str,
        *,
        user_id: str,
        is_admin: bool = False,
    ) -> TemplateIcon:
        """Return the icon row for a template, gated by visibility.

        Sichtbarkeitsregeln matchen ``TemplateService.get_template``:
        Admin darf alles, Owner darf sein eigenes, Fremde nur PUBLIC-Templates
        mit mindestens einer APPROVED Version. Wenn das Template zwar
        sichtbar ist, aber kein Icon hochgeladen wurde, wird 404 geworfen.
        """
        # ``get_template`` wirft NotFound/Forbidden nach denselben Regeln,
        # die auch beim normalen Template-GET greifen.
        self.template_service.get_template(template_id, user_id=user_id, is_admin=is_admin)

        icon = self.repo.get_by_template_id(template_id)
        if not icon:
            # Bewusst 404, nicht 204: der Client bekommt sonst einen
            # Content-Type: application/json ohne Body und rätselt.
            from src.core.exceptions import NotFoundException

            raise NotFoundException(f"Template {template_id} has no uploaded icon")
        return icon

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------
    def upload_icon(
        self,
        template_id: str,
        *,
        content: bytes,
        content_type: str,
        file_name: Optional[str],
        user_id: str,
        is_admin: bool = False,
    ) -> TemplateIcon:
        """Persist a new icon for a template (create or replace).

        Nur Owner oder Admin dürfen ein Icon setzen. Validierung:
        - Content-Type muss in ``settings.allowed_icon_content_types`` sein
          (Default: PNG/JPEG/WebP) → sonst 415.
        - ``content`` darf ``settings.max_icon_size_bytes`` nicht überschreiten
          → sonst 413.
        - Leere Uploads werden abgelehnt (400).
        """
        template = self._require_owner_or_admin(template_id, user_id=user_id, is_admin=is_admin)
        settings = get_settings()

        # 1) Content-Type-Prüfung — via 415 statt 400, damit Clients gezielt
        #    reagieren können ("bitte anderes Format wählen").
        normalized = (content_type or "").split(";", 1)[0].strip().lower()
        if normalized not in settings.allowed_icon_content_types:
            from starlette.exceptions import HTTPException

            raise HTTPException(
                status_code=415,
                detail=(
                    f"Unsupported icon content type: {content_type!r}. "
                    f"Allowed: {', '.join(settings.allowed_icon_content_types)}"
                ),
            )

        # 2) Größe.
        size = len(content)
        if size == 0:
            raise BadRequestException("Uploaded icon file is empty")
        if size > settings.max_icon_size_bytes:
            from starlette.exceptions import HTTPException

            raise HTTPException(
                status_code=413,
                detail=(
                    f"Icon file too large: {size} bytes "
                    f"(max {settings.max_icon_size_bytes} bytes)"
                ),
            )

        # 3) Persistieren — create-or-replace. Wir modifizieren die bestehende
        #    Row statt sie zu löschen+neu-anzulegen, damit ``id`` und
        #    ``created_at`` stabil bleiben (Cache-Buster im Frontend nutzt
        #    ``updated_at``).
        existing = self.repo.get_by_template_id(template_id)
        if existing:
            existing.content = content
            existing.content_type = normalized
            existing.file_name = file_name
            existing.size_bytes = size
            self.db.commit()
            self.db.refresh(existing)
            icon = existing
            action = "replaced"
        else:
            icon = self.repo.create(
                template_id=template.id,
                content=content,
                content_type=normalized,
                file_name=file_name,
                size_bytes=size,
            )
            action = "created"

        logger.info(
            "Template icon %s",
            action,
            extra={
                "template_id": template_id,
                "user_id": user_id,
                "icon_id": icon.id,
                "size_bytes": size,
                "content_type": normalized,
            },
        )
        return icon

    def delete_icon(
        self,
        template_id: str,
        *,
        user_id: str,
        is_admin: bool = False,
    ) -> bool:
        """Remove the uploaded icon for a template.

        Returns True if something was deleted, False if the template
        already had no icon. In both cases the endpoint returns 204;
        the boolean is exposed for tests.
        """
        self._require_owner_or_admin(template_id, user_id=user_id, is_admin=is_admin)
        deleted = self.repo.delete_by_template_id(template_id)
        if deleted:
            logger.info(
                "Template icon deleted",
                extra={"template_id": template_id, "user_id": user_id},
            )
        return deleted

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _require_owner_or_admin(
        self,
        template_id: str,
        *,
        user_id: str,
        is_admin: bool,
    ) -> Template:
        """Load template + enforce owner-or-admin gate for mutating ops."""
        template = self.template_service.get_template(
            template_id,
            user_id=user_id,
            is_admin=is_admin,
        )
        if template.owner_id != user_id and not is_admin:
            raise ForbiddenException(
                "You do not have permission to manage the icon of this template"
            )
        return template
