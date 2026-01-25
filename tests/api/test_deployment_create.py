"""Tests for deployment creation endpoint."""
from unittest.mock import patch
from datetime import datetime
import pytest
from fastapi.testclient import TestClient
from src.main import app
from src.core.dependencies import get_current_user
from src.models.user import UserRole


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
    # Configure the service instance to return the mock deployment
    mock_service_class.return_value.create_deployment.return_value = mock_deployment
    
    # Test data
    payload = {
        "name": "Test Deployment",
        "template_version_id": "version-123",
        "course_id": "course-456",
        "deployment_mode": "per_course",
        "config_json": '{"cpu": 2, "ram": 4096}',
        "access_types": ["ssh"]
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
    # Configure deployment with heat parameters
    heat_params_json = '{"instance_name": "test-vm", "flavor": "gp1.small", "db_password": "secret123"}'
    mock_deployment_with_params = MockDeployment(deployment_parameters=heat_params_json)
    mock_service_class.return_value.create_deployment.return_value = mock_deployment_with_params
    
    # Test data with heat_parameters
    payload = {
        "template_version_id": "version-123",
        "course_id": "course-456",
        "deployment_mode": "per_group",
        "heat_parameters": {
            "instance_name": "test-vm",
            "flavor": "gp1.small",
            "db_password": "secret123"
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
    """Test deployment with both config_json (legacy) and heat_parameters."""
    heat_params_json = '{"instance_name": "vm1"}'
    mock_deployment_with_params = MockDeployment(deployment_parameters=heat_params_json)
    mock_service_class.return_value.create_deployment.return_value = mock_deployment_with_params
    
    # Both config_json and heat_parameters provided
    payload = {
        "template_version_id": "version-123",
        "course_id": "course-456",
        "deployment_mode": "per_course",
        "config_json": '{"cpu": 4}',
        "heat_parameters": {
            "instance_name": "vm1"
        },
        "access_types": ["ssh"]
    }
    
    # Make request
    response = client.post("/api/v1/deployments", json=payload)
    
    # Should succeed - heat_parameters takes priority in deployment task
    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
    assert data["data"]["deployment_parameters"] == heat_params_json


@patch("src.api.deployments.DeploymentService")
def test_create_deployment_without_parameters(mock_service_class, mock_deployment):
    """Test deployment creation without heat_parameters (minimal payload)."""
    minimal_deployment = MockDeployment(deployment_parameters=None)
    mock_service_class.return_value.create_deployment.return_value = minimal_deployment
    
    # Minimal payload without parameters
    payload = {
        "template_version_id": "version-123",
        "course_id": "course-456",
        "deployment_mode": "per_course"
    }
    
    # Make request
    response = client.post("/api/v1/deployments", json=payload)
    
    # Should succeed with defaults
    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
    assert data["data"]["deployment_parameters"] is None
