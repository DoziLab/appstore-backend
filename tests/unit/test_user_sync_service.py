"""Tests for UserSyncService — token-claim caching of display fields.

The service caches `display_name`, `email`, `username` from the JWT on every
login so the API can render owner names without round-tripping to Keycloak.
Roles continue to be read from the token, never from the DB.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.services.user_sync_service import UserSyncService


def _service_with_existing_user(existing):
    """Build a UserSyncService whose repo returns ``existing`` for any sub."""
    db = MagicMock()
    service = UserSyncService(db)
    service.user_repo = MagicMock()
    service.user_repo.get_by_external_id.return_value = existing
    return service, db


def _service_without_existing_user(created):
    """Build a UserSyncService whose repo creates and returns ``created``."""
    db = MagicMock()
    service = UserSyncService(db)
    service.user_repo = MagicMock()
    service.user_repo.get_by_external_id.return_value = None
    service.user_repo.create.return_value = created
    return service, db


def test_create_persists_display_fields_from_token():
    """First-login path stores name/email/username on the new User row."""
    created = SimpleNamespace(id="local-1", external_id="kc-1")
    service, _db = _service_without_existing_user(created)

    service.sync_user_from_token({
        "sub": "kc-1",
        "name": "Prof. Dr. Bernd Berg",
        "email": "berg@dhbw.de",
        "preferred_username": "bberg",
    })

    service.user_repo.create.assert_called_once_with(
        external_id="kc-1",
        display_name="Prof. Dr. Bernd Berg",
        email="berg@dhbw.de",
        username="bberg",
    )


def test_create_with_missing_claims_stores_none():
    """Tokens without optional claims still create the user (fields stay NULL)."""
    created = SimpleNamespace(id="local-2", external_id="kc-2")
    service, _db = _service_without_existing_user(created)

    service.sync_user_from_token({"sub": "kc-2"})

    service.user_repo.create.assert_called_once_with(
        external_id="kc-2",
        display_name=None,
        email=None,
        username=None,
    )


def test_existing_user_refreshes_changed_display_fields():
    """If Keycloak claims differ from what's stored, the cached values update."""
    existing = SimpleNamespace(
        id="local-3",
        external_id="kc-3",
        display_name="Old Name",
        email="old@dhbw.de",
        username="oldname",
        last_login_at=None,
    )
    service, db = _service_with_existing_user(existing)

    service.sync_user_from_token({
        "sub": "kc-3",
        "name": "New Name",
        "email": "new@dhbw.de",
        "preferred_username": "newname",
    })

    assert existing.display_name == "New Name"
    assert existing.email == "new@dhbw.de"
    assert existing.username == "newname"
    db.commit.assert_called_once()


def test_existing_user_unchanged_when_claims_match():
    """Same claims as before: values stay; commit still happens for last_login_at."""
    existing = SimpleNamespace(
        id="local-4",
        external_id="kc-4",
        display_name="Stable Name",
        email="stable@dhbw.de",
        username="stable",
        last_login_at=None,
    )
    service, db = _service_with_existing_user(existing)

    service.sync_user_from_token({
        "sub": "kc-4",
        "name": "Stable Name",
        "email": "stable@dhbw.de",
        "preferred_username": "stable",
    })

    # No surprise overwrites with falsy values.
    assert existing.display_name == "Stable Name"
    assert existing.email == "stable@dhbw.de"
    assert existing.username == "stable"
    db.commit.assert_called_once()


def test_existing_user_clears_field_when_claim_disappears():
    """If a claim is removed in Keycloak, the cached copy is cleared too."""
    existing = SimpleNamespace(
        id="local-5",
        external_id="kc-5",
        display_name="Some Name",
        email="some@dhbw.de",
        username="some",
        last_login_at=None,
    )
    service, _db = _service_with_existing_user(existing)

    service.sync_user_from_token({"sub": "kc-5"})

    assert existing.display_name is None
    assert existing.email is None
    assert existing.username is None
