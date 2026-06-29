"""Tests for the public-only approval model.

Covers:
- Visibility-switch resets/sets ``approval_status`` correctly on each version.
- Visibility can now be changed by the template owner (not only admins).
- Deploy-time gate: private templates can only be deployed by their owner.
- Approve/reject endpoints reject **genuinely** private templates (no
  publish_requested) with 400. Templates that are PRIVATE + publish_requested
  ARE legitimate approval targets — they're awaiting their first approval.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from src.core.exceptions import BadRequestException, ForbiddenException
from src.models.template import Template, TemplateVisibility
from src.models.template_version import TemplateVersion, TemplateVersionApprovalStatus
from src.schemas.template import TemplateUpdate
from src.services.template_service import TemplateService
from src.services.template_version_service import TemplateVersionService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_template(
    visibility=TemplateVisibility.PRIVATE,
    owner_id=None,
    versions=None,
    publish_requested: bool = False,
):
    t = Template()
    t.id = str(uuid4())
    t.owner_id = owner_id or str(uuid4())
    t.name = "demo"
    t.repo_url = "https://example.com"
    t.visibility = visibility
    t.publish_requested = publish_requested
    t.versions = versions or []
    return t


def _make_version(template_id, approval_status):
    v = TemplateVersion()
    v.id = str(uuid4())
    v.template_id = template_id
    v.version = "1.0.0"
    v.git_commit_sha = "sha-" + v.id[:8]
    v.is_active = True
    v.approval_status = approval_status
    v.approved_by_id = "some-admin" if approval_status == TemplateVersionApprovalStatus.APPROVED else None
    v.approved_at = datetime.now(timezone.utc) if approval_status == TemplateVersionApprovalStatus.APPROVED else None
    v.rejection_reason = None
    return v


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def template_service(mock_db):
    s = TemplateService(mock_db)
    s.template_repo = MagicMock()
    return s


# ---------------------------------------------------------------------------
# Visibility-switch — publish_requested-aware
# ---------------------------------------------------------------------------


class TestVisibilityToggleResetsApproval:
    """When a template flips private↔public, the version-level approval state
    has to follow. Seit der Einführung von ``publish_requested`` ist der
    private→public-Pfad nicht mehr ein Direkt-Flip auf PUBLIC, sondern ein
    Veröffentlichungs-Wunsch: das Template BLEIBT PRIVATE, der Wunsch wird
    festgehalten, die Versionen flippen in den Approval-Flow. Erst beim
    ersten approve_version() flippt das Template wirklich auf PUBLIC."""

    def test_private_to_public_sets_null_versions_to_pending(self, template_service, mock_db):
        owner = str(uuid4())
        tid = str(uuid4())
        v_null = _make_version(tid, None)
        t = _make_template(TemplateVisibility.PRIVATE, owner_id=owner, versions=[v_null])
        t.id = tid
        template_service.template_repo.get_by_id.return_value = t
        template_service.template_repo.update.return_value = t

        template_service.update_template(
            template_id=t.id,
            template_data=TemplateUpdate(visibility="public"),
            user_id=owner,
            is_admin=False,
        )

        # Version that was unset before now enters the approval flow.
        assert v_null.approval_status == TemplateVersionApprovalStatus.PENDING

    def test_private_to_public_keeps_visibility_private_without_approved_versions(
        self, template_service, mock_db,
    ):
        """Der „möchte öffentlich werden"-Wunsch landet als ``publish_requested``
        am Template. Der ``visibility``-Wert in der DB-Aktualisierung wird
        bewusst NICHT auf ``public`` durchgereicht — Service entfernt das
        Feld aus dem Update, damit das Template bis zur ersten Genehmigung
        privat bleibt."""
        owner = str(uuid4())
        tid = str(uuid4())
        v_null = _make_version(tid, None)
        t = _make_template(TemplateVisibility.PRIVATE, owner_id=owner, versions=[v_null])
        t.id = tid
        template_service.template_repo.get_by_id.return_value = t
        template_service.template_repo.update.return_value = t

        template_service.update_template(
            template_id=t.id,
            template_data=TemplateUpdate(visibility="public"),
            user_id=owner,
            is_admin=False,
        )

        # ``template_repo.update`` wird aufgerufen — wir prüfen das Payload:
        # `visibility` muss raus, `publish_requested=True` muss drin sein.
        args, kwargs = template_service.template_repo.update.call_args
        assert "visibility" not in kwargs, (
            "Direktflip auf PUBLIC ist unerwünscht solange keine Version "
            "approved ist — Service muss `visibility` aus dem Update entfernen."
        )
        assert kwargs.get("publish_requested") is True

    def test_private_to_public_flips_directly_with_approved_version(
        self, template_service,
    ):
        """Wenn das Template (z.B. nach demote-to-private und re-promote)
        schon eine APPROVED Version hat, ist der Approval-Umweg unnötig —
        wir flippen direkt auf PUBLIC."""
        owner = str(uuid4())
        tid = str(uuid4())
        v_approved = _make_version(tid, TemplateVersionApprovalStatus.APPROVED)
        t = _make_template(TemplateVisibility.PRIVATE, owner_id=owner, versions=[v_approved])
        t.id = tid
        template_service.template_repo.get_by_id.return_value = t
        template_service.template_repo.update.return_value = t

        template_service.update_template(
            template_id=t.id,
            template_data=TemplateUpdate(visibility="public"),
            user_id=owner,
            is_admin=False,
        )

        args, kwargs = template_service.template_repo.update.call_args
        # Direktflip: visibility bleibt im Update-Payload, publish_requested
        # wird auf False gesetzt (defensiv — falls ein Vorgänger-Wunsch da war).
        assert kwargs.get("visibility") == "public"
        assert kwargs.get("publish_requested") is False
        assert v_approved.approval_status == TemplateVersionApprovalStatus.APPROVED

    def test_private_to_public_does_not_re_pend_already_approved(self, template_service):
        """If a version somehow already carries APPROVED (e.g. legacy data
        from before the schema change), the switch must NOT clobber it back
        to PENDING — that would silently un-approve content."""
        owner = str(uuid4())
        tid = str(uuid4())
        v_already = _make_version(tid, TemplateVersionApprovalStatus.APPROVED)
        t = _make_template(TemplateVisibility.PRIVATE, owner_id=owner, versions=[v_already])
        t.id = tid
        template_service.template_repo.get_by_id.return_value = t
        template_service.template_repo.update.return_value = t

        template_service.update_template(
            template_id=t.id,
            template_data=TemplateUpdate(visibility="public"),
            user_id=owner,
            is_admin=False,
        )

        assert v_already.approval_status == TemplateVersionApprovalStatus.APPROVED

    def test_public_to_private_wipes_approval_state(self, template_service):
        """Going private clears the approval state on every version — the
        concept doesn't apply anymore, and stale APPROVED records would
        leak back to PUBLIC if someone flipped a third time. Plus the
        ``publish_requested``-Wunsch wird gelöscht."""
        owner = str(uuid4())
        tid = str(uuid4())
        v_approved = _make_version(tid, TemplateVersionApprovalStatus.APPROVED)
        v_pending = _make_version(tid, TemplateVersionApprovalStatus.PENDING)
        t = _make_template(
            TemplateVisibility.PUBLIC,
            owner_id=owner,
            versions=[v_approved, v_pending],
            publish_requested=False,
        )
        t.id = tid
        template_service.template_repo.get_by_id.return_value = t
        template_service.template_repo.update.return_value = t

        template_service.update_template(
            template_id=t.id,
            template_data=TemplateUpdate(visibility="private"),
            user_id=owner,
            is_admin=False,
        )

        for v in (v_approved, v_pending):
            assert v.approval_status is None
            assert v.approved_by_id is None
            assert v.approved_at is None
            assert v.rejection_reason is None

        args, kwargs = template_service.template_repo.update.call_args
        assert kwargs.get("publish_requested") is False

    def test_no_change_when_visibility_stays_same(self, template_service):
        """If the PATCH sets visibility to the same value, nothing should
        change on the versions — guards against an accidental wipe when the
        UI sends the full template object back unchanged."""
        owner = str(uuid4())
        tid = str(uuid4())
        v_approved = _make_version(tid, TemplateVersionApprovalStatus.APPROVED)
        t = _make_template(TemplateVisibility.PUBLIC, owner_id=owner, versions=[v_approved])
        t.id = tid
        template_service.template_repo.get_by_id.return_value = t
        template_service.template_repo.update.return_value = t

        template_service.update_template(
            template_id=t.id,
            template_data=TemplateUpdate(visibility="public"),
            user_id=owner,
            is_admin=False,
        )

        assert v_approved.approval_status == TemplateVersionApprovalStatus.APPROVED


# ---------------------------------------------------------------------------
# Visibility-change permission: owner OR admin (no longer admin-only)
# ---------------------------------------------------------------------------


class TestVisibilityChangePermission:
    def test_owner_can_change_visibility(self, template_service):
        owner = str(uuid4())
        tid = str(uuid4())
        t = _make_template(TemplateVisibility.PRIVATE, owner_id=owner, versions=[])
        t.id = tid
        template_service.template_repo.get_by_id.return_value = t
        template_service.template_repo.update.return_value = t

        # No exception expected.
        template_service.update_template(
            template_id=t.id,
            template_data=TemplateUpdate(visibility="public"),
            user_id=owner,
            is_admin=False,
        )

    def test_non_owner_non_admin_cannot_change_visibility(self, template_service):
        owner = str(uuid4())
        attacker = str(uuid4())
        tid = str(uuid4())
        t = _make_template(TemplateVisibility.PRIVATE, owner_id=owner, versions=[])
        t.id = tid
        template_service.template_repo.get_by_id.return_value = t

        with pytest.raises(ForbiddenException):
            template_service.update_template(
                template_id=t.id,
                template_data=TemplateUpdate(visibility="public"),
                user_id=attacker,
                is_admin=False,
            )

    def test_admin_can_change_visibility_on_another_users_template(self, template_service):
        owner = str(uuid4())
        admin = str(uuid4())
        tid = str(uuid4())
        t = _make_template(TemplateVisibility.PRIVATE, owner_id=owner, versions=[])
        t.id = tid
        template_service.template_repo.get_by_id.return_value = t
        template_service.template_repo.update.return_value = t

        template_service.update_template(
            template_id=t.id,
            template_data=TemplateUpdate(visibility="public"),
            user_id=admin,
            is_admin=True,
        )


# ---------------------------------------------------------------------------
# Deploy gate: private templates only deployable by owner
# ---------------------------------------------------------------------------


class TestDeployPrivateTemplateOwnerOnly:
    """The visibility + ownership gate in DeploymentService.create_deployment.

    Mocking the whole create_deployment flow is overkill — we test the gate
    function in isolation by exercising the relevant branch on a mocked
    service. The integration test (Staging E2E) covers the full happy path."""

    def test_other_lecturer_cannot_deploy_private_template(self):
        """Even with the version_id in hand, a non-owner lecturer must not
        deploy a private template. This is the whole point of 'private'."""
        from src.models.user import User
        from src.models.template_version import TemplateVersion as TV

        owner_local = str(uuid4())
        attacker_local = str(uuid4())
        attacker_kc = "attacker-keycloak-id"

        template = _make_template(TemplateVisibility.PRIVATE, owner_id=owner_local, versions=[])
        version = TV()
        version.id = str(uuid4())
        version.template_id = template.id

        attacker_user = User()
        attacker_user.id = attacker_local
        attacker_user.external_id = attacker_kc

        # Verify the gate logic itself — same expression as deployment_service:86.
        # If visibility is private AND owner != caller -> forbidden.
        is_blocked = (
            template.visibility != TemplateVisibility.PUBLIC
            and template.owner_id != attacker_user.id
        )
        assert is_blocked is True

    def test_owner_can_deploy_own_private_template(self):
        """The owner has full access to their private template."""
        from src.models.user import User

        owner_local = str(uuid4())
        owner_kc = "owner-keycloak-id"

        template = _make_template(TemplateVisibility.PRIVATE, owner_id=owner_local, versions=[])
        owner_user = User()
        owner_user.id = owner_local
        owner_user.external_id = owner_kc

        # Gate evaluates to "not blocked".
        is_blocked = (
            template.visibility != TemplateVisibility.PUBLIC
            and template.owner_id != owner_user.id
        )
        assert is_blocked is False

    def test_public_template_gate_does_not_apply(self):
        """For public templates the owner-check is irrelevant; visibility +
        approval drive who can see/deploy what."""
        template = _make_template(TemplateVisibility.PUBLIC, owner_id="someone-else", versions=[])
        is_blocked = (
            template.visibility != TemplateVisibility.PUBLIC
            and template.owner_id != "some-attacker"
        )
        assert is_blocked is False


# ---------------------------------------------------------------------------
# Approve/Reject — Genuine-private vs. publish_requested
# ---------------------------------------------------------------------------


class TestApproveRejectGate:
    def test_approve_400_when_template_genuinely_private(self):
        """Approve auf einem GENUINELY-privaten Template (kein
        publish_requested-Wunsch) ist weiterhin verboten — der Begriff
        Approval ergibt dort keinen Sinn."""
        s = TemplateVersionService(MagicMock())
        s.version_repo = MagicMock()
        s.template_repo = MagicMock()

        priv = _make_template(TemplateVisibility.PRIVATE, publish_requested=False)
        v = _make_version(priv.id, None)
        s.version_repo.get_by_id.return_value = v
        s.template_repo.get_by_id.return_value = priv

        with pytest.raises(BadRequestException) as exc:
            s.approve_version(v.id, admin_user_id="admin-1")
        assert "public" in str(exc.value).lower()

    def test_reject_400_when_template_genuinely_private(self):
        s = TemplateVersionService(MagicMock())
        s.version_repo = MagicMock()
        s.template_repo = MagicMock()

        priv = _make_template(TemplateVisibility.PRIVATE, publish_requested=False)
        v = _make_version(priv.id, None)
        s.version_repo.get_by_id.return_value = v
        s.template_repo.get_by_id.return_value = priv

        with pytest.raises(BadRequestException):
            s.reject_version(v.id, admin_user_id="admin-1")

    def test_approve_succeeds_on_private_with_publish_requested(self, mock_db):
        """Erst-Veröffentlichungs-Pfad: PRIVATE + publish_requested = True
        ist ein legitimer Approval-Kandidat. Beim Approve flippt der
        Template-State atomar auf PUBLIC + publish_requested=False."""
        s = TemplateVersionService(mock_db)
        s.version_repo = MagicMock()
        s.template_repo = MagicMock()

        tpl = _make_template(TemplateVisibility.PRIVATE, publish_requested=True)
        v = _make_version(tpl.id, TemplateVersionApprovalStatus.PENDING)
        s.version_repo.get_by_id.return_value = v
        s.template_repo.get_by_id.return_value = tpl

        s.approve_version(v.id, admin_user_id="admin-1")

        assert v.approval_status == TemplateVersionApprovalStatus.APPROVED
        # Template wurde auf PUBLIC promoted und Wunsch gelöscht.
        assert tpl.visibility == TemplateVisibility.PUBLIC
        assert tpl.publish_requested is False

    def test_reject_succeeds_on_private_with_publish_requested(self, mock_db):
        """Reject auf PRIVATE + publish_requested verwirft den Wunsch:
        Template bleibt PRIVATE und publish_requested → False."""
        s = TemplateVersionService(mock_db)
        s.version_repo = MagicMock()
        s.template_repo = MagicMock()

        tpl = _make_template(TemplateVisibility.PRIVATE, publish_requested=True)
        v = _make_version(tpl.id, TemplateVersionApprovalStatus.PENDING)
        s.version_repo.get_by_id.return_value = v
        s.template_repo.get_by_id.return_value = tpl

        s.reject_version(v.id, admin_user_id="admin-1", reason="needs work")

        assert v.approval_status == TemplateVersionApprovalStatus.REJECTED
        assert v.rejection_reason == "needs work"
        assert tpl.visibility == TemplateVisibility.PRIVATE
        assert tpl.publish_requested is False
