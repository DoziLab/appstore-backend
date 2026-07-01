"""Unit-Tests für den Template-Icon-Service.

Testen Content-Type-Whitelist, Größenlimit, Owner/Admin-Gate, sowie den
Create-vs-Replace-Zweig. Wir vermeiden echte DB-Setups und nutzen
MagicMock-Sessions — die Zusammenarbeit mit dem Repository ist trivial
genug, dass die Interaktion pro Testfall stubbbar ist.
"""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from starlette.exceptions import HTTPException

from src.core.exceptions import BadRequestException, ForbiddenException
from src.models.template import Template, TemplateVisibility
from src.models.template_icon import TemplateIcon
from src.services.template_icon_service import TemplateIconService


def _tpl(owner_id: str = "owner-1") -> Template:
    """Build a plain Template ORM object (no DB) with the fields the
    service touches. ``visibility=PUBLIC`` because ``get_template`` also
    checks the general visibility gate — for owner access that check is
    a no-op, but we want to be defensive.
    """
    t = Template()
    t.id = str(uuid4())
    t.name = "demo"
    t.description = None
    t.owner_id = owner_id
    t.repo_url = "https://example.com"
    t.icon_url = None
    t.visibility = TemplateVisibility.PRIVATE
    t.publish_requested = False
    t.versions = []
    return t


def _service_with_stubs(template: Template) -> TemplateIconService:
    """Wire a service with mocked ``template_service`` + ``repo`` so we
    can drive the two collaborators without a real DB."""
    svc = TemplateIconService(MagicMock())
    svc.template_service = MagicMock()
    svc.template_service.get_template.return_value = template
    svc.repo = MagicMock()
    return svc


# ---------------------------------------------------------------------------
# Upload — content-type validation
# ---------------------------------------------------------------------------
class TestUploadContentTypes:
    def test_png_accepted(self):
        tpl = _tpl()
        svc = _service_with_stubs(tpl)
        svc.repo.get_by_template_id.return_value = None
        svc.repo.create.return_value = TemplateIcon(
            id=str(uuid4()),
            template_id=tpl.id,
            content=b"x",
            content_type="image/png",
            file_name="a.png",
            size_bytes=1,
        )
        icon = svc.upload_icon(
            tpl.id,
            content=b"x",
            content_type="image/png",
            file_name="a.png",
            user_id="owner-1",
        )
        assert icon.content_type == "image/png"

    def test_jpeg_accepted(self):
        tpl = _tpl()
        svc = _service_with_stubs(tpl)
        svc.repo.get_by_template_id.return_value = None
        svc.repo.create.return_value = TemplateIcon(
            id=str(uuid4()),
            template_id=tpl.id,
            content=b"y",
            content_type="image/jpeg",
            file_name="a.jpg",
            size_bytes=1,
        )
        icon = svc.upload_icon(
            tpl.id,
            content=b"y",
            content_type="image/jpeg",
            file_name="a.jpg",
            user_id="owner-1",
        )
        assert icon.content_type == "image/jpeg"

    def test_webp_accepted(self):
        tpl = _tpl()
        svc = _service_with_stubs(tpl)
        svc.repo.get_by_template_id.return_value = None
        svc.repo.create.return_value = TemplateIcon(
            id=str(uuid4()),
            template_id=tpl.id,
            content=b"z",
            content_type="image/webp",
            file_name=None,
            size_bytes=1,
        )
        icon = svc.upload_icon(
            tpl.id,
            content=b"z",
            content_type="image/webp",
            file_name=None,
            user_id="owner-1",
        )
        assert icon.content_type == "image/webp"

    def test_svg_rejected_with_415(self):
        """SVG ist bewusst nicht erlaubt (XML-Payload / Skript-Vektor)."""
        tpl = _tpl()
        svc = _service_with_stubs(tpl)
        with pytest.raises(HTTPException) as exc:
            svc.upload_icon(
                tpl.id,
                content=b"<svg/>",
                content_type="image/svg+xml",
                file_name="a.svg",
                user_id="owner-1",
            )
        assert exc.value.status_code == 415

    def test_plain_text_rejected_with_415(self):
        tpl = _tpl()
        svc = _service_with_stubs(tpl)
        with pytest.raises(HTTPException) as exc:
            svc.upload_icon(
                tpl.id,
                content=b"hello",
                content_type="text/plain",
                file_name="a.txt",
                user_id="owner-1",
            )
        assert exc.value.status_code == 415

    def test_content_type_with_charset_suffix_still_accepted(self):
        """Browser hängen manchmal ``; charset=…`` an — wir strippen."""
        tpl = _tpl()
        svc = _service_with_stubs(tpl)
        svc.repo.get_by_template_id.return_value = None
        svc.repo.create.return_value = TemplateIcon(
            id=str(uuid4()),
            template_id=tpl.id,
            content=b"x",
            content_type="image/png",
            file_name="a.png",
            size_bytes=1,
        )
        icon = svc.upload_icon(
            tpl.id,
            content=b"x",
            content_type="image/png; charset=binary",
            file_name="a.png",
            user_id="owner-1",
        )
        assert icon.content_type == "image/png"


