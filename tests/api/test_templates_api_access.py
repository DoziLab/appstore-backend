"""API tests for template access control."""
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.main import app
from src.core.database import Base
from src.core.dependencies import get_db, get_current_user
from src.models.template import Template, TemplateVisibility
from src.models.template_version import TemplateVersion
from src.models.template_version_file import TemplateVersionFile, FileType
from src.models.user import User


# Create in-memory SQLite database for testing
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db_session():
    """Create a fresh database for each test."""
    # Import all models to ensure they're registered
    import src.models.deployment  # noqa
    import src.models.deployment_instance  # noqa
    import src.models.deployment_instance_access  # noqa
    import src.models.deployment_log  # noqa
    import src.models.template_category  # noqa
    import src.models.template_category_assignment  # noqa
    import src.models.template_version_file  # noqa
    import src.models.course  # noqa
    import src.models.course_member  # noqa
    import src.models.course_group  # noqa
    import src.models.group_member  # noqa
    import src.models.openstack_project  # noqa

    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def owner_user(db_session):
    """Create template owner user."""
    user = User(
        id="owner-user-id",
        external_id="owner-ext-id",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def other_user(db_session):
    """Create non-owner user."""
    user = User(
        id="other-user-id",
        external_id="other-ext-id",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def admin_user(db_session):
    """Create admin user."""
    user = User(
        id="admin-user-id",
        external_id="admin-ext-id",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def private_template(db_session, owner_user):
    """Create a private template."""
    template = Template(
        name="Private Template",
        description="A private template",
        owner_id=owner_user.id,
        repo_url="https://github.com/example/private-template",
        visibility=TemplateVisibility.PRIVATE,
    )
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)
    return template


@pytest.fixture
def public_approved_template(db_session, owner_user):
    """Create a public template with an APPROVED version."""
    from src.models.template_version import TemplateVersionApprovalStatus

    template = Template(
        name="Public Template",
        description="A public template",
        owner_id=owner_user.id,
        repo_url="https://github.com/example/public-template",
        visibility=TemplateVisibility.PUBLIC,
    )
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)

    version = TemplateVersion(
        template_id=template.id,
        version="1.0.0",
        git_commit_sha="public-approved-sha",
        is_active=True,
        approval_status=TemplateVersionApprovalStatus.APPROVED,
    )
    db_session.add(version)
    db_session.commit()
    return template


@pytest.fixture
def template_version(db_session, private_template):
    """Create a template version."""
    version = TemplateVersion(
        template_id=private_template.id,
        version="1.0.0",
        git_commit_sha="abc123",
        is_active=True,
    )
    db_session.add(version)
    db_session.commit()
    db_session.refresh(version)
    return version


@pytest.fixture
def template_file(db_session, template_version):
    """Create a template version file."""
    file = TemplateVersionFile(
        template_version_id=template_version.id,
        file_name="test.yaml",
        file_type=FileType.HEAT_TEMPLATE,
        file_path="test.yaml",
        content="test: content",
        file_size=100,
        is_primary=True,
    )
    db_session.add(file)
    db_session.commit()
    db_session.refresh(file)
    return file


def create_client_with_user(db_session, user, is_admin=False):
    """Create test client with specific user context."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    def override_get_current_user():
        roles = ["admin", "lecturer"] if is_admin else ["lecturer"]
        return {
            "sub": user.external_id,
            "email": f"{user.id}@example.com",
            "name": "Test User",
            "preferred_username": user.id,
            "roles": roles,
            "user_id": user.id,
        }

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    client = TestClient(app)
    return client


class TestTemplateAccessControl:
    """Test template access control in API endpoints."""

    def test_owner_can_view_private_template(
        self, db_session, owner_user, private_template
    ):
        """Owner can view their private template."""
        client = create_client_with_user(db_session, owner_user)

        response = client.get(f"/api/v1/templates/{private_template.id}")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["data"]["id"] == private_template.id

    def test_non_owner_cannot_view_private_template(
        self, db_session, other_user, private_template
    ):
        """Non-owner cannot view private template."""
        client = create_client_with_user(db_session, other_user)

        response = client.get(f"/api/v1/templates/{private_template.id}")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        data = response.json()
        assert "permission" in data["message"].lower()

    def test_admin_can_view_any_template(
        self, db_session, admin_user, private_template
    ):
        """Admin can view any template."""
        client = create_client_with_user(db_session, admin_user, is_admin=True)

        response = client.get(f"/api/v1/templates/{private_template.id}")

        assert response.status_code == status.HTTP_200_OK

    def test_non_owner_can_view_public_approved_template(
        self, db_session, other_user, public_approved_template
    ):
        """Non-owner can view public approved template."""
        client = create_client_with_user(db_session, other_user)

        response = client.get(f"/api/v1/templates/{public_approved_template.id}")

        assert response.status_code == status.HTTP_200_OK

    def test_list_templates_filters_private_for_non_owner(
        self, db_session, other_user, private_template, public_approved_template
    ):
        """List templates filters private templates for non-owner."""
        client = create_client_with_user(db_session, other_user)

        response = client.get("/api/v1/templates")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        template_ids = [t["id"] for t in data["data"]]

        # Should only see public approved template
        assert public_approved_template.id in template_ids
        assert private_template.id not in template_ids

    def test_list_templates_shows_own_private_for_owner(
        self, db_session, owner_user, private_template, public_approved_template
    ):
        """List templates shows own private templates for owner."""
        client = create_client_with_user(db_session, owner_user)

        response = client.get("/api/v1/templates")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        template_ids = [t["id"] for t in data["data"]]

        # Should see both templates
        assert public_approved_template.id in template_ids
        assert private_template.id in template_ids


class TestTemplateVersionAccessControl:
    """Test template version access control in API endpoints."""

    def test_non_owner_cannot_view_version_of_private_template(
        self, db_session, other_user, template_version
    ):
        """Non-owner cannot view version of private template."""
        client = create_client_with_user(db_session, other_user)

        response = client.get(f"/api/v1/template-versions/{template_version.id}")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_owner_can_view_version_of_private_template(
        self, db_session, owner_user, template_version
    ):
        """Owner can view version of their private template."""
        client = create_client_with_user(db_session, owner_user)

        response = client.get(f"/api/v1/template-versions/{template_version.id}")

        assert response.status_code == status.HTTP_200_OK

    def test_admin_can_view_version_of_any_template(
        self, db_session, admin_user, template_version
    ):
        """Admin can view version of any template."""
        client = create_client_with_user(db_session, admin_user, is_admin=True)

        response = client.get(f"/api/v1/template-versions/{template_version.id}")

        assert response.status_code == status.HTTP_200_OK

    def test_non_owner_cannot_list_versions_of_private_template(
        self, db_session, other_user, private_template, template_version
    ):
        """Non-owner cannot list versions of private template."""
        client = create_client_with_user(db_session, other_user)

        response = client.get(
            f"/api/v1/template-versions/template/{private_template.id}"
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_owner_can_list_versions_of_private_template(
        self, db_session, owner_user, private_template, template_version
    ):
        """Owner can list versions of their private template."""
        client = create_client_with_user(db_session, owner_user)

        response = client.get(
            f"/api/v1/template-versions/template/{private_template.id}"
        )

        assert response.status_code == status.HTTP_200_OK


class TestTemplateVersionFileAccessControl:
    """Test template version file access control in API endpoints."""

    def test_non_owner_cannot_view_file_of_private_template(
        self, db_session, other_user, template_file
    ):
        """Non-owner cannot view file of private template."""
        client = create_client_with_user(db_session, other_user)

        response = client.get(f"/api/v1/template-version-files/{template_file.id}")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_owner_can_view_file_of_private_template(
        self, db_session, owner_user, template_file
    ):
        """Owner can view file of their private template."""
        client = create_client_with_user(db_session, owner_user)

        response = client.get(f"/api/v1/template-version-files/{template_file.id}")

        assert response.status_code == status.HTTP_200_OK

    def test_admin_can_view_file_of_any_template(
        self, db_session, admin_user, template_file
    ):
        """Admin can view file of any template."""
        client = create_client_with_user(db_session, admin_user, is_admin=True)

        response = client.get(f"/api/v1/template-version-files/{template_file.id}")

        assert response.status_code == status.HTTP_200_OK

    def test_non_owner_cannot_list_files_of_private_template(
        self, db_session, other_user, template_version, template_file
    ):
        """Non-owner cannot list files of private template."""
        client = create_client_with_user(db_session, other_user)

        response = client.get(
            f"/api/v1/template-version-files/version/{template_version.id}"
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_owner_can_list_files_of_private_template(
        self, db_session, owner_user, template_version, template_file
    ):
        """Owner can list files of their private template."""
        client = create_client_with_user(db_session, owner_user)

        response = client.get(
            f"/api/v1/template-version-files/version/{template_version.id}"
        )

        assert response.status_code == status.HTTP_200_OK

    def test_non_owner_cannot_view_files_of_pending_version_on_public_template(
        self, db_session, other_user, owner_user
    ):
        """Regression: non-owner must NOT access files of a PENDING version,
        even when the parent public template has another APPROVED version.

        Before this fix, file access was authorized only at the template level
        via the safety net (`has_approved_version`), which would let any
        non-owner pull the file content of unreviewed versions on the same
        template. Per-version approval must gate file access too.
        """
        from src.models.template_version import TemplateVersionApprovalStatus
        from src.models.template_version_file import TemplateVersionFile, FileType

        template = Template(
            name="Public mixed-status template",
            description=None,
            owner_id=owner_user.id,
            repo_url="https://example.com/mixed",
            visibility=TemplateVisibility.PUBLIC,
        )
        db_session.add(template)
        db_session.commit()
        db_session.refresh(template)

        approved = TemplateVersion(
            template_id=template.id,
            version="1.0.0",
            git_commit_sha="approved-sha",
            is_active=False,
            approval_status=TemplateVersionApprovalStatus.APPROVED,
        )
        pending = TemplateVersion(
            template_id=template.id,
            version="1.1.0",
            git_commit_sha="pending-sha",
            is_active=True,
            approval_status=TemplateVersionApprovalStatus.PENDING,
        )
        db_session.add_all([approved, pending])
        db_session.commit()
        db_session.refresh(approved)
        db_session.refresh(pending)

        secret_file = TemplateVersionFile(
            template_version_id=pending.id,
            file_name="app.yaml",
            file_type=FileType.APP_MANIFEST,
            file_path="app.yaml",
            content="secret: not-yet-reviewed",
            file_size=24,
            is_primary=False,
        )
        db_session.add(secret_file)
        db_session.commit()
        db_session.refresh(secret_file)

        client = create_client_with_user(db_session, other_user)

        # Direct file fetch
        file_resp = client.get(f"/api/v1/template-version-files/{secret_file.id}")
        assert file_resp.status_code == status.HTTP_403_FORBIDDEN

        # Listing files of the pending version
        list_resp = client.get(
            f"/api/v1/template-version-files/version/{pending.id}"
        )
        assert list_resp.status_code == status.HTTP_403_FORBIDDEN


# Clean up after tests
@pytest.fixture(autouse=True)
def cleanup():
    """Cleanup after each test."""
    yield
    app.dependency_overrides.clear()


class TestApprovalQueue:
    """Tests for the admin approval queue endpoint."""

    @pytest.fixture
    def pending_version_private(self, db_session, private_template):
        """Pending version on a private template."""
        from src.models.template_version import TemplateVersionApprovalStatus

        v = TemplateVersion(
            template_id=private_template.id,
            version="1.0.0",
            git_commit_sha="pending-private-sha",
            is_active=True,
            approval_status=TemplateVersionApprovalStatus.PENDING,
        )
        db_session.add(v)
        db_session.commit()
        db_session.refresh(v)
        return v

    @pytest.fixture
    def pending_version_public(self, db_session, public_approved_template):
        """A second, still-pending version on a public template (which already has an approved one)."""
        from src.models.template_version import TemplateVersionApprovalStatus

        v = TemplateVersion(
            template_id=public_approved_template.id,
            version="1.1.0",
            git_commit_sha="pending-public-sha",
            is_active=False,
            approval_status=TemplateVersionApprovalStatus.PENDING,
        )
        db_session.add(v)
        db_session.commit()
        db_session.refresh(v)
        return v

    def test_admin_sees_pending_versions_across_templates(
        self,
        db_session,
        admin_user,
        pending_version_private,
        pending_version_public,
    ):
        """Admin queue (default status=pending) returns pending versions across all templates."""
        client = create_client_with_user(db_session, admin_user, is_admin=True)

        response = client.get("/api/v1/template-versions/queue")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        version_ids = [v["id"] for v in data["data"]]

        assert pending_version_private.id in version_ids
        assert pending_version_public.id in version_ids

        for row in data["data"]:
            assert row["approval_status"] == "pending"
            assert "template" in row
            assert {"id", "name", "owner_id", "visibility"}.issubset(row["template"].keys())

    def test_non_admin_cannot_access_queue(
        self,
        db_session,
        owner_user,
        pending_version_private,
    ):
        """Lecturer (non-admin) gets 403 from the approval queue."""
        client = create_client_with_user(db_session, owner_user, is_admin=False)

        response = client.get("/api/v1/template-versions/queue")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_status_filter_approved(
        self,
        db_session,
        admin_user,
        pending_version_private,
        public_approved_template,
    ):
        """status=approved returns only approved versions."""
        client = create_client_with_user(db_session, admin_user, is_admin=True)

        response = client.get("/api/v1/template-versions/queue?status=approved")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        for row in data["data"]:
            assert row["approval_status"] == "approved"

        assert pending_version_private.id not in [r["id"] for r in data["data"]]

    def test_template_id_filter(
        self,
        db_session,
        admin_user,
        private_template,
        pending_version_private,
        pending_version_public,
    ):
        """template_id filter restricts the queue to one template."""
        client = create_client_with_user(db_session, admin_user, is_admin=True)

        response = client.get(
            f"/api/v1/template-versions/queue?template_id={private_template.id}"
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        version_ids = [v["id"] for v in data["data"]]

        assert pending_version_private.id in version_ids
        assert pending_version_public.id not in version_ids

    def test_visibility_filter(
        self,
        db_session,
        admin_user,
        pending_version_private,
        pending_version_public,
    ):
        """visibility filter restricts queue rows by parent template visibility."""
        client = create_client_with_user(db_session, admin_user, is_admin=True)

        public_only = client.get("/api/v1/template-versions/queue?visibility=public")
        assert public_only.status_code == status.HTTP_200_OK
        ids_public = [v["id"] for v in public_only.json()["data"]]
        assert pending_version_public.id in ids_public
        assert pending_version_private.id not in ids_public

        private_only = client.get("/api/v1/template-versions/queue?visibility=private")
        assert private_only.status_code == status.HTTP_200_OK
        ids_private = [v["id"] for v in private_only.json()["data"]]
        assert pending_version_private.id in ids_private
        assert pending_version_public.id not in ids_private

    def test_sort_template_name_asc(
        self,
        db_session,
        admin_user,
        owner_user,
    ):
        """sort=template_name_asc orders rows by template.name ascending."""
        from src.models.template_version import TemplateVersionApprovalStatus

        z_template = Template(
            name="Z-template",
            description=None,
            owner_id=owner_user.id,
            repo_url="https://example.com/z",
            visibility=TemplateVisibility.PRIVATE,
        )
        a_template = Template(
            name="A-template",
            description=None,
            owner_id=owner_user.id,
            repo_url="https://example.com/a",
            visibility=TemplateVisibility.PRIVATE,
        )
        db_session.add_all([z_template, a_template])
        db_session.commit()
        db_session.refresh(z_template)
        db_session.refresh(a_template)

        for tmpl, sha in [(z_template, "z-sha"), (a_template, "a-sha")]:
            v = TemplateVersion(
                template_id=tmpl.id,
                version="1.0.0",
                git_commit_sha=sha,
                is_active=True,
                approval_status=TemplateVersionApprovalStatus.PENDING,
            )
            db_session.add(v)
        db_session.commit()

        client = create_client_with_user(db_session, admin_user, is_admin=True)
        response = client.get(
            "/api/v1/template-versions/queue?sort=template_name_asc"
        )
        assert response.status_code == status.HTTP_200_OK
        names_in_order = [r["template"]["name"] for r in response.json()["data"]]

        a_idx = names_in_order.index("A-template")
        z_idx = names_in_order.index("Z-template")
        assert a_idx < z_idx

    def test_parameters_inlined_from_app_yaml(
        self,
        db_session,
        admin_user,
        private_template,
    ):
        """Each queue row inlines `parameters` parsed from app.yaml of the version."""
        from src.models.template_version import TemplateVersionApprovalStatus
        from src.models.template_version_file import TemplateVersionFile, FileType

        v = TemplateVersion(
            template_id=private_template.id,
            version="1.0.0",
            git_commit_sha="param-sha",
            is_active=True,
            approval_status=TemplateVersionApprovalStatus.PENDING,
        )
        db_session.add(v)
        db_session.commit()
        db_session.refresh(v)

        manifest = """
app:
  name: test-app
  version: 1.0.0
parameters:
  - name: cpu
    type: integer
    default: 2
    required: true
  - name: ram_mb
    type: integer
    default: 2048
    required: true
"""
        f = TemplateVersionFile(
            template_version_id=v.id,
            file_name="app.yaml",
            file_type=FileType.APP_MANIFEST,
            file_path="app.yaml",
            content=manifest,
            file_size=len(manifest),
            is_primary=False,
        )
        db_session.add(f)
        db_session.commit()

        client = create_client_with_user(db_session, admin_user, is_admin=True)
        response = client.get(
            f"/api/v1/template-versions/queue?template_id={private_template.id}"
        )
        assert response.status_code == status.HTTP_200_OK
        rows = response.json()["data"]
        assert len(rows) == 1

        params = rows[0]["parameters"]
        param_names = {p["name"] for p in params}
        assert "cpu" in param_names
        assert "ram_mb" in param_names


class TestRejectVersionWithReason:
    """Tests for `POST /template-versions/{id}/reject` with optional reason body.

    Approval/rejection only apply to PUBLIC templates — private templates now
    return ``approval_status=None`` and the approve/reject endpoints 400 them.
    """

    @pytest.fixture
    def pending_version(self, db_session, public_approved_template):
        from src.models.template_version import TemplateVersionApprovalStatus

        # Auf demselben PUBLIC-Template gibt es schon v1.0.0 APPROVED — wir
        # legen v1.1.0 PENDING an, damit der UniqueConstraint auf
        # (template_id, version) nicht stört.
        v = TemplateVersion(
            template_id=public_approved_template.id,
            version="1.1.0",
            git_commit_sha="reject-test-sha",
            is_active=False,
            approval_status=TemplateVersionApprovalStatus.PENDING,
        )
        db_session.add(v)
        db_session.commit()
        db_session.refresh(v)
        return v

    def test_reject_persists_reason(self, db_session, admin_user, pending_version):
        """Reject with a reason body persists rejection_reason."""
        client = create_client_with_user(db_session, admin_user, is_admin=True)

        response = client.post(
            f"/api/v1/template-versions/{pending_version.id}/reject",
            json={"reason": "app.yaml is missing required parameters"},
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["data"]["approval_status"] == "rejected"
        assert body["data"]["rejection_reason"] == "app.yaml is missing required parameters"

        db_session.expire(pending_version)
        db_session.refresh(pending_version)
        assert pending_version.rejection_reason == "app.yaml is missing required parameters"

    def test_reject_without_body_works(self, db_session, admin_user, pending_version):
        """Reject without any body still works; rejection_reason stays None."""
        client = create_client_with_user(db_session, admin_user, is_admin=True)

        response = client.post(
            f"/api/v1/template-versions/{pending_version.id}/reject",
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["data"]["approval_status"] == "rejected"
        assert body["data"]["rejection_reason"] is None

    def test_approve_clears_previous_rejection_reason(
        self, db_session, admin_user, pending_version
    ):
        """Re-approving a previously rejected version clears its rejection_reason."""
        client = create_client_with_user(db_session, admin_user, is_admin=True)

        client.post(
            f"/api/v1/template-versions/{pending_version.id}/reject",
            json={"reason": "broken"},
        )
        approve_response = client.post(
            f"/api/v1/template-versions/{pending_version.id}/approve",
        )

        assert approve_response.status_code == status.HTTP_200_OK
        body = approve_response.json()
        assert body["data"]["approval_status"] == "approved"
        assert body["data"]["rejection_reason"] is None

    def test_non_admin_cannot_reject(self, db_session, owner_user, pending_version):
        """Lecturer (non-admin) cannot reject."""
        client = create_client_with_user(db_session, owner_user, is_admin=False)

        response = client.post(
            f"/api/v1/template-versions/{pending_version.id}/reject",
            json={"reason": "any"},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestImportFromGithubVisibility:
    """The import-from-github schema accepts an optional visibility field
    (private/public). Default is private. Invalid values are rejected.

    This used to be a hard ban on the field; now lecturers can choose at
    import time whether the template lives in private or public space."""

    def test_schema_exposes_visibility_field(self):
        from src.schemas.template import GithubImportNewTemplate

        assert "visibility" in GithubImportNewTemplate.model_fields

    def test_default_visibility_is_private(self):
        from src.schemas.template import GithubImportNewTemplate

        p = GithubImportNewTemplate(
            name="x",
            github_url="https://github.com/a/b",
        )
        assert p.visibility == "private"

    def test_explicit_public_visibility_accepted(self):
        from src.schemas.template import GithubImportNewTemplate

        p = GithubImportNewTemplate(
            name="x",
            github_url="https://github.com/a/b",
            visibility="public",
        )
        assert p.visibility == "public"

    def test_uppercase_visibility_normalised(self):
        from src.schemas.template import GithubImportNewTemplate

        p = GithubImportNewTemplate(
            name="x",
            github_url="https://github.com/a/b",
            visibility="PUBLIC",
        )
        assert p.visibility == "public"

    def test_invalid_visibility_rejected(self):
        from src.schemas.template import GithubImportNewTemplate
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            GithubImportNewTemplate(
                name="x",
                github_url="https://github.com/a/b",
                visibility="secret",
            )
