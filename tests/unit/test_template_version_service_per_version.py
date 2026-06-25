"""Unit tests for new TemplateVersionService methods introduced with the
per-version approval / GitHub import refactor:

- _initial_approval        - auto-approve only for admin + public template
- _can_access_version      - per-version visibility for non-owners
- approve_version          - sets status / approver / timestamp
- reject_version           - sets status / approver / timestamp
- create_version_with_files - atomic version+files, optional base_version_id overlay
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from src.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
from src.models.template import Template, TemplateVisibility
from src.models.template_version import TemplateVersion, TemplateVersionApprovalStatus
from src.models.template_version_file import TemplateVersionFile, FileType
from src.schemas.template_version import (
    TemplateVersionFileInline,
    TemplateVersionWithFilesCreate,
)
from src.services.template_version_service import TemplateVersionService


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def service(mock_db):
    s = TemplateVersionService(mock_db)
    s.template_repo = MagicMock()
    s.version_repo = MagicMock()
    s.file_repo = MagicMock()
    return s


def _make_template(visibility: TemplateVisibility, owner_id: str | None = None) -> Template:
    t = Template()
    t.id = str(uuid4())
    t.owner_id = owner_id or str(uuid4())
    t.name = "demo"
    t.repo_url = "https://example.com"
    t.visibility = visibility
    return t


def _make_version(
    template_id: str,
    approval_status: TemplateVersionApprovalStatus = TemplateVersionApprovalStatus.PENDING,
) -> TemplateVersion:
    v = TemplateVersion()
    v.id = str(uuid4())
    v.template_id = template_id
    v.version = "1.0.0"
    v.git_commit_sha = "sha-" + v.id[:8]
    v.is_active = True
    v.approval_status = approval_status
    v.approved_by_id = None
    v.approved_at = None
    return v


# ---------------------------------------------------------------------------
# _initial_approval - the auto-approve rule
# ---------------------------------------------------------------------------


class TestInitialApproval:
    def test_admin_on_public_template_auto_approves(self):
        t = _make_template(TemplateVisibility.PUBLIC)
        assert TemplateVersionService._initial_approval(t, ["admin"]) == TemplateVersionApprovalStatus.APPROVED

    def test_admin_on_private_template_returns_none(self):
        """Private templates skip the approval flow entirely — approval
        concept doesn't apply when the template is owner-only."""
        t = _make_template(TemplateVisibility.PRIVATE)
        assert TemplateVersionService._initial_approval(t, ["admin"]) is None

    def test_lecturer_on_public_template_stays_pending(self):
        t = _make_template(TemplateVisibility.PUBLIC)
        assert TemplateVersionService._initial_approval(t, ["lecturer"]) == TemplateVersionApprovalStatus.PENDING

    def test_lecturer_on_private_template_returns_none(self):
        t = _make_template(TemplateVisibility.PRIVATE)
        assert TemplateVersionService._initial_approval(t, ["lecturer"]) is None

    def test_empty_roles_stays_pending(self):
        t = _make_template(TemplateVisibility.PUBLIC)
        assert TemplateVersionService._initial_approval(t, []) == TemplateVersionApprovalStatus.PENDING


# ---------------------------------------------------------------------------
# _can_access_version - per-version visibility
# ---------------------------------------------------------------------------


