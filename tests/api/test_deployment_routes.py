"""Tests for deployment listing endpoint."""
from unittest.mock import patch, MagicMock
import pytest
from uuid import uuid4
from fastapi.testclient import TestClient
from src.main import app
from src.core.dependencies import get_current_user
from src.models.user import UserRole
from src.models.deployment import DeploymentStatus


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


@patch("src.api.deployments.DeploymentRepository")
def test_get_deployment_as_owner(mock_repo_class):
    """Test retrieving a single deployment as the owner (lecturer)."""
    app.dependency_overrides[get_current_user] = mock_lecturer_user
    
    # Mock deployment with related objects
    mock_deployment = MagicMock()
    mock_deployment.id = "deploy-123"
    mock_deployment.name = "Test Deployment"
    mock_deployment.template_version_id = "version-456"
    mock_deployment.course_id = "course-789"
    mock_deployment.deployment_mode = "per_course"
    mock_deployment.status = "active"
    mock_deployment.openstack_stack_id = "stack-abc"
    mock_deployment.config_json = '{"cpu": 2}'
    mock_deployment.access_types_json = '["ssh", "web_url"]'
    mock_deployment.created_at = "2024-11-27T10:00:00"
    mock_deployment.updated_at = "2024-11-27T10:00:00"
    
    # Mock course (owner check)
    mock_deployment.course = MagicMock()
    mock_deployment.course.id = "course-789"
    mock_deployment.course.name = "Test Course"
    mock_deployment.course.lecturer_id = 1  # Same as mock_lecturer_user
    
    # Mock template version
    mock_deployment.template_version = MagicMock()
    mock_deployment.template_version.id = "version-456"
    mock_deployment.template_version.version = "1.0"
    mock_deployment.template_version.template_id = "template-abc"
    mock_deployment.template_version.template = MagicMock()
    mock_deployment.template_version.template.name = "Test Template"
    
    # Mock instances
    mock_instance = MagicMock()
    mock_instance.id = "instance-123"
    mock_instance.instance_name = "vm-1"
    mock_instance.openstack_instance_id = "os-instance-456"
    mock_instance.status = MagicMock()
    mock_instance.status.value = "ACTIVE"
    mock_instance.ip_address = "192.168.1.10"
    mock_instance.access_urls_json = '{"ssh": "ssh://192.168.1.10"}'
    mock_instance.created_at = "2024-11-27T10:00:00"
    mock_instance.updated_at = "2024-11-27T10:00:00"
    mock_deployment.instances = [mock_instance]
    
    mock_repo_instance = MagicMock()
    mock_repo_instance.get_by_id.return_value = mock_deployment
    mock_repo_class.return_value = mock_repo_instance
    
    response = client.get("/api/v1/deployments/deploy-123")
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["id"] == "deploy-123"
    assert data["data"]["template_version"]["id"] == "version-456"
    assert data["data"]["course"]["name"] == "Test Course"
    assert len(data["data"]["instances"]) == 1
    assert data["data"]["instances"][0]["instance_name"] == "vm-1"
    
    app.dependency_overrides.clear()


@patch("src.api.deployments.DeploymentRepository")
def test_get_deployment_as_admin(mock_repo_class):
    """Test retrieving a single deployment as ADMIN (can access any deployment)."""
    app.dependency_overrides[get_current_user] = mock_admin_user
    
    # Mock deployment owned by another user
    mock_deployment = MagicMock()
    mock_deployment.id = "deploy-123"
    mock_deployment.name = "Admin Test Deployment"
    mock_deployment.template_version_id = "version-456"
    mock_deployment.course_id = "course-789"
    mock_deployment.deployment_mode = "per_course"
    mock_deployment.status = "active"
    mock_deployment.openstack_stack_id = "stack-abc"
    mock_deployment.config_json = '{"cpu": 2}'
    mock_deployment.access_types_json = '["ssh"]'
    mock_deployment.created_at = "2024-11-27T10:00:00"
    mock_deployment.updated_at = "2024-11-27T10:00:00"
    
    # Mock course (different owner)
    mock_deployment.course = MagicMock()
    mock_deployment.course.id = "course-789"
    mock_deployment.course.name = "Other Course"
    mock_deployment.course.lecturer_id = 999  # Different from admin user_id
    
    # Mock template version
    mock_deployment.template_version = MagicMock()
    mock_deployment.template_version.id = "version-456"
    mock_deployment.template_version.version = "1.0"
    mock_deployment.template_version.template_id = "template-abc"
    mock_deployment.template_version.template = MagicMock()
    mock_deployment.template_version.template.name = "Test Template"
    
    mock_deployment.instances = []
    
    mock_repo_instance = MagicMock()
    mock_repo_instance.get_by_id.return_value = mock_deployment
    mock_repo_class.return_value = mock_repo_instance
    
    response = client.get("/api/v1/deployments/deploy-123")
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["id"] == "deploy-123"
    
    app.dependency_overrides.clear()


