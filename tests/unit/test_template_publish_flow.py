"""Tests für den Erst-Veröffentlichungs-Flow.

Owner klickt beim Anlegen „öffentlich" → Template landet als PRIVATE +
publish_requested=True. Erst beim ersten approve_version() flippt das
Template atomar auf PUBLIC. Bei reject bleibt es PRIVATE und der Wunsch
wird verworfen.

Diese Tests decken nur die Service-Logik ab (Unit-Level, mit MagicMock-DB).
Die End-to-End-Validierung läuft als Frontend-Smoke-Test bzw. im API-Layer.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from src.models.template import Template, TemplateVisibility
from src.models.template_version import TemplateVersion, TemplateVersionApprovalStatus
from src.models.user import UserRole
from src.services.template_version_service import TemplateVersionService


def _tpl(visibility=TemplateVisibility.PRIVATE, publish_requested=False):
    t = Template()
    t.id = str(uuid4())
    t.owner_id = "owner-1"
    t.name = "demo"
    t.repo_url = "https://example.com"
    t.visibility = visibility
    t.publish_requested = publish_requested
    t.versions = []
    return t


def _ver(template_id, approval_status, is_active=False, version_str="1.0.0"):
    v = TemplateVersion()
    v.id = str(uuid4())
    v.template_id = template_id
    v.version = version_str
    v.git_commit_sha = "sha-" + v.id[:8]
    v.is_active = is_active
    v.approval_status = approval_status
    v.approved_by_id = None
    v.approved_at = None
    v.rejection_reason = None
    return v


class TestInitialApproval:
    """``_initial_approval`` bildet (template, caller) → approval_status ab.
    Wir testen die drei relevanten Eingangs-Konstellationen für
    `publish_requested` (neu) + den unveränderten Standard-Flow."""

    def test_genuinely_private_returns_none(self):
        tpl = _tpl(TemplateVisibility.PRIVATE, publish_requested=False)
        assert TemplateVersionService._initial_approval(tpl, [UserRole.LECTURER.value]) is None
        assert TemplateVersionService._initial_approval(tpl, [UserRole.ADMIN.value]) is None

    def test_public_template_lecturer_caller_gets_pending(self):
        tpl = _tpl(TemplateVisibility.PUBLIC, publish_requested=False)
        result = TemplateVersionService._initial_approval(tpl, [UserRole.LECTURER.value])
        assert result == TemplateVersionApprovalStatus.PENDING

    def test_public_template_admin_caller_gets_approved(self):
        tpl = _tpl(TemplateVisibility.PUBLIC, publish_requested=False)
        result = TemplateVersionService._initial_approval(tpl, [UserRole.ADMIN.value])
        assert result == TemplateVersionApprovalStatus.APPROVED

    def test_private_with_publish_requested_lecturer_gets_pending(self):
        """Erst-Veröffentlichungs-Pfad: Template ist noch PRIVATE, aber der
        Wunsch ist gesetzt → Approval-Flow läuft schon, neue Versionen
        starten PENDING."""
        tpl = _tpl(TemplateVisibility.PRIVATE, publish_requested=True)
        result = TemplateVersionService._initial_approval(tpl, [UserRole.LECTURER.value])
        assert result == TemplateVersionApprovalStatus.PENDING

    def test_private_with_publish_requested_admin_gets_approved(self):
        tpl = _tpl(TemplateVisibility.PRIVATE, publish_requested=True)
        result = TemplateVersionService._initial_approval(tpl, [UserRole.ADMIN.value])
        assert result == TemplateVersionApprovalStatus.APPROVED


class TestApproveFlipsToPublic:
    """``approve_version`` flippt PRIVATE+publish_requested atomar zu
    PUBLIC + publish_requested=False — und nur dann."""

    def test_approve_on_publish_requested_promotes_to_public(self):
        s = TemplateVersionService(MagicMock())
        s.version_repo = MagicMock()
        s.template_repo = MagicMock()

        tpl = _tpl(TemplateVisibility.PRIVATE, publish_requested=True)
        v = _ver(tpl.id, TemplateVersionApprovalStatus.PENDING)
        s.version_repo.get_by_id.return_value = v
        s.template_repo.get_by_id.return_value = tpl

        s.approve_version(v.id, admin_user_id="admin-1")

        assert tpl.visibility == TemplateVisibility.PUBLIC
        assert tpl.publish_requested is False
        assert v.approval_status == TemplateVersionApprovalStatus.APPROVED
        assert v.approved_by_id == "admin-1"
        assert v.approved_at is not None

    def test_approve_on_already_public_template_does_not_touch_publish_requested(self):
        """Approves auf bereits-PUBLIC Templates lassen die Spalte unangetastet."""
        s = TemplateVersionService(MagicMock())
        s.version_repo = MagicMock()
        s.template_repo = MagicMock()

        tpl = _tpl(TemplateVisibility.PUBLIC, publish_requested=False)
        v = _ver(tpl.id, TemplateVersionApprovalStatus.PENDING)
        s.version_repo.get_by_id.return_value = v
        s.template_repo.get_by_id.return_value = tpl

        s.approve_version(v.id, admin_user_id="admin-1")

        assert tpl.visibility == TemplateVisibility.PUBLIC
        assert tpl.publish_requested is False
        assert v.approval_status == TemplateVersionApprovalStatus.APPROVED


class TestRejectClearsPublishRequest:
    """``reject_version`` verwirft den Veröffentlichungs-Wunsch, lässt das
    Template aber PRIVATE."""

    def test_reject_on_publish_requested_clears_wish_keeps_private(self):
        s = TemplateVersionService(MagicMock())
        s.version_repo = MagicMock()
        s.template_repo = MagicMock()

        tpl = _tpl(TemplateVisibility.PRIVATE, publish_requested=True)
        v = _ver(tpl.id, TemplateVersionApprovalStatus.PENDING)
        s.version_repo.get_by_id.return_value = v
        s.template_repo.get_by_id.return_value = tpl

        s.reject_version(v.id, admin_user_id="admin-1", reason="format")

        assert tpl.visibility == TemplateVisibility.PRIVATE
        assert tpl.publish_requested is False
        assert v.approval_status == TemplateVersionApprovalStatus.REJECTED
        assert v.rejection_reason == "format"

    def test_reject_on_public_template_does_not_alter_publish_requested(self):
        """Reject auf einem bereits-PUBLIC Template: publish_requested
        bleibt wie es war (typischerweise False), Template-State bleibt."""
        s = TemplateVersionService(MagicMock())
        s.version_repo = MagicMock()
        s.template_repo = MagicMock()

        tpl = _tpl(TemplateVisibility.PUBLIC, publish_requested=False)
        v = _ver(tpl.id, TemplateVersionApprovalStatus.PENDING)
        s.version_repo.get_by_id.return_value = v
        s.template_repo.get_by_id.return_value = tpl

        s.reject_version(v.id, admin_user_id="admin-1")

        assert tpl.visibility == TemplateVisibility.PUBLIC
        assert tpl.publish_requested is False
        assert v.approval_status == TemplateVersionApprovalStatus.REJECTED