# ---------------------------------------------------------------------------
# Upload — size validation
# ---------------------------------------------------------------------------
class TestUploadSize:
    def test_empty_upload_rejected_400(self):
        tpl = _tpl()
        svc = _service_with_stubs(tpl)
        with pytest.raises(BadRequestException):
            svc.upload_icon(
                tpl.id,
                content=b"",
                content_type="image/png",
                file_name="a.png",
                user_id="owner-1",
            )

    def test_oversize_upload_rejected_413(self, monkeypatch):
        tpl = _tpl()
        svc = _service_with_stubs(tpl)

        # Kleiner Grenzwert, damit wir keine 5 MB im Test allokieren müssen.
        from src.core import config as config_module

        fake_settings = config_module.get_settings()
        # ``Settings`` ist eine Pydantic-Instanz; wir mutieren die Cache-Kopie.
        # Der ``get_settings``-Cache liefert dieselbe Instanz, damit reicht das.
        original = fake_settings.max_icon_size_bytes
        fake_settings.max_icon_size_bytes = 10
        try:
            with pytest.raises(HTTPException) as exc:
                svc.upload_icon(
                    tpl.id,
                    content=b"x" * 20,
                    content_type="image/png",
                    file_name="a.png",
                    user_id="owner-1",
                )
            assert exc.value.status_code == 413
        finally:
            fake_settings.max_icon_size_bytes = original


# ---------------------------------------------------------------------------
# Upload — owner/admin gate
# ---------------------------------------------------------------------------
class TestUploadAuthGate:
    def test_non_owner_non_admin_forbidden(self):
        tpl = _tpl(owner_id="owner-1")
        svc = _service_with_stubs(tpl)
        with pytest.raises(ForbiddenException):
            svc.upload_icon(
                tpl.id,
                content=b"x",
                content_type="image/png",
                file_name="a.png",
                user_id="stranger",
                is_admin=False,
            )

    def test_admin_allowed_even_if_not_owner(self):
        tpl = _tpl(owner_id="owner-1")
        svc = _service_with_stubs(tpl)
        svc.repo.get_by_template_id.return_value = None
        svc.repo.create.return_value = TemplateIcon(
            id=str(uuid4()),
            template_id=tpl.id,
            content=b"x",
            content_type="image/png",
            file_name="a.png",
            size_bytes=1,
        )
        icon = svc.upload_icon(
            tpl.id,
            content=b"x",
            content_type="image/png",
            file_name="a.png",
            user_id="admin-99",
            is_admin=True,
        )
        assert icon is not None


# ---------------------------------------------------------------------------
# Upload — create-vs-replace behaviour
# ---------------------------------------------------------------------------
class TestUploadCreateOrReplace:
    def test_first_upload_creates_new_row(self):
        tpl = _tpl()
        svc = _service_with_stubs(tpl)
        svc.repo.get_by_template_id.return_value = None
        created = TemplateIcon(
            id=str(uuid4()),
            template_id=tpl.id,
            content=b"x",
            content_type="image/png",
            file_name="a.png",
            size_bytes=1,
        )
        svc.repo.create.return_value = created

        icon = svc.upload_icon(
            tpl.id,
            content=b"x",
            content_type="image/png",
            file_name="a.png",
            user_id="owner-1",
        )
        assert icon is created
        svc.repo.create.assert_called_once()

    def test_second_upload_replaces_content_keeps_id(self):
        """Bei bereits vorhandenem Icon wird die Row in-place mutiert,
        damit ``id`` und ``created_at`` stabil bleiben."""
        tpl = _tpl()
        svc = _service_with_stubs(tpl)
        existing = TemplateIcon(
            id="stable-icon-id",
            template_id=tpl.id,
            content=b"old",
            content_type="image/jpeg",
            file_name="old.jpg",
            size_bytes=3,
        )
        svc.repo.get_by_template_id.return_value = existing

        icon = svc.upload_icon(
            tpl.id,
            content=b"NEWDATA",
            content_type="image/png",
            file_name="new.png",
            user_id="owner-1",
        )
        assert icon.id == "stable-icon-id"
        assert icon.content == b"NEWDATA"
        assert icon.content_type == "image/png"
        assert icon.file_name == "new.png"
        assert icon.size_bytes == 7
        # ``create`` darf im Replace-Pfad nicht aufgerufen werden.
        svc.repo.create.assert_not_called()


# ---------------------------------------------------------------------------
# Get / Delete
# ---------------------------------------------------------------------------
class TestGetIcon:
    def test_get_returns_icon_when_present(self):
        tpl = _tpl()
        svc = _service_with_stubs(tpl)
        stored = TemplateIcon(
            id="x",
            template_id=tpl.id,
            content=b"blob",
            content_type="image/png",
            file_name="a.png",
            size_bytes=4,
        )
        svc.repo.get_by_template_id.return_value = stored
        icon = svc.get_icon(tpl.id, user_id="owner-1")
        assert icon is stored

    def test_get_raises_404_when_no_icon(self):
        from src.core.exceptions import NotFoundException

        tpl = _tpl()
        svc = _service_with_stubs(tpl)
        svc.repo.get_by_template_id.return_value = None
        with pytest.raises(NotFoundException):
            svc.get_icon(tpl.id, user_id="owner-1")


class TestDeleteIcon:
    def test_delete_returns_true_when_deleted(self):
        tpl = _tpl()
        svc = _service_with_stubs(tpl)
        svc.repo.delete_by_template_id.return_value = True
        assert svc.delete_icon(tpl.id, user_id="owner-1") is True

    def test_delete_idempotent_returns_false_when_nothing_existed(self):
        tpl = _tpl()
        svc = _service_with_stubs(tpl)
        svc.repo.delete_by_template_id.return_value = False
        assert svc.delete_icon(tpl.id, user_id="owner-1") is False

    def test_delete_non_owner_forbidden(self):
        tpl = _tpl(owner_id="owner-1")
        svc = _service_with_stubs(tpl)
        with pytest.raises(ForbiddenException):
            svc.delete_icon(tpl.id, user_id="stranger", is_admin=False)
