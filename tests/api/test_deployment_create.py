"""Tests for deployment creation endpoint."""
from unittest.mock import patch
from datetime import datetime
import pytest
from fastapi.testclient import TestClient
from src.main import app
from src.core.dependencies import get_current_user
from src.models.user import UserRole


# Local DB id of the active OpenstackProject — required field on every create
# payload since the FK was added. Tests pass a fixed UUID; the service is
# fully mocked so the value just needs to satisfy the schema.
TEST_OS_PROJECT_ID = "11111111-1111-1111-1111-111111111111"


def mock_authenticated_user():
    """Mock authenticated user with LECTURER role."""
    return {
        "sub": "test-user-123",
        "email": "test@example.com",
        "name": "Test User",
        "preferred_username": "testuser",
        "roles": [UserRole.LECTURER.value],
        "user_id": 1,
    }


# Override the get_current_user dependency to skip authentication in tests
app.dependency_overrides[get_current_user] = mock_authenticated_user

client = TestClient(app)


class MockDeployment:
    """Simple mock deployment object with proper attributes for Pydantic validation."""
    def __init__(self, deployment_parameters=None):
        self.id = "test-deployment-123"
        self.name = "Test Deployment"
        self.template_version_id = "version-123"
        self.course_id = "course-456"
        self.deployment_mode = "per_course"
        self.status = "queued"
        self.openstack_stack_id = None
        self.config_json = '{"cpu": 2, "ram": 4096}'
        self.deployment_parameters = deployment_parameters
        self.access_types_json = '["ssh"]'
        self.created_at = datetime(2024, 11, 27, 10, 0, 0)
        self.updated_at = datetime(2024, 11, 27, 10, 0, 0)


@pytest.fixture
def mock_deployment():
    """Mock deployment object."""
    return MockDeployment()


@patch("src.api.deployments.DeploymentService")
def test_create_deployment_success(mock_service_class, mock_deployment):
    """Test successful deployment creation."""
    # Re-apply override per-test: other test modules call dependency_overrides.clear()
    # in their cleanup, which would otherwise leave us 401-unauthenticated.
    app.dependency_overrides[get_current_user] = mock_authenticated_user
    # Configure the service instance to return the mock deployment
    mock_service_class.return_value.create_deployment.return_value = mock_deployment
    
    # Test data with new schema
    payload = {
        "name": "Test Deployment",
        "template_version_id": "version-123",
        "course_id": "course-456",
        "openstack_project_id": TEST_OS_PROJECT_ID,
        "heat_parameters": {
            "image": "Ubuntu 22.04",
            "flavor": "gp1.small",
            "network": "NAT"
        },
        "stack_assignments": [
            {
                "stack_index": 1,
                "groups": [
                    {
                        "group_name": "Group 1",
                        "group_index": 1,
                        "students": [
                            {
                                "id": "student-123",
                                "username": "student1",
                                "email": "student1@example.com",
                                "first_name": "Test",
                                "last_name": "Student"
                            }
                        ]
                    }
                ]
            }
        ],
        "teacher": {
            "id": "test-user-123",
            "username": "testuser",
            "email": "test@example.com",
            "first_name": "Test",
            "last_name": "User"
        }
    }
    
    # Make request
    response = client.post("/api/v1/deployments", json=payload)
    
    # Assertions
    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
    assert data["message"] == "Deployment created and queued for processing"
    assert data["data"]["id"] == "test-deployment-123"
    assert data["data"]["status"] == "queued"
    
    # Verify service method was called
    mock_service_class.return_value.create_deployment.assert_called_once()


@patch("src.api.deployments.DeploymentService")
def test_create_deployment_with_heat_parameters(mock_service_class, mock_deployment):
    """Test deployment creation with Heat template parameters."""
    app.dependency_overrides[get_current_user] = mock_authenticated_user
    # Configure deployment with heat parameters
    heat_params_json = '{"instance_name": "test-vm", "flavor": "gp1.small", "db_password": "secret123"}'
    mock_deployment_with_params = MockDeployment(deployment_parameters=heat_params_json)
    mock_service_class.return_value.create_deployment.return_value = mock_deployment_with_params
    
    # Test data with heat_parameters
    payload = {
        "name": "Database Deployment",
        "template_version_id": "version-123",
        "course_id": "course-456",
        "openstack_project_id": TEST_OS_PROJECT_ID,
        "heat_parameters": {
            "instance_name": "test-vm",
            "flavor": "gp1.small",
            "db_password": "secret123"
        },
        "stack_assignments": [
            {
                "stack_index": 1,
                "groups": [
                    {
                        "group_name": "Group A",
                        "group_index": 1,
                        "students": []
                    }
                ]
            }
        ],
        "teacher": {
            "id": "test-user-123",
            "username": "testuser",
            "email": "test@example.com",
            "first_name": "Test",
            "last_name": "User"
        },
        "access_types": ["ssh", "web"]
    }
    
    # Make request
    response = client.post("/api/v1/deployments", json=payload)
    
    # Assertions
    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
    assert data["data"]["deployment_parameters"] == heat_params_json
    
    # Verify service was called with heat_parameters
    mock_service_class.return_value.create_deployment.assert_called_once()


@patch("src.api.deployments.DeploymentService")
def test_create_deployment_with_both_config_and_parameters(mock_service_class, mock_deployment):
    """Test deployment with required fields."""
    app.dependency_overrides[get_current_user] = mock_authenticated_user
    heat_params_json = '{"instance_name": "vm1"}'
    mock_deployment_with_params = MockDeployment(deployment_parameters=heat_params_json)
    mock_service_class.return_value.create_deployment.return_value = mock_deployment_with_params
    
    # Payload with all required fields
    payload = {
        "name": "VM Deployment",
        "template_version_id": "version-123",
        "course_id": "course-456",
        "openstack_project_id": TEST_OS_PROJECT_ID,
        "heat_parameters": {
            "instance_name": "vm1"
        },
        "stack_assignments": [
            {
                "stack_index": 1,
                "groups": [
                    {
                        "group_name": "Group 1",
                        "group_index": 1,
                        "students": []
                    }
                ]
            }
        ],
        "teacher": {
            "id": "test-user-123",
            "username": "testuser",
            "email": "test@example.com",
            "first_name": "Test",
            "last_name": "User"
        }
    }
    
    # Make request
    response = client.post("/api/v1/deployments", json=payload)
    
    # Should succeed
    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
    assert data["data"]["deployment_parameters"] == heat_params_json


@patch("src.api.deployments.DeploymentService")
def test_create_deployment_without_parameters(mock_service_class, mock_deployment):
    """Test deployment creation fails without required fields."""
    app.dependency_overrides[get_current_user] = mock_authenticated_user
    minimal_deployment = MockDeployment(deployment_parameters=None)
    mock_service_class.return_value.create_deployment.return_value = minimal_deployment
    
    # Minimal payload without required fields (should fail validation)
    payload = {
        "template_version_id": "version-123",
        "course_id": "course-456"
    }
    
    # Make request
    response = client.post("/api/v1/deployments", json=payload)
    
    # Should fail with 422 Unprocessable Entity (validation error)
    assert response.status_code == 422
