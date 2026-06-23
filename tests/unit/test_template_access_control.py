"""Unit tests for template access control."""
import pytest
from unittest.mock import Mock, MagicMock
from uuid import uuid4

from src.services.template_service import TemplateService
from src.services.template_version_service import TemplateVersionService
from src.services.template_version_file_service import TemplateVersionFileService
from src.models.template import Template, TemplateVisibility
from src.models.template_version import TemplateVersion
from src.models.template_version_file import TemplateVersionFile
from src.core.exceptions import ForbiddenException, NotFoundException


@pytest.fixture
def mock_db():
    """Create a mock database session."""
    return MagicMock()


@pytest.fixture
def template_service(mock_db):
    """Create TemplateService instance with mocked dependencies."""
    return TemplateService(mock_db)


@pytest.fixture
def template_version_service(mock_db):
    """Create TemplateVersionService instance with mocked dependencies."""
    return TemplateVersionService(mock_db)


@pytest.fixture
def template_version_file_service(mock_db):
    """Create TemplateVersionFileService instance with mocked dependencies."""
    return TemplateVersionFileService(mock_db)


@pytest.fixture
def owner_user_id():
    """Owner user ID."""
    return str(uuid4())


@pytest.fixture
def other_user_id():
    """Other user ID."""
    return str(uuid4())


@pytest.fixture
def private_template(owner_user_id):
    """Create a private template."""
    template = Mock(spec=Template)
    template.id = str(uuid4())
    template.owner_id = owner_user_id
    template.visibility = TemplateVisibility.PRIVATE
    return template


@pytest.fixture
def public_approved_template(owner_user_id):
    """Create a public template (approval lives on TemplateVersion now)."""
    template = Mock(spec=Template)
    template.id = str(uuid4())
    template.owner_id = owner_user_id
    template.visibility = TemplateVisibility.PUBLIC
    return template


@pytest.fixture
def public_pending_template(owner_user_id):
    """Create a public template with no approved version yet."""
    template = Mock(spec=Template)
    template.id = str(uuid4())
    template.owner_id = owner_user_id
    template.visibility = TemplateVisibility.PUBLIC
    return template


class TestTemplateServiceAccessControl:
    """Test access control in TemplateService."""

    def test_can_access_template_admin_can_access_any(
        self, template_service, private_template, other_user_id
    ):
        """Admin can access any template."""
        assert template_service._can_access_template(
            private_template, user_id=other_user_id, is_admin=True
        )

    def test_can_access_template_owner_can_access_own_private(
        self, template_service, private_template, owner_user_id
    ):
        """Owner can access their own private template."""
        assert template_service._can_access_template(
            private_template, user_id=owner_user_id, is_admin=False
        )

    def test_can_access_template_non_owner_cannot_access_private(
        self, template_service, private_template, other_user_id
    ):
        """Non-owner cannot access private template."""
        assert not template_service._can_access_template(
            private_template, user_id=other_user_id, is_admin=False
        )

    def test_can_access_template_anyone_can_access_public_approved(
        self, template_service, public_approved_template, other_user_id
    ):
        """Non-owner can access a public template that has an APPROVED version."""
        template_service.template_repo = Mock()
        template_service.template_repo.has_approved_version.return_value = True
        assert template_service._can_access_template(
            public_approved_template, user_id=other_user_id, is_admin=False
        )

    def test_can_access_template_non_owner_cannot_access_public_pending(
        self, template_service, public_pending_template, other_user_id
    ):
        """Non-owner CANNOT access a public template with no approved version yet.

        Safety-net: a public template only becomes visible to non-owners once
        at least one version has been approved. Per-version gating still applies
        on top of this in TemplateVersionService._can_access_version.
        """
        template_service.template_repo = Mock()
        template_service.template_repo.has_approved_version.return_value = False
        assert not template_service._can_access_template(
            public_pending_template, user_id=other_user_id, is_admin=False
        )

    def test_can_access_template_owner_can_access_public_pending(
        self, template_service, public_pending_template, owner_user_id
    ):
        """Owner can access their own public pending template."""
        assert template_service._can_access_template(
            public_pending_template, user_id=owner_user_id, is_admin=False
        )

    def test_can_access_template_no_user_id_denies_access(
        self, template_service, public_approved_template
    ):
        """No user_id denies access."""
        assert not template_service._can_access_template(
            public_approved_template, user_id=None, is_admin=False
        )

    def test_get_template_owner_can_view_private(
        self, template_service, private_template, owner_user_id
    ):
        """Owner can view their private template."""
        template_service.template_repo = Mock()
        template_service.template_repo.get_by_id.return_value = private_template

        result = template_service.get_template(
            private_template.id, user_id=owner_user_id, is_admin=False
        )

        assert result == private_template

    def test_get_template_non_owner_cannot_view_private(
        self, template_service, private_template, other_user_id
    ):
        """Non-owner cannot view private template."""
        template_service.template_repo = Mock()
        template_service.template_repo.get_by_id.return_value = private_template

        with pytest.raises(ForbiddenException) as exc_info:
            template_service.get_template(
                private_template.id, user_id=other_user_id, is_admin=False
            )

        assert "permission" in str(exc_info.value).lower()

    def test_get_template_admin_can_view_any(
        self, template_service, private_template, other_user_id
    ):
        """Admin can view any template."""
        template_service.template_repo = Mock()
        template_service.template_repo.get_by_id.return_value = private_template

        result = template_service.get_template(
            private_template.id, user_id=other_user_id, is_admin=True
        )

        assert result == private_template

    def test_get_template_not_found(self, template_service, owner_user_id):
        """Get template raises NotFoundException when template not found."""
        template_service.template_repo = Mock()
        template_service.template_repo.get_by_id.return_value = None

        with pytest.raises(NotFoundException):
            template_service.get_template(
                str(uuid4()), user_id=owner_user_id, is_admin=False
            )

    def test_list_templates_passes_user_id_for_non_admin(
        self, template_service, public_approved_template, other_user_id
    ):
        """Non-admin list pushes the safety-net filter into SQL via visible_to_user_id."""
        template_service.template_repo = Mock()
        template_service.template_repo.get_all_filtered.return_value = (
            [public_approved_template],
            1,
        )

        templates, total = template_service.list_templates(
            user_id=other_user_id, is_admin=False
        )

        # Repo was asked to apply the safety-net filter for this user.
        kwargs = template_service.template_repo.get_all_filtered.call_args.kwargs
        assert kwargs["visible_to_user_id"] == other_user_id
        assert templates == [public_approved_template]
        assert total == 1

    def test_list_templates_admin_sees_all(
        self, template_service, private_template, public_approved_template, other_user_id
    ):
        """Admin bypasses the safety-net filter (visible_to_user_id is None)."""
        template_service.template_repo = Mock()
        template_service.template_repo.get_all_filtered.return_value = (
            [private_template, public_approved_template],
            2
        )

        templates, total = template_service.list_templates(
            user_id=other_user_id, is_admin=True
        )

        kwargs = template_service.template_repo.get_all_filtered.call_args.kwargs
        assert kwargs["visible_to_user_id"] is None
        assert len(templates) == 2
        assert total == 2


