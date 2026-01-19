"""Tests for deployment listing endpoint."""
from unittest.mock import patch, MagicMock
import pytest
from uuid import uuid4
from fastapi.testclient import TestClient
from src.main import app
from src.core.dependencies import get_current_user
from src.models.user import UserRole


def mock_lecturer_user():
    """Mock authenticated user with LECTURER role."""
    return {
        "sub": "lecturer-123",
        "email": "lecturer@example.com",
        "name": "Test Lecturer",
        "preferred_username": "lecturer",
        "roles": [UserRole.LECTURER.value],
        "user_id": 1,
    }


def mock_admin_user():
    """Mock authenticated user with ADMIN role."""
    return {
        "sub": "admin-123",
        "email": "admin@example.com",
        "name": "Test Admin",
        "preferred_username": "admin",
        "roles": [UserRole.ADMIN.value],
        "user_id": 2,
    }


client = TestClient(app)


@pytest.fixture
def mock_stacks():
    """Mock OpenStack stacks data."""
    course_id_1 = str(uuid4())
    course_id_2 = str(uuid4())
    
    return [
        {
            "stack_id": "stack-1",
            "stack_name": "test-stack-1",
            "status": "CREATE_COMPLETE",
            "creation_time": "2024-11-27T10:00:00",
            "deployment_id": "deploy-1",
            "course_id": course_id_1,
            "deployment_mode": "per_course",
            "deployment_status": "active",
            "owner_user_id": 1,
            "openstack_project_id": "project-1",
            "openstack_project_name": "Test Project",
            "resources": [],
            "outputs": {},
        },
        {
            "stack_id": "stack-2",
            "stack_name": "test-stack-2",
            "status": "CREATE_IN_PROGRESS",
            "creation_time": "2024-11-27T11:00:00",
            "deployment_id": "deploy-2",
            "course_id": course_id_2,
            "deployment_mode": "per_group",
            "deployment_status": "deploying",
            "owner_user_id": 1,
            "openstack_project_id": "project-1",
            "openstack_project_name": "Test Project",
            "resources": [],
            "outputs": {},
        },
        {
            "stack_id": "stack-3",
            "stack_name": "test-stack-3",
            "status": "DELETE_COMPLETE",
            "creation_time": "2024-11-27T09:00:00",
            "deployment_id": "deploy-3",
            "course_id": course_id_1,
            "deployment_mode": "per_student",
            "deployment_status": "deleted",
            "owner_user_id": 2,
            "openstack_project_id": "project-2",
            "openstack_project_name": "Other Project",
            "resources": [],
            "outputs": {},
        },
    ], course_id_1, course_id_2


@patch("src.api.deployments.DeploymentService")
def test_list_deployments_as_lecturer(mock_service_class, mock_stacks):
    """Test listing deployments as LECTURER (should see only own stacks)."""
    app.dependency_overrides[get_current_user] = mock_lecturer_user
    
    stacks, course_id_1, course_id_2 = mock_stacks
    # Mock service to return only lecturer's stacks
    lecturer_stacks = [s for s in stacks if s["owner_user_id"] == 1]
    mock_service_instance = MagicMock()
    mock_service_instance.list_all_openstack_stacks.return_value = lecturer_stacks
    mock_service_class.return_value = mock_service_instance
    
    response = client.get("/api/v1/deployments")
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["pagination"]["total_items"] == 2
    assert len(data["data"]) == 2
    
    # Verify service was called with lecturer's user_id
    mock_service_instance.list_all_openstack_stacks.assert_called_once_with(user_id=1)
    
    app.dependency_overrides.clear()


@patch("src.api.deployments.DeploymentService")
def test_list_deployments_as_admin(mock_service_class, mock_stacks):
    """Test listing deployments as ADMIN (should see all stacks)."""
    app.dependency_overrides[get_current_user] = mock_admin_user
    
    stacks, course_id_1, course_id_2 = mock_stacks
    # Mock service to return all stacks
    mock_service_instance = MagicMock()
    mock_service_instance.list_all_openstack_stacks.return_value = stacks
    mock_service_class.return_value = mock_service_instance
    
    response = client.get("/api/v1/deployments")
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["pagination"]["total_items"] == 3
    assert len(data["data"]) == 3
    
    # Verify service was called with user_id=None (admin mode)
    mock_service_instance.list_all_openstack_stacks.assert_called_once_with(user_id=None)
    
    app.dependency_overrides.clear()


