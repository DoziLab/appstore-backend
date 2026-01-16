"""Tests for OpenStack Resources API endpoints."""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.main import app
from src.core.database import Base
from src.core.dependencies import get_db, get_current_user
from src.models.openstack_project import OpenstackProject
from src.models.user import User
from src.core.exceptions import NotFoundException, ForbiddenException


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
    import src.models.deployment  # noqa
    import src.models.deployment_instance  # noqa
    import src.models.deployment_instance_access  # noqa
    import src.models.deployment_log  # noqa
    import src.models.template_category  # noqa
    import src.models.template_category_assignment  # noqa
    import src.models.template_version  # noqa
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
def client(db_session):
    """Create test client with overridden database dependency."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    
    def override_get_current_user():
        """Mock authenticated user for tests."""
        return {
            "sub": "user-123",
            "email": "test@example.com",
            "name": "Test User",
            "preferred_username": "testuser",
            "roles": ["lecturer"],
            "user_id": "user-123",
        }
    
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def mock_openstack_project():
    """Create a mock OpenStack project."""
    project = MagicMock(spec=OpenstackProject)
    project.id = "project-123"
    project.owner_user_id = "user-123"
    project.openstack_project_id = "openstack-proj-123"
    project.openstack_project_name = "test-project"
    project.auth_url = "https://openstack.example.com:5000"
    project.username = "testuser"
    project.password = "testpass"
    project.user_domain_name = "Default"
    project.region_name = "RegionOne"
    return project


class TestGetQuotas:
    """Tests for GET /api/v1/quotas endpoint."""
    
    def test_get_quotas_success(self, client, db_session):
        """Test successful quota retrieval."""
        quotas_data = {
            'project_id': 'openstack-proj-123',
            'project_name': 'test-project',
            'owner_user_id': 'user-123',
            'compute': {
                'instances': {'limit': 10, 'used': 3, 'available': 7},
                'cores': {'limit': 20, 'used': 5, 'available': 15},
                'ram': {'limit': 40960, 'used': 10240, 'available': 30720}
            },
            'volume': {
                'volumes': {'limit': 10, 'used': 2, 'available': 8},
                'gigabytes': {'limit': 1000, 'used': 200, 'available': 800}
            },
            'network': {
                'floatingip': {'limit': 5, 'used': 2, 'available': 3}
            },
            'fetched_at': '2024-01-01T00:00:00Z'
        }
        
        with patch('src.api.quotas.OpenstackResourceService') as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.get_quotas.return_value = quotas_data
            
            response = client.get("/api/v1/quotas")
            
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["data"]["project_id"] == "openstack-proj-123"
            assert data["data"]["project_name"] == "test-project"
    
    def test_get_quotas_force_refresh(self, client, db_session):
        """Test quota retrieval with force_refresh parameter."""
        quotas_data = {
            'project_id': 'openstack-proj-123',
            'project_name': 'test-project',
            'owner_user_id': 'user-123',
            'compute': {'instances': {'limit': 10, 'used': 5, 'available': 5}},
            'volume': None,
            'network': None,
            'fetched_at': '2024-01-01T00:00:00Z'
        }
        
        with patch('src.api.quotas.OpenstackResourceService') as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.get_quotas.return_value = quotas_data
            
            response = client.get("/api/v1/quotas?force_refresh=true")
            
            assert response.status_code == 200
            mock_service.get_quotas.assert_called_once()
            # Verify force_refresh was passed
            call_args = mock_service.get_quotas.call_args
            assert call_args[1].get('force_refresh') is True
    
    def test_get_quotas_no_project_found(self, client, db_session):
        """Test quota retrieval when no project is found."""
        with patch('src.api.quotas.OpenstackResourceService') as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.get_quotas.side_effect = NotFoundException("No OpenStack project found")
            
            response = client.get("/api/v1/quotas")
            
            assert response.status_code == 404
    
    def test_get_quotas_admin_access_other_project(self, client, db_session):
        """Test that admins can access other users' quotas."""
        quotas_data = {
            'project_id': 'openstack-proj-456',
            'project_name': 'other-project',
            'owner_user_id': 'user-456',
            'compute': {'instances': {'limit': 10, 'used': 3, 'available': 7}},
            'volume': None,
            'network': None,
            'fetched_at': '2024-01-01T00:00:00Z'
        }
        
        # Mock admin user
        def override_get_current_user_admin():
            return {
                "sub": "admin-123",
                "email": "admin@example.com",
                "name": "Admin User",
                "preferred_username": "admin",
                "roles": ["admin"],
                "user_id": "admin-123",
            }
        
        app.dependency_overrides[get_current_user] = override_get_current_user_admin
        
        try:
            with patch('src.api.quotas.OpenstackResourceService') as mock_service_class:
                mock_service = mock_service_class.return_value
                mock_service.get_quotas.return_value = quotas_data
                
                # Use a valid UUID format for project_id
                response = client.get("/api/v1/quotas?project_id=12345678-1234-1234-1234-123456789012")
                
                assert response.status_code == 200
                data = response.json()
                assert data["data"]["project_id"] == "openstack-proj-456"
        finally:
            app.dependency_overrides.clear()


class TestCheckAvailabilityService:
    """Tests for check_availability service method (used internally)."""
    
    def test_check_availability_service_success(self, client, db_session):
        """Test that check_availability service method works correctly."""
        from src.services.openstack_resource_service import OpenstackResourceService
        
        quotas_data = {
            'project_id': 'openstack-proj-123',
            'project_name': 'test-project',
            'compute': {
                'instances': {'limit': 10, 'used': 3, 'available': 7},
                'cores': {'limit': 20, 'used': 5, 'available': 15},
                'ram': {'limit': 40960, 'used': 10240, 'available': 30720}
            },
            'volume': {
                'volumes': {'limit': 10, 'used': 2, 'available': 8},
                'gigabytes': {'limit': 1000, 'used': 200, 'available': 800}
            }
        }
        
        required_resources = {
            'instances': 2,
            'cores': 4,
            'ram': 8192
        }
        
        service = OpenstackResourceService(db_session)
        
        with patch.object(service, 'get_quotas', return_value=quotas_data):
            result = service.check_availability(
                user_id="user-123",
                required_resources=required_resources
            )
            
            assert result['available'] is True
            assert len(result['reasons']) == 0
            assert result['quotas'] == quotas_data
    
    def test_check_availability_service_insufficient(self, client, db_session):
        """Test check_availability with insufficient resources."""
        from src.services.openstack_resource_service import OpenstackResourceService
        
        quotas_data = {
            'project_id': 'openstack-proj-123',
            'project_name': 'test-project',
            'compute': {
                'instances': {'limit': 10, 'used': 9, 'available': 1},
                'cores': {'limit': 20, 'used': 18, 'available': 2},
                'ram': {'limit': 40960, 'used': 35000, 'available': 5960}
            }
        }
        
        required_resources = {
            'instances': 3,  # Need 3, only 1 available
            'cores': 5,      # Need 5, only 2 available
            'ram': 8192      # Need 8192 MB, only 5960 MB available
        }
        
        service = OpenstackResourceService(db_session)
        
        with patch.object(service, 'get_quotas', return_value=quotas_data):
            result = service.check_availability(
                user_id="user-123",
                required_resources=required_resources
            )
            
            assert result['available'] is False
            assert len(result['reasons']) == 3
            assert any("instances" in reason for reason in result['reasons'])
            assert any("CPU cores" in reason for reason in result['reasons'])
            assert any("RAM" in reason for reason in result['reasons'])