@patch("src.api.deployments.DeploymentRepository")
def test_get_deployment_not_found(mock_repo_class):
    """Test retrieving a non-existent deployment."""
    app.dependency_overrides[get_current_user] = mock_lecturer_user
    
    mock_repo_instance = MagicMock()
    mock_repo_instance.get_by_id.return_value = None
    mock_repo_class.return_value = mock_repo_instance
    
    response = client.get("/api/v1/deployments/nonexistent-id")
    
    assert response.status_code == 404
    data = response.json()
    assert data["success"] is False
    assert "not found" in data["message"].lower()
    
    app.dependency_overrides.clear()


@patch("src.api.deployments.DeploymentRepository")
def test_get_deployment_forbidden(mock_repo_class):
    """Test retrieving another lecturer's deployment (should be forbidden)."""
    app.dependency_overrides[get_current_user] = mock_lecturer_user
    
    # Mock deployment owned by another lecturer
    mock_deployment = MagicMock()
    mock_deployment.id = "deploy-123"
    mock_deployment.course = MagicMock()
    mock_deployment.course.lecturer_id = 999  # Different from mock_lecturer_user.user_id (1)
    
    mock_repo_instance = MagicMock()
    mock_repo_instance.get_by_id.return_value = mock_deployment
    mock_repo_class.return_value = mock_repo_instance
    
    response = client.get("/api/v1/deployments/deploy-123")
    
    assert response.status_code == 403
    data = response.json()
    assert data["success"] is False
    assert "permission" in data["message"].lower()
    
    app.dependency_overrides.clear()


@patch("src.api.deployments.restart_deployment_task")
@patch("src.api.deployments.DeploymentLogService")
@patch("src.api.deployments.DeploymentRepository")
def test_restart_deployment_success(mock_repo_class, mock_log_service_class, mock_restart_task):
    """Test successful deployment restart request."""
    app.dependency_overrides[get_current_user] = mock_lecturer_user
    
    # Mock deployment in RUNNING state
    mock_deployment = MagicMock()
    mock_deployment.id = "deploy-123"
    mock_deployment.status = DeploymentStatus.RUNNING
    mock_deployment.openstack_stack_id = "stack-abc"
    mock_deployment.course = MagicMock()
    mock_deployment.course.lecturer_id = 1  # Same as mock_lecturer_user
    
    mock_repo_instance = MagicMock()
    mock_repo_instance.get_by_id.return_value = mock_deployment
    mock_repo_class.return_value = mock_repo_instance
    
    response = client.post("/api/v1/deployments/deploy-123/restart")
    
    assert response.status_code == 202
    data = response.json()
    assert data["success"] is True
    assert data["data"]["status"] == "restart_queued"
    
    # Verify task was enqueued
    mock_restart_task.delay.assert_called_once_with("deploy-123")
    
    app.dependency_overrides.clear()


@patch("src.api.deployments.DeploymentRepository")
def test_restart_deployment_not_found(mock_repo_class):
    """Test restarting a non-existent deployment."""
    app.dependency_overrides[get_current_user] = mock_lecturer_user
    
    mock_repo_instance = MagicMock()
    mock_repo_instance.get_by_id.return_value = None
    mock_repo_class.return_value = mock_repo_instance
    
    response = client.post("/api/v1/deployments/nonexistent-id/restart")
    
    assert response.status_code == 404
    data = response.json()
    assert data["success"] is False
    assert "not found" in data["message"].lower()
    
    app.dependency_overrides.clear()