class TestTemplateVersionServiceAccessControl:
    """Test access control in TemplateVersionService."""

    def test_check_template_access_raises_forbidden_for_private(
        self, template_version_service, private_template, other_user_id
    ):
        """Check template access raises ForbiddenException for private template."""
        template_version_service.template_repo = Mock()
        template_version_service.template_repo.get_by_id.return_value = private_template

        with pytest.raises(ForbiddenException):
            template_version_service._check_template_access(
                private_template.id, user_id=other_user_id, is_admin=False
            )

    def test_check_template_access_allows_owner(
        self, template_version_service, private_template, owner_user_id
    ):
        """Check template access allows owner."""
        template_version_service.template_repo = Mock()
        template_version_service.template_repo.get_by_id.return_value = private_template

        result = template_version_service._check_template_access(
            private_template.id, user_id=owner_user_id, is_admin=False
        )

        assert result == private_template

    def test_get_version_checks_parent_template_access(
        self, template_version_service, private_template, other_user_id
    ):
        """Get version checks parent template access."""
        version = Mock(spec=TemplateVersion)
        version.id = str(uuid4())
        version.template_id = private_template.id

        template_version_service.version_repo = Mock()
        template_version_service.version_repo.get_by_id.return_value = version
        template_version_service.template_repo = Mock()
        template_version_service.template_repo.get_by_id.return_value = private_template

        with pytest.raises(ForbiddenException):
            template_version_service.get_version(
                version.id, user_id=other_user_id, is_admin=False
            )

    def test_list_template_versions_checks_parent_access(
        self, template_version_service, private_template, other_user_id
    ):
        """List template versions checks parent template access."""
        template_version_service.template_repo = Mock()
        template_version_service.template_repo.get_by_id.return_value = private_template

        with pytest.raises(ForbiddenException):
            template_version_service.list_template_versions(
                private_template.id, user_id=other_user_id, is_admin=False
            )


