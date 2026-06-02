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


# Clean up after tests
@pytest.fixture(autouse=True)
def cleanup():
    """Cleanup after each test."""
    yield
    app.dependency_overrides.clear()