@patch("src.api.deployments.DeploymentRepository")
def test_restart_deployment_forbidden(mock_repo_class):
    """Test restarting another lecturer's deployment (should be forbidden)."""
    app.dependency_overrides[get_current_user] = mock_lecturer_user
    
    # Mock deployment owned by another lecturer
    mock_deployment = MagicMock()
    mock_deployment.id = "deploy-123"
    mock_deployment.status = DeploymentStatus.RUNNING
    mock_deployment.course = MagicMock()
    mock_deployment.course.lecturer_id = 999  # Different from mock_lecturer_user
    
    mock_repo_instance = MagicMock()
    mock_repo_instance.get_by_id.return_value = mock_deployment
    mock_repo_class.return_value = mock_repo_instance
    
    response = client.post("/api/v1/deployments/deploy-123/restart")
    
    assert response.status_code == 403
    data = response.json()
    assert data["success"] is False
    assert "permission" in data["message"].lower()
    
    app.dependency_overrides.clear()


@patch("src.api.deployments.DeploymentRepository")
def test_restart_deployment_in_transitional_state(mock_repo_class):
    """Test restarting a deployment that is already in a transitional state."""
    app.dependency_overrides[get_current_user] = mock_lecturer_user
    
    # Mock deployment in CREATING state
    mock_deployment = MagicMock()
    mock_deployment.id = "deploy-123"
    mock_deployment.status = DeploymentStatus.CREATING
    mock_deployment.course = MagicMock()
    mock_deployment.course.lecturer_id = 1
    
    mock_repo_instance = MagicMock()
    mock_repo_instance.get_by_id.return_value = mock_deployment
    mock_repo_class.return_value = mock_repo_instance
    
    response = client.post("/api/v1/deployments/deploy-123/restart")
    
    assert response.status_code == 400
    data = response.json()
    assert data["success"] is False
    assert "creating" in data["message"].lower()
    
    app.dependency_overrides.clear()


@patch("src.api.deployments.DeploymentRepository")
def test_restart_deployment_without_stack(mock_repo_class):
    """Test restarting a deployment that has no OpenStack stack."""
    app.dependency_overrides[get_current_user] = mock_lecturer_user
    
    # Mock deployment without stack_id
    mock_deployment = MagicMock()
    mock_deployment.id = "deploy-123"
    mock_deployment.status = DeploymentStatus.FAILED
    mock_deployment.openstack_stack_id = None
    mock_deployment.course = MagicMock()
    mock_deployment.course.lecturer_id = 1
    
    mock_repo_instance = MagicMock()
    mock_repo_instance.get_by_id.return_value = mock_deployment
    mock_repo_class.return_value = mock_repo_instance
    
    response = client.post("/api/v1/deployments/deploy-123/restart")
    
    assert response.status_code == 400
    data = response.json()
    assert data["success"] is False
    assert "no associated openstack stack" in data["message"].lower()
    
    app.dependency_overrides.clear()


@patch("src.api.deployments.restart_deployment_task")
@patch("src.api.deployments.DeploymentLogService")
@patch("src.api.deployments.DeploymentRepository")
def test_restart_deployment_task_enqueue_failure(mock_repo_class, mock_log_service_class, mock_restart_task):
    """Test handling of Celery task enqueue failure."""
    app.dependency_overrides[get_current_user] = mock_lecturer_user
    
    # Mock deployment
    mock_deployment = MagicMock()
    mock_deployment.id = "deploy-123"
    mock_deployment.status = DeploymentStatus.RUNNING
    mock_deployment.openstack_stack_id = "stack-abc"
    mock_deployment.course = MagicMock()
    mock_deployment.course.lecturer_id = 1
    
    mock_repo_instance = MagicMock()
    mock_repo_instance.get_by_id.return_value = mock_deployment
    mock_repo_class.return_value = mock_repo_instance
    
    mock_log_instance = MagicMock()
    mock_log_service_class.return_value = mock_log_instance
    
    # Simulate task enqueue failure
    mock_restart_task.delay.side_effect = Exception("Redis connection failed")
    
    response = client.post("/api/v1/deployments/deploy-123/restart")
    
    assert response.status_code == 500
    data = response.json()
    assert data["success"] is False
    assert "enqueue" in data["message"].lower()
    
    app.dependency_overrides.clear()