class TestTemplateVersionFileServiceAccessControl:
    """Test access control in TemplateVersionFileService."""

    def test_check_template_access_via_version(
        self, template_version_file_service, private_template, other_user_id
    ):
        """Check template access via version ID."""
        version = Mock(spec=TemplateVersion)
        version.id = str(uuid4())
        version.template_id = private_template.id

        template_version_file_service.version_repo = Mock()
        template_version_file_service.version_repo.get_by_id.return_value = version
        template_version_file_service.template_repo = Mock()
        template_version_file_service.template_repo.get_by_id.return_value = private_template

        with pytest.raises(ForbiddenException):
            template_version_file_service._check_template_access(
                version.id, user_id=other_user_id, is_admin=False
            )

    def test_get_file_checks_parent_template_access(
        self, template_version_file_service, private_template, other_user_id
    ):
        """Get file checks parent template access."""
        version = Mock(spec=TemplateVersion)
        version.id = str(uuid4())
        version.template_id = private_template.id

        file = Mock(spec=TemplateVersionFile)
        file.id = str(uuid4())
        file.template_version_id = version.id

        template_version_file_service.file_repo = Mock()
        template_version_file_service.file_repo.get_by_id.return_value = file
        template_version_file_service.version_repo = Mock()
        template_version_file_service.version_repo.get_by_id.return_value = version
        template_version_file_service.template_repo = Mock()
        template_version_file_service.template_repo.get_by_id.return_value = private_template

        with pytest.raises(ForbiddenException):
            template_version_file_service.get_file(
                file.id, user_id=other_user_id, is_admin=False
            )

    def test_get_version_files_checks_parent_access(
        self, template_version_file_service, private_template, other_user_id
    ):
        """Get version files checks parent template access."""
        version = Mock(spec=TemplateVersion)
        version.id = str(uuid4())
        version.template_id = private_template.id

        template_version_file_service.version_repo = Mock()
        template_version_file_service.version_repo.get_by_id.return_value = version
        template_version_file_service.template_repo = Mock()
        template_version_file_service.template_repo.get_by_id.return_value = private_template

        with pytest.raises(ForbiddenException):
            template_version_file_service.get_version_files(
                version.id, user_id=other_user_id, is_admin=False
            )

    def test_get_version_files_skip_access_check(
        self, template_version_file_service, private_template, other_user_id
    ):
        """Get version files with skip_access_check bypasses access control."""
        version = Mock(spec=TemplateVersion)
        version.id = str(uuid4())
        version.template_id = private_template.id

        # Mock repos
        template_version_file_service.file_repo = Mock()
        template_version_file_service.file_repo.get_by_version_id.return_value = []
        template_version_file_service.version_repo = Mock()
        template_version_file_service.template_repo = Mock()

        # Should succeed and return empty list without checking access
        files = template_version_file_service.get_version_files(
            version.id, user_id=other_user_id, is_admin=False, skip_access_check=True
        )

        assert files == []
        # Verify access check repos were NOT called
        template_version_file_service.version_repo.get_by_id.assert_not_called()
        template_version_file_service.template_repo.get_by_id.assert_not_called()

    def test_get_template_parameters_skip_access_check(
        self, template_version_file_service, private_template, other_user_id
    ):
        """Get template parameters with skip_access_check bypasses access control."""
        version = Mock(spec=TemplateVersion)
        version.id = str(uuid4())
        version.template_id = private_template.id

        # Mock file repo to return no files (will raise NotFoundException)
        template_version_file_service.file_repo = Mock()
        template_version_file_service.file_repo.get_by_version_id.return_value = []

        # Should raise NotFoundException (no app.yaml), not ForbiddenException
        with pytest.raises(NotFoundException) as exc_info:
            template_version_file_service.get_template_parameters(
                version.id, user_id=other_user_id, is_admin=False, skip_access_check=True
            )

        assert "app.yaml" in str(exc_info.value).lower()

    def test_get_template_parameters_checks_access_by_default(
        self, template_version_file_service, private_template, other_user_id
    ):
        """Get template parameters checks access by default."""
        version = Mock(spec=TemplateVersion)
        version.id = str(uuid4())
        version.template_id = private_template.id

        template_version_file_service.version_repo = Mock()
        template_version_file_service.version_repo.get_by_id.return_value = version
        template_version_file_service.template_repo = Mock()
        template_version_file_service.template_repo.get_by_id.return_value = private_template

        # Should raise ForbiddenException before trying to get files
        with pytest.raises(ForbiddenException):
            template_version_file_service.get_template_parameters(
                version.id, user_id=other_user_id, is_admin=False, skip_access_check=False
            )

    # ------------------------------------------------------------------
    # update_file / delete_file: previously did NOT check parent template
    # ownership — any authenticated user with a file_id could mutate or
    # delete files on private templates. Regression tests below pin the
    # corrected behaviour: admins always pass, template owners always
    # pass, everyone else gets 403.
    # ------------------------------------------------------------------

    def _seed_file_under_template(self, service, template):
        """Helper: wire repos so file_id resolves to a file whose parent
        template is the given one. Returns the mock file."""
        from src.models.template_version_file import TemplateVersionFile

        version = Mock(spec=TemplateVersion)
        version.id = str(uuid4())
        version.template_id = template.id

        file = Mock(spec=TemplateVersionFile)
        file.id = str(uuid4())
        file.template_version_id = version.id
        # Defaults for the primary-flag branch in update_file
        file.is_primary = False

        service.file_repo = Mock()
        service.file_repo.get_by_id.return_value = file
        service.file_repo.get_primary_file.return_value = None
        service.version_repo = Mock()
        service.version_repo.get_by_id.return_value = version
        service.template_repo = Mock()
        service.template_repo.get_by_id.return_value = template
        return file

    def test_update_file_forbidden_for_non_owner_non_admin(
        self, template_version_file_service, private_template, other_user_id
    ):
        from src.schemas.template_version_file import TemplateVersionFileUpdate

        self._seed_file_under_template(template_version_file_service, private_template)

        with pytest.raises(ForbiddenException):
            template_version_file_service.update_file(
                file_id=str(uuid4()),
                file_data=TemplateVersionFileUpdate(file_type="OTHER"),
                user_id=other_user_id,
                is_admin=False,
            )

    def test_update_file_allowed_for_admin(
        self, template_version_file_service, private_template, other_user_id
    ):
        from src.schemas.template_version_file import TemplateVersionFileUpdate

        file = self._seed_file_under_template(template_version_file_service, private_template)
        # Mock the persistence layer so we don't hit a real DB.
        template_version_file_service.db = MagicMock()

        result = template_version_file_service.update_file(
            file_id=file.id,
            file_data=TemplateVersionFileUpdate(file_type="HEAT_TEMPLATE"),
            user_id=other_user_id,  # NOT the owner — admin override is the point
            is_admin=True,
        )
        assert result is file  # update is in-place on the mock

    def test_update_file_allowed_for_owner(
        self, template_version_file_service, private_template, owner_user_id
    ):
        from src.schemas.template_version_file import TemplateVersionFileUpdate

        file = self._seed_file_under_template(template_version_file_service, private_template)
        template_version_file_service.db = MagicMock()

        result = template_version_file_service.update_file(
            file_id=file.id,
            file_data=TemplateVersionFileUpdate(file_type="ANSIBLE_PLAYBOOK"),
            user_id=owner_user_id,
            is_admin=False,
        )
        assert result is file

    def test_update_file_forbidden_without_user_id(
        self, template_version_file_service, private_template
    ):
        """Bare ``update_file(...)`` without identifying the caller must
        not silently succeed — that was the original bug."""
        from src.schemas.template_version_file import TemplateVersionFileUpdate

        self._seed_file_under_template(template_version_file_service, private_template)

        with pytest.raises(ForbiddenException):
            template_version_file_service.update_file(
                file_id=str(uuid4()),
                file_data=TemplateVersionFileUpdate(file_type="OTHER"),
                # No user_id, no is_admin — default permissive would be wrong.
            )

    def test_delete_file_forbidden_for_non_owner_non_admin(
        self, template_version_file_service, private_template, other_user_id
    ):
        self._seed_file_under_template(template_version_file_service, private_template)

        with pytest.raises(ForbiddenException):
            template_version_file_service.delete_file(
                file_id=str(uuid4()),
                user_id=other_user_id,
                is_admin=False,
            )
        # Repo's delete must NOT have been called — guard against future
        # refactors that move the delete before the permission check.
        template_version_file_service.file_repo.delete.assert_not_called()

    def test_delete_file_allowed_for_admin(
        self, template_version_file_service, private_template, other_user_id
    ):
        file = self._seed_file_under_template(template_version_file_service, private_template)

        template_version_file_service.delete_file(
            file_id=file.id,
            user_id=other_user_id,
            is_admin=True,
        )
        # delete_file normalises the file_id to UUID before handing it to the
        # repo (BaseRepository.delete is typed UUID). Assert the call shape,
        # not the exact value, since we passed a string in.
        template_version_file_service.file_repo.delete.assert_called_once()
        called_with = template_version_file_service.file_repo.delete.call_args.args[0]
        assert str(called_with) == file.id

    def test_delete_file_allowed_for_owner(
        self, template_version_file_service, private_template, owner_user_id
    ):
        file = self._seed_file_under_template(template_version_file_service, private_template)

        template_version_file_service.delete_file(
            file_id=file.id,
            user_id=owner_user_id,
            is_admin=False,
        )
        template_version_file_service.file_repo.delete.assert_called_once()
        called_with = template_version_file_service.file_repo.delete.call_args.args[0]
        assert str(called_with) == file.id