class TestCanAccessVersion:
    def test_admin_sees_any_version(self, service):
        t = _make_template(TemplateVisibility.PRIVATE)
        v = _make_version(t.id, TemplateVersionApprovalStatus.PENDING)
        assert service._can_access_version(v, t, user_id="anyone", is_admin=True)

    def test_owner_sees_pending_version_on_private_template(self, service):
        owner_id = str(uuid4())
        t = _make_template(TemplateVisibility.PRIVATE, owner_id=owner_id)
        v = _make_version(t.id, TemplateVersionApprovalStatus.PENDING)
        assert service._can_access_version(v, t, user_id=owner_id, is_admin=False)

    def test_owner_sees_rejected_version(self, service):
        owner_id = str(uuid4())
        t = _make_template(TemplateVisibility.PUBLIC, owner_id=owner_id)
        v = _make_version(t.id, TemplateVersionApprovalStatus.REJECTED)
        assert service._can_access_version(v, t, user_id=owner_id, is_admin=False)

    def test_other_user_sees_approved_version_on_public_template(self, service):
        t = _make_template(TemplateVisibility.PUBLIC)
        v = _make_version(t.id, TemplateVersionApprovalStatus.APPROVED)
        assert service._can_access_version(v, t, user_id="other-user", is_admin=False)

    def test_other_user_blocked_from_pending_version_on_public_template(self, service):
        t = _make_template(TemplateVisibility.PUBLIC)
        v = _make_version(t.id, TemplateVersionApprovalStatus.PENDING)
        assert not service._can_access_version(v, t, user_id="other-user", is_admin=False)

    def test_other_user_blocked_from_any_version_on_private_template(self, service):
        t = _make_template(TemplateVisibility.PRIVATE)
        v = _make_version(t.id, TemplateVersionApprovalStatus.APPROVED)
        assert not service._can_access_version(v, t, user_id="other-user", is_admin=False)

    def test_anonymous_user_blocked(self, service):
        t = _make_template(TemplateVisibility.PUBLIC)
        v = _make_version(t.id, TemplateVersionApprovalStatus.APPROVED)
        assert not service._can_access_version(v, t, user_id=None, is_admin=False)


# ---------------------------------------------------------------------------
# approve_version / reject_version
# ---------------------------------------------------------------------------


class TestApproveRejectVersion:
    def test_approve_sets_status_and_audit_fields(self, service, mock_db):
        # Approve is allowed only on public templates — wire the template_repo
        # mock so the gate in approve_version() lets us through.
        public_template = _make_template(TemplateVisibility.PUBLIC)
        service.template_repo.get_by_id.return_value = public_template
        v = _make_version(public_template.id, TemplateVersionApprovalStatus.PENDING)
        service.version_repo.get_by_id.return_value = v
        admin_id = str(uuid4())

        before = datetime.now(timezone.utc)
        result = service.approve_version(v.id, admin_user_id=admin_id)
        after = datetime.now(timezone.utc)

        assert result.approval_status == TemplateVersionApprovalStatus.APPROVED
        assert result.approved_by_id == admin_id
        assert before <= result.approved_at <= after
        mock_db.commit.assert_called_once()

    def test_approve_raises_when_version_missing(self, service):
        service.version_repo.get_by_id.return_value = None
        with pytest.raises(NotFoundException):
            service.approve_version("missing-id", admin_user_id="admin-1")

    def test_approve_400_when_template_private(self, service):
        """Approval flow doesn't apply to private templates — must reject."""
        priv = _make_template(TemplateVisibility.PRIVATE)
        v = _make_version(priv.id, None)
        service.version_repo.get_by_id.return_value = v
        service.template_repo.get_by_id.return_value = priv

        with pytest.raises(BadRequestException) as exc:
            service.approve_version(v.id, admin_user_id="admin-1")
        assert "public" in str(exc.value).lower()

    def test_reject_sets_status_and_audit_fields(self, service, mock_db):
        public_template = _make_template(TemplateVisibility.PUBLIC)
        service.template_repo.get_by_id.return_value = public_template
        v = _make_version(public_template.id, TemplateVersionApprovalStatus.PENDING)
        service.version_repo.get_by_id.return_value = v
        admin_id = str(uuid4())

        result = service.reject_version(v.id, admin_user_id=admin_id)

        assert result.approval_status == TemplateVersionApprovalStatus.REJECTED
        assert result.approved_by_id == admin_id
        assert result.approved_at is not None
        mock_db.commit.assert_called_once()

    def test_reject_raises_when_version_missing(self, service):
        service.version_repo.get_by_id.return_value = None
        with pytest.raises(NotFoundException):
            service.reject_version("missing-id", admin_user_id="admin-1")

    def test_reject_400_when_template_private(self, service):
        priv = _make_template(TemplateVisibility.PRIVATE)
        v = _make_version(priv.id, None)
        service.version_repo.get_by_id.return_value = v
        service.template_repo.get_by_id.return_value = priv

        with pytest.raises(BadRequestException):
            service.reject_version(v.id, admin_user_id="admin-1")