@patch("src.api.deployments.DeploymentService")
def test_list_deployments_filter_by_course(mock_service_class, mock_stacks):
    """Test filtering deployments by course_id."""
    app.dependency_overrides[get_current_user] = mock_lecturer_user
    
    stacks, course_id_1, course_id_2 = mock_stacks
    mock_service_instance = MagicMock()
    lecturer_stacks = [s for s in stacks if s["owner_user_id"] == 1]
    mock_service_instance.list_all_openstack_stacks.return_value = lecturer_stacks
    mock_service_class.return_value = mock_service_instance
    
    response = client.get(f"/api/v1/deployments?course_id={course_id_1}")
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["pagination"]["total_items"] == 1
    assert data["data"][0]["course_id"] == course_id_1
    
    app.dependency_overrides.clear()


@patch("src.api.deployments.DeploymentService")
def test_list_deployments_filter_by_status(mock_service_class, mock_stacks):
    """Test filtering deployments by status."""
    app.dependency_overrides[get_current_user] = mock_lecturer_user
    
    stacks, course_id_1, course_id_2 = mock_stacks
    mock_service_instance = MagicMock()
    lecturer_stacks = [s for s in stacks if s["owner_user_id"] == 1]
    mock_service_instance.list_all_openstack_stacks.return_value = lecturer_stacks
    mock_service_class.return_value = mock_service_instance
    
    response = client.get("/api/v1/deployments?status=CREATE_COMPLETE")
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["pagination"]["total_items"] == 1
    assert data["data"][0]["status"] == "CREATE_COMPLETE"
    
    app.dependency_overrides.clear()


@patch("src.api.deployments.DeploymentService")
def test_list_deployments_pagination(mock_service_class, mock_stacks):
    """Test pagination of deployment list."""
    app.dependency_overrides[get_current_user] = mock_lecturer_user
    
    stacks, course_id_1, course_id_2 = mock_stacks
    mock_service_instance = MagicMock()
    lecturer_stacks = [s for s in stacks if s["owner_user_id"] == 1]
    mock_service_instance.list_all_openstack_stacks.return_value = lecturer_stacks
    mock_service_class.return_value = mock_service_instance
    
    # Request first page with page_size=1
    response = client.get("/api/v1/deployments?page=1&page_size=1")
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["pagination"]["page"] == 1
    assert data["pagination"]["page_size"] == 1
    assert data["pagination"]["total_items"] == 2
    assert len(data["data"]) == 1
    
    app.dependency_overrides.clear()


@patch("src.api.deployments.DeploymentService")
def test_list_deployments_combined_filters(mock_service_class, mock_stacks):
    """Test combining multiple filters."""
    app.dependency_overrides[get_current_user] = mock_lecturer_user
    
    stacks, course_id_1, course_id_2 = mock_stacks
    mock_service_instance = MagicMock()
    lecturer_stacks = [s for s in stacks if s["owner_user_id"] == 1]
    mock_service_instance.list_all_openstack_stacks.return_value = lecturer_stacks
    mock_service_class.return_value = mock_service_instance
    
    response = client.get(f"/api/v1/deployments?course_id={course_id_1}&status=CREATE_COMPLETE")
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["pagination"]["total_items"] == 1
    assert data["data"][0]["course_id"] == course_id_1
    assert data["data"][0]["status"] == "CREATE_COMPLETE"
    
    app.dependency_overrides.clear()


@patch("src.api.deployments.DeploymentService")
def test_list_deployments_no_results(mock_service_class):
    """Test empty result when no deployments match filters."""
    app.dependency_overrides[get_current_user] = mock_lecturer_user
    
    mock_service_instance = MagicMock()
    mock_service_instance.list_all_openstack_stacks.return_value = []
    mock_service_class.return_value = mock_service_instance
    
    response = client.get("/api/v1/deployments")
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["pagination"]["total_items"] == 0
    assert len(data["data"]) == 0
    
    app.dependency_overrides.clear()


@patch("src.api.deployments.DeploymentService")
def test_list_deployments_filter_by_template_id(mock_service_class, mock_stacks):
    """Test filtering deployments by template_id."""
    app.dependency_overrides[get_current_user] = mock_lecturer_user
    
    stacks, course_id_1, course_id_2 = mock_stacks
    template_id = uuid4()
    
    # Mock deployment with template_version relationship
    mock_deployment = MagicMock()
    mock_deployment.id = "deploy-1"
    mock_deployment.template_version = MagicMock()
    mock_deployment.template_version.template_id = template_id
    
    mock_service_instance = MagicMock()
    lecturer_stacks = [s for s in stacks if s["owner_user_id"] == 1]
    mock_service_instance.list_all_openstack_stacks.return_value = lecturer_stacks
    mock_service_instance.deployment_repo.get_by_id.return_value = mock_deployment
    mock_service_class.return_value = mock_service_instance
    
    response = client.get(f"/api/v1/deployments?template_id={template_id}")
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    # Should only return stacks matching the template_id
    assert all(s["deployment_id"] == "deploy-1" for s in data["data"])
    
    app.dependency_overrides.clear()
