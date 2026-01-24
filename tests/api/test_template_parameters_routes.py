"""Tests for template parameter API endpoints."""
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
from src.models.template_version_file import TemplateVersionFile, FileType
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
        name="PostgreSQL Database Template",
        description="A template for PostgreSQL deployments",
        owner_id=mock_user.id,
        repo_url="https://github.com/example/postgres-template",
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


@pytest.fixture
def valid_app_yaml_content():
    """Valid app.yaml content with parameters."""
    return """
id: postgres-group-db
name: PostgreSQL Group Database
version: 1.0.0
description: "Provisioniert pro Gruppe eine Ubuntu-VM mit PostgreSQL."

parameters:
  instance_name:
    type: string
    required: true
    description: "Eindeutiger Name der Instanz/Stacks (z.B. kursX-grp1-db)."

  flavor:
    type: string
    required: true
    default: "gp1.small"
    description: "OpenStack Flavor."

  db_name:
    type: string
    required: true
    description: "Name der PostgreSQL Datenbank."

  db_password:
    type: string
    required: true
    description: "Passwort für den PostgreSQL User."

  postgres_version:
    type: int
    required: false
    default: 14
    description: "PostgreSQL Major-Version."
"""


@pytest.fixture
def app_yaml_file(db_session, sample_version, valid_app_yaml_content):
    """Create app.yaml file with parameters."""
    file = TemplateVersionFile(
        template_version_id=sample_version.id,
        file_name="app.yaml",
        file_type=FileType.CONFIG_FILE,
        file_path="app.yaml",
        content=valid_app_yaml_content,
        file_size=len(valid_app_yaml_content),
        is_primary=False,
        order=0
    )
    db_session.add(file)
    db_session.commit()
    db_session.refresh(file)
    return file


class TestGetTemplateVersionParameters:
    """Tests for GET /api/v1/template-version-files/version/{version_id}/parameters endpoint."""
    
    def test_get_parameters_success(self, client, sample_version, app_yaml_file):
        """Test successful parameter retrieval."""
        response = client.get(
            f"/api/v1/template-version-files/version/{sample_version.id}/parameters"
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        assert data["success"] is True
        assert "Retrieved 5 template parameters" in data["message"]
        
        # Check response structure
        assert "template_version_id" in data["data"]
        assert "parameters" in data["data"]
        assert data["data"]["template_version_id"] == sample_version.id
        
        # Check parameters
        params = data["data"]["parameters"]
        assert len(params) == 5
        
        # Verify specific parameters
        param_names = [p["name"] for p in params]
        assert "instance_name" in param_names
        assert "flavor" in param_names
        assert "db_name" in param_names
        assert "db_password" in param_names
        assert "postgres_version" in param_names
        
        # Check required parameter
        instance_name = next(p for p in params if p["name"] == "instance_name")
        assert instance_name["type"] == "string"
        assert instance_name["required"] is True
        assert instance_name["default"] is None
        
        # Check parameter with default
        flavor = next(p for p in params if p["name"] == "flavor")
        assert flavor["default"] == "gp1.small"
        assert flavor["required"] is True
        
        # Check optional parameter
        postgres_version = next(p for p in params if p["name"] == "postgres_version")
        assert postgres_version["type"] == "int"
        assert postgres_version["required"] is False
        assert postgres_version["default"] == 14
    
    def test_get_parameters_no_app_yaml(self, client, sample_version):
        """Test error when no app.yaml file exists."""
        response = client.get(
            f"/api/v1/template-version-files/version/{sample_version.id}/parameters"
        )
        
        assert response.status_code == status.HTTP_404_NOT_FOUND
        data = response.json()
        assert "No app.yaml file found" in data["detail"]
    
    def test_get_parameters_invalid_version_id(self, client):
        """Test error with non-existent version ID."""
        fake_version_id = "00000000-0000-0000-0000-000000000099"
        response = client.get(
            f"/api/v1/template-version-files/version/{fake_version_id}/parameters"
        )
        
        assert response.status_code == status.HTTP_404_NOT_FOUND
    
    def test_get_parameters_empty_app_yaml(self, client, db_session, sample_version):
        """Test error when app.yaml has no content."""
        empty_file = TemplateVersionFile(
            template_version_id=sample_version.id,
            file_name="app.yaml",
            file_type=FileType.CONFIG_FILE,
            file_path="app.yaml",
            content=None,
            file_size=0,
            is_primary=False,
            order=0
        )
        db_session.add(empty_file)
        db_session.commit()
        
        response = client.get(
            f"/api/v1/template-version-files/version/{sample_version.id}/parameters"
        )
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        data = response.json()
        assert "has no content" in data["detail"]
    
    def test_get_parameters_invalid_yaml(self, client, db_session, sample_version):
        """Test error when app.yaml contains invalid YAML."""
        invalid_file = TemplateVersionFile(
            template_version_id=sample_version.id,
            file_name="app.yaml",
            file_type=FileType.CONFIG_FILE,
            file_path="app.yaml",
            content="invalid: yaml: [unclosed",
            file_size=100,
            is_primary=False,
            order=0
        )
        db_session.add(invalid_file)
        db_session.commit()
        
        response = client.get(
            f"/api/v1/template-version-files/version/{sample_version.id}/parameters"
        )
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        data = response.json()
        assert "Invalid YAML" in data["detail"]
    
    def test_get_parameters_missing_parameters_section(self, client, db_session, sample_version):
        """Test error when app.yaml is missing parameters section."""
        no_params_content = """
id: test-template
name: Test Template
version: 1.0.0
"""
        no_params_file = TemplateVersionFile(
            template_version_id=sample_version.id,
            file_name="app.yaml",
            file_type=FileType.CONFIG_FILE,
            file_path="app.yaml",
            content=no_params_content,
            file_size=len(no_params_content),
            is_primary=False,
            order=0
        )
        db_session.add(no_params_file)
        db_session.commit()
        
        response = client.get(
            f"/api/v1/template-version-files/version/{sample_version.id}/parameters"
        )
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        data = response.json()
        assert "missing 'parameters' section" in data["detail"]
    
    def test_get_parameters_requires_authentication(self, db_session, sample_version, app_yaml_file):
        """Test that endpoint requires authentication."""
        # Client without auth override
        def override_get_db():
            try:
                yield db_session
            finally:
                pass
        
        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)
        
        response = client.get(
            f"/api/v1/template-version-files/version/{sample_version.id}/parameters"
        )
        
        # Should fail with 401 or 403 due to missing auth
        assert response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]
        
        app.dependency_overrides.clear()
