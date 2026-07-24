"""Tests für ``icon_path`` auf TemplateResponse.

Nach dem Umbau kennt das Backend nur noch hochgeladene Icon-Bilder;
``mdi:*``/URL-Strings gibt es nicht mehr. Frontend rendert entweder
``icon_path`` als ``<img src="…">`` (gegen die API-Base-URL aufgelöst)
oder einen Placeholder.
"""
from datetime import datetime, timezone
from types import SimpleNamespace

from src.schemas.template import TemplateResponse


def _orm_template(**overrides):
    """Build a Template-like ORM stub for schema validation."""
    defaults = dict(
        id="tmpl-1",
        name="Test Template",
        description=None,
        owner_id="user-1",
        repo_url="https://github.com/example/test",
        visibility="private",
        versions=None,
        owner=None,
        icon=None,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestIconPath:
    def test_uploaded_icon_returns_serve_path(self):
        icon = SimpleNamespace(id="icon-42")
        response = TemplateResponse.model_validate(_orm_template(icon=icon))
        assert response.icon_path == "/api/v1/templates/tmpl-1/icon"

    def test_no_icon_returns_none(self):
        """Ohne Upload ist ``icon_path`` ``None`` — kein Fallback."""
        response = TemplateResponse.model_validate(_orm_template(icon=None))
        assert response.icon_path is None


class TestSerializedPayloadShape:
    def test_raw_icon_object_not_leaked_into_json(self):
        """Die ORM-Icon-Relation darf nicht in die Response wandern —
        Clients bekommen nur ``icon_path``."""
        icon = SimpleNamespace(id="icon-42", content_type="image/png")
        payload = TemplateResponse.model_validate(
            _orm_template(icon=icon)
        ).model_dump(mode="json")

        assert "icon" not in payload
        assert "icon_url" not in payload  # Altes Feld existiert nicht mehr
        assert "effective_icon" not in payload  # Zwischenname war effective_icon
        assert "has_uploaded_icon" not in payload  # ebenfalls entfernt
        assert payload["icon_path"] == "/api/v1/templates/tmpl-1/icon"

    def test_json_payload_when_no_upload(self):
        payload = TemplateResponse.model_validate(
            _orm_template(icon=None)
        ).model_dump(mode="json")

        assert payload["icon_path"] is None
