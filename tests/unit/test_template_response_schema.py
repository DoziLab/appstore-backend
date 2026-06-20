"""Tests for TemplateResponse — owner display fields are surfaced from the
ORM ``owner`` relationship without exposing the User object itself.
"""
from datetime import datetime, timezone
from types import SimpleNamespace

from src.schemas.template import TemplateResponse


def _orm_template(owner=None, **overrides):
    """Build a SimpleNamespace that mimics the Template ORM attributes Pydantic reads."""
    defaults = dict(
        id="tmpl-1",
        name="Test Template",
        description="A test template",
        owner_id="user-1",
        repo_url="https://github.com/example/test",
        icon_url=None,
        visibility="private",
        versions=None,
        owner=owner,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_owner_name_email_username_pulled_from_owner_relationship():
    """When the joined User row has display fields, they appear in the response."""
    owner = SimpleNamespace(
        id="user-1",
        display_name="Prof. Dr. Bernd Berg",
        email="berg@dhbw.de",
        username="bberg",
    )
    response = TemplateResponse.model_validate(_orm_template(owner=owner))

    assert response.owner_name == "Prof. Dr. Bernd Berg"
    assert response.owner_email == "berg@dhbw.de"
    assert response.owner_username == "bberg"


def test_owner_name_is_none_for_legacy_user_without_cached_fields():
    """Pre-migration users have NULL display fields; clients fall back to owner_id."""
    owner = SimpleNamespace(
        id="user-1",
        display_name=None,
        email=None,
        username=None,
    )
    response = TemplateResponse.model_validate(_orm_template(owner=owner))

    assert response.owner_name is None
    assert response.owner_email is None
    assert response.owner_username is None
    assert response.owner_id == "user-1"  # always present


def test_owner_name_is_none_when_owner_relationship_not_loaded():
    """Defensive: if upstream forgets to eager-load owner, response stays valid."""
    response = TemplateResponse.model_validate(_orm_template(owner=None))

    assert response.owner_name is None
    assert response.owner_email is None
    assert response.owner_username is None


def test_serialized_payload_excludes_raw_owner_object():
    """The User ORM row must not leak into the JSON response."""
    owner = SimpleNamespace(
        id="user-1",
        display_name="Berg",
        email="berg@dhbw.de",
        username="bberg",
    )
    payload = TemplateResponse.model_validate(_orm_template(owner=owner)).model_dump(mode="json")

    assert "owner" not in payload
    assert payload["owner_name"] == "Berg"
    assert payload["owner_email"] == "berg@dhbw.de"
    assert payload["owner_username"] == "bberg"
    # owner_id stays — it's the stable foreign key the frontend keys off of.
    assert payload["owner_id"] == "user-1"
