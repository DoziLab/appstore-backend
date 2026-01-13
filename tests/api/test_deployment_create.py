"""Tests for deployment creation endpoint."""
import json
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient
from src.main import app


client = TestClient(app)


@pytest.fixture
def mock_deployment():
    """Mock deployment object."""
    deployment = MagicMock()
    deployment.id = "test-deployment-123"
    deployment.template_version_id = "version-123"
    deployment.course_id = "course-456"
    deployment.deployment_mode = "per_course"
    deployment.status = "queued"
    deployment.openstack_stack_id = None
    deployment.config_json = '{"cpu": 2, "ram": 4096}'
    deployment.access_types_json = '["ssh"]'
    deployment.created_at = "2024-11-27T10:00:00Z"
    deployment.updated_at = "2024-11-27T10:00:00Z"
    return deployment


@patch("src.services.deployment_service.deploy_stack")
@patch("src.services.deployment_service.DeploymentRepository")
def test_create_deployment_success(mock_repo_class, mock_deploy_task, mock_deployment):
    """Test successful deployment creation."""
    # Setup mock repository
    mock_repo = MagicMock()
    mock_repo_class.return_value = mock_repo
    mock_repo.create.return_value = mock_deployment
    
    # Test data
    payload = {
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
    assert data["status"] == "success"
    assert data["data"]["id"] == "test-deployment-123"
    assert data["data"]["status"] == "queued"
    
    # Verify Celery task was triggered
    mock_deploy_task.delay.assert_called_once_with("test-deployment-123")


@patch("src.services.deployment_service.deploy_stack")
@patch("src.services.deployment_service.DeploymentRepository")
def test_create_deployment_per_group_validation(mock_repo_class, mock_deploy_task):
    """Test validation: group_ids required for per_group mode."""
    payload = {
        "template_version_id": "version-123",
        "course_id": "course-456",
        "deployment_mode": "per_group",
        # Missing group_ids - should fail validation
    }
    
    response = client.post("/api/v1/deployments", json=payload)
    
    # Should return 422 Unprocessable Entity for validation error
    assert response.status_code == 422
    assert "group_ids" in str(response.json())


@patch("src.services.deployment_service.deploy_stack")
@patch("src.services.deployment_service.DeploymentRepository")
def test_create_deployment_per_student_validation(mock_repo_class, mock_deploy_task):
    """Test validation: course_member_ids required for per_student mode."""
    payload = {
        "template_version_id": "version-123",
        "course_id": "course-456",
        "deployment_mode": "per_student",
        # Missing course_member_ids - should fail validation
    }
    
    response = client.post("/api/v1/deployments", json=payload)
    
    # Should return 422 Unprocessable Entity for validation error
    assert response.status_code == 422
    assert "course_member_ids" in str(response.json())
