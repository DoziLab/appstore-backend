"""Tests für „Aktive Version ändern" — Switch zwischen Versionen, auch
zu älteren. Backend-Service muss das beidseitig erlauben; das Frontend
hat heute keinen Strict-Newer-Filter mehr.

Wir mocken die DB-Schicht; der eigentliche SQL-Update läuft im
TemplateVersionRepository und ist dort separat covered.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from src.core.exceptions import BadRequestException, ForbiddenException
from src.models.template import Template, TemplateVisibility
from src.models.template_version import TemplateVersion, TemplateVersionApprovalStatus
from src.services.template_version_service import TemplateVersionService


def _tpl(owner_id="owner-1"):
    t = Template()
    t.id = str(uuid4())
    t.owner_id = owner_id
    t.name = "demo"
    t.repo_url = "https://example.com"
    t.visibility = TemplateVisibility.PUBLIC
    t.publish_requested = False
    t.versions = []
    return t


def _ver(template_id, version_str, is_active):
    v = TemplateVersion()
    v.id = str(uuid4())
    v.template_id = template_id
    v.version = version_str
    v.git_commit_sha = "sha-" + v.id[:8]
    v.is_active = is_active
    v.approval_status = TemplateVersionApprovalStatus.APPROVED
    v.approved_by_id = "admin-1"
    v.approved_at = datetime.now(timezone.utc)
    v.rejection_reason = None
    return v


class TestActivateVersionSwitch:
    """``activate_version`` darf den active-Flag in beide Richtungen
    switchen — kein Strict-Newer-Filter im Backend."""

    def test_activate_newer_version_works(self):
        s = TemplateVersionService(MagicMock())
        s.version_repo = MagicMock()
        s.template_repo = MagicMock()

        tpl = _tpl()
        v_old = _ver(tpl.id, "2.0.0", is_active=True)
        v_new = _ver(tpl.id, "2.1.0", is_active=False)
        s.version_repo.get_by_id.return_value = v_new
        s.template_repo.get_by_id.return_value = tpl
        s.version_repo.update.return_value = v_new

        result = s.activate_version(v_new.id, user_id=tpl.owner_id, is_admin=False)
        assert result is v_new
        # deactivate_other_versions wurde mit der NEUEN id aufgerufen, damit
        # die OLD-Row passiv mit-deaktiviert wird.
        s.version_repo.deactivate_other_versions.assert_called_once_with(
            tpl.id, v_new.id,
        )

    def test_activate_older_version_works(self):
        """Downgrade-Pfad: ältere Version wieder aktivieren. Service darf
        das genauso wie ein Upgrade durchwinken."""
        s = TemplateVersionService(MagicMock())
        s.version_repo = MagicMock()
        s.template_repo = MagicMock()

        tpl = _tpl()
        v_old = _ver(tpl.id, "2.0.0", is_active=False)
        v_new = _ver(tpl.id, "2.1.0", is_active=True)
        s.version_repo.get_by_id.return_value = v_old
        s.template_repo.get_by_id.return_value = tpl
        s.version_repo.update.return_value = v_old

        result = s.activate_version(v_old.id, user_id=tpl.owner_id, is_admin=False)
        assert result is v_old
        s.version_repo.deactivate_other_versions.assert_called_once_with(
            tpl.id, v_old.id,
        )

    def test_activate_requires_owner_or_admin(self):
        s = TemplateVersionService(MagicMock())
        s.version_repo = MagicMock()
        s.template_repo = MagicMock()

        tpl = _tpl(owner_id="owner-1")
        v = _ver(tpl.id, "1.0.0", is_active=False)
        s.version_repo.get_by_id.return_value = v
        s.template_repo.get_by_id.return_value = tpl

        with pytest.raises(ForbiddenException):
            s.activate_version(v.id, user_id="someone-else", is_admin=False)


class TestActivateVersionWithVersionString:
    """Wenn ``update_version`` einen neuen Versions-String übergibt, läuft
    der Validator. Hier sicherstellen, dass die Activate-Logik selbst
    unabhängig davon funktioniert (versions-Spalte unverändert)."""

    def test_update_with_only_is_active_skips_version_validation(self):
        from src.schemas.template_version import TemplateVersionUpdate

        s = TemplateVersionService(MagicMock())
        s.version_repo = MagicMock()
        s.template_repo = MagicMock()

        tpl = _tpl()
        v = _ver(tpl.id, "2.0.0", is_active=False)
        s.version_repo.get_by_id.return_value = v
        s.template_repo.get_by_id.return_value = tpl
        s.version_repo.update.return_value = v

        # update_version(is_active=True) ohne version-Feld: Validator darf
        # nicht angeschmissen werden (würde sonst die existierende Version
        # gegen sich selbst vergleichen).
        s.update_version(
            v.id,
            TemplateVersionUpdate(is_active=True),
            user_id=tpl.owner_id,
            is_admin=False,
        )
        # deactivate_other_versions wurde aufgerufen.
        s.version_repo.deactivate_other_versions.assert_called_once_with(tpl.id, v.id)
