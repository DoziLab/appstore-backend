"""Tests for Template Version API endpoints."""
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.main import app
from src.core.database import Base
from src.core.dependencies import get_db, get_current_user
from src.models.template import Template, TemplateVisibility, TemplateApprovalStatus
from src.models.template_version import TemplateVersion
from src.models.user import User


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


@pytest.fixture(scope="function")
def client(db_session, mock_user):
    """Create test client with overridden database dependency."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    
    def override_get_current_user():
        """Mock authenticated user for tests."""
        return {
            "sub": mock_user.external_id,
            "email": "test@example.com",
            "name": "Test User",
            "preferred_username": "testuser",
            "roles": ["admin"],
            "user_id": mock_user.id,
        }
    
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def mock_user(db_session):
    """Create a mock user for testing."""
    user = User(
        id="00000000-0000-0000-0000-000000000000",
        external_id="test-user-ext-id",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def sample_template(db_session, mock_user):
    """Create a sample template for testing."""
    template = Template(
        name="Test Template",
        description="A template for testing",
        owner_id=mock_user.id,
        repo_url="https://github.com/example/test-template",
        visibility=TemplateVisibility.PUBLIC,
        approval_status=TemplateApprovalStatus.APPROVED,
    )
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)
    return template


@pytest.fixture
def sample_version(db_session, sample_template):
    """Create a sample template version for testing."""
    version = TemplateVersion(
        template_id=sample_template.id,
        git_commit_sha="abc123def456",
        is_active=True,
    )
    db_session.add(version)
    db_session.commit()
    db_session.refresh(version)
    return version


class TestListTemplateVersions:
    """Tests for GET /api/v1/template-versions/template/{template_id} endpoint."""
    
    def test_list_versions_empty(self, client, sample_template):
        """Test listing versions when none exist."""
        response = client.get(f"/api/v1/template-versions/template/{sample_template.id}")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        assert data["data"] == []
    
    def test_list_versions_with_data(self, client, sample_version):
        """Test listing versions with existing data."""
        response = client.get(f"/api/v1/template-versions/template/{sample_version.template_id}")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        assert len(data["data"]) == 1
        assert data["data"][0]["git_commit_sha"] == "abc123def456"
    
    def test_list_versions_active_only(self, client, db_session, sample_template):
        """Test filtering for active versions only."""
        active_version = TemplateVersion(
            template_id=sample_template.id,
            git_commit_sha="active123",
            is_active=True,
        )
        inactive_version = TemplateVersion(
            template_id=sample_template.id,
            git_commit_sha="inactive456",
            is_active=False,
        )
        db_session.add(active_version)
        db_session.add(inactive_version)
        db_session.commit()
        
        response = client.get(f"/api/v1/template-versions/template/{sample_template.id}?active_only=true")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["data"]) == 1
        assert data["data"][0]["is_active"] is True


class TestGetTemplateVersion:
    """Tests for GET /api/v1/template-versions/{id} endpoint."""
    
    def test_get_version_success(self, client, sample_version):
        """Test retrieving a version by ID."""
        response = client.get(f"/api/v1/template-versions/{sample_version.id}")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        assert data["data"]["id"] == sample_version.id
        assert data["data"]["git_commit_sha"] == "abc123def456"
    
    def test_get_version_not_found(self, client):
        """Test retrieving non-existent version."""
        fake_id = "00000000-0000-0000-0000-000000000001"
        response = client.get(f"/api/v1/template-versions/{fake_id}")
        
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestGetActiveVersion:
    """Tests for GET /api/v1/template-versions/template/{template_id}/active endpoint."""
    
    def test_get_active_version_success(self, client, sample_version):
        """Test retrieving active version."""
        response = client.get(f"/api/v1/template-versions/template/{sample_version.template_id}/active")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        assert data["data"]["is_active"] is True
    
    def test_get_active_version_not_found(self, client, db_session, mock_user):
        """Test retrieving active version when none exists."""
        # Create template without any versions
        template = Template(
            name="No Version Template",
            owner_id=mock_user.id,
            repo_url="https://github.com/example/no-version",
        )
        db_session.add(template)
        db_session.commit()
        db_session.refresh(template)
        
        response = client.get(f"/api/v1/template-versions/template/{template.id}/active")
        
        # API returns 200 with data=None when no active version exists
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        assert data["data"] is None


class TestCreateTemplateVersion:
    """Tests for POST /api/v1/template-versions endpoint."""
    
    def test_create_version_success(self, client, sample_template):
        """Test creating a new version."""
        version_data = {
            "template_id": sample_template.id,
            "git_commit_sha": "new789commit",
            "is_active": True,
        }
        
        response = client.post("/api/v1/template-versions", json=version_data)
        
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["success"] is True
        assert data["data"]["git_commit_sha"] == "new789commit"
        assert data["data"]["is_active"] is True
    
    def test_create_version_minimal_data(self, client, sample_template):
        """Test creating version with minimal required fields."""
        version_data = {
            "template_id": sample_template.id,
            "git_commit_sha": "minimal123",
        }
        
        response = client.post("/api/v1/template-versions", json=version_data)
        
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        # When is_active is not provided, service defaults to False unless it's the first version
        assert "is_active" in data["data"]
    
    def test_create_version_missing_required_fields(self, client):
        """Test creating version without required fields."""
        version_data = {
            "is_active": True
        }
        
        response = client.post("/api/v1/template-versions", json=version_data)
        
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


class TestUpdateTemplateVersion:
    """Tests for PATCH /api/v1/template-versions/{id} endpoint."""
    
    def test_update_version_success(self, client, sample_version):
        """Test updating a version."""
        update_data = {
            "git_commit_sha": "updated999"
        }
        
        response = client.patch(f"/api/v1/template-versions/{sample_version.id}", json=update_data)
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        assert data["data"]["git_commit_sha"] == "updated999"
    
    def test_update_version_not_found(self, client):
        """Test updating non-existent version."""
        fake_id = "00000000-0000-0000-0000-000000000001"
        update_data = {"git_commit_sha": "wont_work"}
        
        response = client.patch(f"/api/v1/template-versions/{fake_id}", json=update_data)
        
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestActivateTemplateVersion:
    """Tests for POST /api/v1/template-versions/{id}/activate endpoint."""
    
    def test_activate_version_success(self, client, db_session, sample_template):
        """Test activating a version."""
        # Create two versions, one inactive
        active_v1 = TemplateVersion(
            template_id=sample_template.id,
            git_commit_sha="active_v1",
            is_active=True,
        )
        inactive_v2 = TemplateVersion(
            template_id=sample_template.id,
            git_commit_sha="inactive_v2",
            is_active=False,
        )
        db_session.add(active_v1)
        db_session.add(inactive_v2)
        db_session.commit()
        db_session.refresh(inactive_v2)
        
        # Activate v2
        response = client.post(f"/api/v1/template-versions/{inactive_v2.id}/activate")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["data"]["is_active"] is True
        
        # Verify v1 is now inactive
        db_session.refresh(active_v1)
        assert active_v1.is_active is False
    
    def test_activate_already_active(self, client, sample_version):
        """Test activating an already active version."""
        response = client.post(f"/api/v1/template-versions/{sample_version.id}/activate")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["data"]["is_active"] is True


class TestDeleteTemplateVersion:
    """Tests for DELETE /api/v1/template-versions/{id} endpoint."""
    
    def test_delete_version_success(self, client, db_session, sample_template):
        """Test deleting a non-active version."""
        inactive_version = TemplateVersion(
            template_id=sample_template.id,
            git_commit_sha="to_delete",
            is_active=False,
        )
        db_session.add(inactive_version)
        db_session.commit()
        db_session.refresh(inactive_version)
        
        response = client.delete(f"/api/v1/template-versions/{inactive_version.id}")
        
        assert response.status_code == status.HTTP_204_NO_CONTENT
        
        # Verify version is deleted
        get_response = client.get(f"/api/v1/template-versions/{inactive_version.id}")
        assert get_response.status_code == status.HTTP_404_NOT_FOUND
    
    def test_delete_version_not_found(self, client):
        """Test deleting non-existent version."""
        fake_id = "00000000-0000-0000-0000-000000000001"
        response = client.delete(f"/api/v1/template-versions/{fake_id}")
        
        assert response.status_code == status.HTTP_404_NOT_FOUND