# ---------------------------------------------------------------------------
# create_version_with_files - atomic create + base_version_id overlay
# ---------------------------------------------------------------------------


class TestCreateVersionWithFiles:
    def _payload(self, template_id: str, files=None, base_version_id=None, version="1.0.0", sha="sha-xyz"):
        return TemplateVersionWithFilesCreate(
            template_id=template_id,
            version=version,
            git_commit_sha=sha,
            is_active=True,
            base_version_id=base_version_id,
            files=files or [],
        )

    def _file(self, name: str, path: str, content: str = "x", file_type: str = "OTHER",
              is_primary: bool = False, order: int = 0):
        return TemplateVersionFileInline(
            file_name=name, file_path=path, content=content,
            file_type=file_type, is_primary=is_primary, order=order,
        )

    def test_forbidden_for_non_owner_non_admin(self, service):
        t = _make_template(TemplateVisibility.PRIVATE)
        service.template_repo.get_by_id.return_value = t
        service.version_repo.get_by_commit_sha.return_value = None

        payload = self._payload(t.id, files=[self._file("a.yaml", "a.yaml")])
        with pytest.raises(ForbiddenException):
            service.create_version_with_files(payload, user_id="someone-else", user_roles=["lecturer"])

    def test_rejects_duplicate_commit_sha(self, service):
        t = _make_template(TemplateVisibility.PRIVATE)
        service.template_repo.get_by_id.return_value = t
        existing = _make_version(t.id)
        service.version_repo.get_by_commit_sha.return_value = existing

        payload = self._payload(t.id, files=[self._file("a.yaml", "a.yaml")])
        with pytest.raises(BadRequestException, match="already exists"):
            service.create_version_with_files(payload, user_id=t.owner_id, user_roles=["lecturer"])

    def test_rejects_zero_files_without_base(self, service):
        t = _make_template(TemplateVisibility.PRIVATE)
        service.template_repo.get_by_id.return_value = t
        service.version_repo.get_by_commit_sha.return_value = None

        payload = self._payload(t.id, files=[])
        with pytest.raises(BadRequestException, match="zero files"):
            service.create_version_with_files(payload, user_id=t.owner_id, user_roles=["lecturer"])

    def test_rejects_multiple_primary_files(self, service):
        t = _make_template(TemplateVisibility.PRIVATE)
        service.template_repo.get_by_id.return_value = t
        service.version_repo.get_by_commit_sha.return_value = None

        payload = self._payload(t.id, files=[
            self._file("app.yaml", "app.yaml", file_type="APP_MANIFEST", is_primary=True),
            self._file("b.yaml", "b.yaml", is_primary=True),
        ])
        with pytest.raises(BadRequestException, match="is_primary"):
            service.create_version_with_files(payload, user_id=t.owner_id, user_roles=["lecturer"])

    def test_persists_inline_files_and_starts_pending_for_lecturer(self, service, mock_db):
        t = _make_template(TemplateVisibility.PUBLIC)
        service.template_repo.get_by_id.return_value = t
        service.version_repo.get_by_commit_sha.return_value = None

        payload = self._payload(t.id, files=[
            self._file("app.yaml", "app.yaml", file_type="APP_MANIFEST", order=0),
            self._file("heat.yaml", "heat/heat.yaml", file_type="HEAT_TEMPLATE", is_primary=True, order=1),
        ])
        version = service.create_version_with_files(
            payload, user_id=t.owner_id, user_roles=["lecturer"]
        )

        assert version.approval_status == TemplateVersionApprovalStatus.PENDING
        assert version.template_id == t.id

        added_files = [
            c.args[0] for c in mock_db.add.call_args_list
            if isinstance(c.args[0], TemplateVersionFile)
        ]
        paths = sorted(f.file_path for f in added_files)
        assert paths == ["app.yaml", "heat/heat.yaml"]

    def test_admin_on_public_template_auto_approves(self, service):
        t = _make_template(TemplateVisibility.PUBLIC)
        service.template_repo.get_by_id.return_value = t
        service.version_repo.get_by_commit_sha.return_value = None
        admin_id = str(uuid4())

        payload = self._payload(t.id, files=[self._file("app.yaml", "app.yaml")])
        version = service.create_version_with_files(
            payload, user_id=admin_id, user_roles=["admin"]
        )

        assert version.approval_status == TemplateVersionApprovalStatus.APPROVED
        assert version.approved_by_id == admin_id
        assert version.approved_at is not None

    def test_base_version_files_are_overlaid_by_inline_files(self, service, mock_db):
        """`base_version_id` copies files first, then inline files overwrite by file_path."""
        t = _make_template(TemplateVisibility.PRIVATE)
        service.template_repo.get_by_id.return_value = t
        service.version_repo.get_by_commit_sha.return_value = None

        base_version = _make_version(t.id)
        service.version_repo.get_by_id.return_value = base_version

        # The base version has two files
        base_file_kept = MagicMock(spec=TemplateVersionFile)
        base_file_kept.file_name = "keep.yaml"
        base_file_kept.file_path = "keep.yaml"
        base_file_kept.file_type = FileType.OTHER
        base_file_kept.content = "ORIGINAL_KEEP"
        base_file_kept.description = None
        base_file_kept.is_primary = False
        base_file_kept.order = 0

        base_file_overwritten = MagicMock(spec=TemplateVersionFile)
        base_file_overwritten.file_name = "app.yaml"
        base_file_overwritten.file_path = "app.yaml"
        base_file_overwritten.file_type = FileType.APP_MANIFEST
        base_file_overwritten.content = "ORIGINAL_APP"
        base_file_overwritten.description = None
        base_file_overwritten.is_primary = False
        base_file_overwritten.order = 1

        service.file_repo.get_by_version_id.return_value = [base_file_kept, base_file_overwritten]

        # Inline files: overwrite app.yaml only
        payload = self._payload(t.id, base_version_id=base_version.id, files=[
            self._file("app.yaml", "app.yaml", content="EDITED_APP", file_type="APP_MANIFEST", order=1),
        ])
        service.create_version_with_files(payload, user_id=t.owner_id, user_roles=["lecturer"])

        added_files = [
            c.args[0] for c in mock_db.add.call_args_list
            if isinstance(c.args[0], TemplateVersionFile)
        ]
        by_path = {f.file_path: f for f in added_files}
        assert set(by_path.keys()) == {"keep.yaml", "app.yaml"}
        assert by_path["keep.yaml"].content == "ORIGINAL_KEEP"
        # Inline overlay wins for app.yaml
        assert by_path["app.yaml"].content == "EDITED_APP"

    def test_rejects_base_version_from_other_template(self, service):
        t = _make_template(TemplateVisibility.PRIVATE)
        service.template_repo.get_by_id.return_value = t
        service.version_repo.get_by_commit_sha.return_value = None

        # Base version belongs to a DIFFERENT template
        foreign = _make_version("some-other-template-id")
        service.version_repo.get_by_id.return_value = foreign

        payload = self._payload(t.id, base_version_id=foreign.id, files=[
            self._file("a.yaml", "a.yaml")
        ])
        with pytest.raises(BadRequestException, match="not a version of template"):
            service.create_version_with_files(payload, user_id=t.owner_id, user_roles=["lecturer"])
