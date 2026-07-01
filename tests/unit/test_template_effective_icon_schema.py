"""Tests für die ``effective_icon``-Aggregation auf TemplateResponse.

Frontend soll nur ein Feld rendern müssen: hochgeladenes Bild → Serve-URL,
sonst Fallback auf ``icon_url``, sonst ``None``. Die rohe Icon-Relation
wird bewusst ausgeblendet.
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
        icon_url=None,
        visibility="private",
        versions=None,
        owner=None,
        icon=None,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestEffectiveIcon:
    def test_uploaded_icon_wins_over_icon_url(self):
        """Wenn beide gesetzt sind, wird die Serve-URL des Uploads zurückgegeben."""
        icon = SimpleNamespace(id="icon-42")
        response = TemplateResponse.model_validate(
            _orm_template(icon_url="mdi:server", icon=icon)
        )
        assert response.effective_icon == "/api/v1/templates/tmpl-1/icon"
        assert response.has_uploaded_icon is True

    def test_icon_url_only_returned_when_no_upload(self):
        response = TemplateResponse.model_validate(
            _orm_template(icon_url="mdi:server", icon=None)
        )
        assert response.effective_icon == "mdi:server"
        assert response.has_uploaded_icon is False

    def test_external_url_returned_when_no_upload(self):
        response = TemplateResponse.model_validate(
            _orm_template(icon_url="https://cdn.example.com/logo.png", icon=None)
        )
        assert response.effective_icon == "https://cdn.example.com/logo.png"
        assert response.has_uploaded_icon is False

    def test_none_when_neither_set(self):
        response = TemplateResponse.model_validate(
            _orm_template(icon_url=None, icon=None)
        )
        assert response.effective_icon is None
        assert response.has_uploaded_icon is False


class TestSerializedPayloadShape:
    def test_raw_icon_object_not_leaked_into_json(self):
        """Die ORM-Icon-Relation darf nicht in die Response wandern —
        Clients bekommen nur ``effective_icon`` + ``has_uploaded_icon``."""
        icon = SimpleNamespace(id="icon-42", content_type="image/png")
        payload = TemplateResponse.model_validate(
            _orm_template(icon_url="mdi:server", icon=icon)
        ).model_dump(mode="json")

        assert "icon" not in payload
        assert payload["effective_icon"] == "/api/v1/templates/tmpl-1/icon"
        assert payload["has_uploaded_icon"] is True
        # icon_url bleibt als Rohfeld sichtbar, damit Bearbeitungs-UIs
        # den ursprünglichen Wert weiter im Formular haben.
        assert payload["icon_url"] == "mdi:server"

    def test_json_payload_when_only_icon_url_set(self):
        payload = TemplateResponse.model_validate(
            _orm_template(icon_url="mdi:server", icon=None)
        ).model_dump(mode="json")

        assert payload["effective_icon"] == "mdi:server"
        assert payload["has_uploaded_icon"] is False
        assert payload["icon_url"] == "mdi:server"
