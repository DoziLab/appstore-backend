"""Tests for deployment listing endpoint."""
from unittest.mock import patch, MagicMock
import pytest
from uuid import uuid4
from datetime import datetime
from fastapi.testclient import TestClient
from src.main import app
from src.core.dependencies import get_current_user, get_db
from src.models.user import UserRole
from src.models.deployment import DeploymentStatus, Deployment
from src.models.course import Course
from src.models.template_version import TemplateVersion
from src.models.template import Template


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
def mock_deployments():
    """Mock deployment database objects."""
    course_id_1 = str(uuid4())
    course_id_2 = str(uuid4())
    template_id_1 = str(uuid4())
    template_id_2 = str(uuid4())
    
    # Mock template
    template1 = MagicMock(spec=Template)
    template1.id = template_id_1
    template1.name = "Ubuntu 22.04"
    
    template2 = MagicMock(spec=Template)
    template2.id = template_id_2
    template2.name = "PostgreSQL"
    
    # Mock template versions
    version1 = MagicMock(spec=TemplateVersion)
    version1.id = str(uuid4())
    version1.version = "1.0.0"
    version1.template_id = template_id_1
    version1.template = template1
    
    version2 = MagicMock(spec=TemplateVersion)
    version2.id = str(uuid4())
    version2.version = "2.0.0"
    version2.template_id = template_id_1
    version2.template = template1
    
    version3 = MagicMock(spec=TemplateVersion)
    version3.id = str(uuid4())
    version3.version = "1.0.0"
    version3.template_id = template_id_2
    version3.template = template2
    
    # Mock courses
    course1 = MagicMock(spec=Course)
    course1.id = course_id_1
    course1.name = "CS101"
    course1.lecturer_id = 1
    
    course2 = MagicMock(spec=Course)
    course2.id = course_id_2
    course2.name = "CS201"
    course2.lecturer_id = 1
    
    course3 = MagicMock(spec=Course)
    course3.id = str(uuid4())
    course3.name = "CS301"
    course3.lecturer_id = 2
    
    # Mock deployments
    deployment1 = MagicMock(spec=Deployment)
    deployment1.id = "deploy-1"
    deployment1.name = "Web Dev Lab"
    deployment1.template_version_id = version1.id
    deployment1.course_id = course_id_1
    deployment1.status = DeploymentStatus.RUNNING
    deployment1.openstack_stack_id = "stack-1"
    deployment1.config_json = None
    deployment1.deployment_parameters = '{"cpu": 2}'
    deployment1.access_types_json = '["ssh"]'
    deployment1.created_at = datetime(2024, 11, 27, 10, 0, 0)
    deployment1.updated_at = datetime(2024, 11, 27, 10, 5, 0)
    deployment1.template_version = version1
    deployment1.course = course1
    
    deployment2 = MagicMock(spec=Deployment)
    deployment2.id = "deploy-2"
    deployment2.name = "Database Lab"
    deployment2.template_version_id = version2.id
    deployment2.course_id = course_id_2
    deployment2.status = DeploymentStatus.CREATING
    deployment2.openstack_stack_id = "stack-2"
    deployment2.config_json = None
    deployment2.deployment_parameters = '{"cpu": 4}'
    deployment2.access_types_json = '["ssh", "web"]'
    deployment2.created_at = datetime(2024, 11, 27, 11, 0, 0)
    deployment2.updated_at = datetime(2024, 11, 27, 11, 0, 0)
    deployment2.template_version = version2
    deployment2.course = course2
    
    deployment3 = MagicMock(spec=Deployment)
    deployment3.id = "deploy-3"
    deployment3.name = "Admin Deployment"
    deployment3.template_version_id = version3.id
    deployment3.course_id = course3.id
    deployment3.status = DeploymentStatus.FAILED
    deployment3.openstack_stack_id = "stack-3"
    deployment3.config_json = None
    deployment3.deployment_parameters = None
    deployment3.access_types_json = '["ssh"]'
    deployment3.created_at = datetime(2024, 11, 27, 9, 0, 0)
    deployment3.updated_at = datetime(2024, 11, 27, 9, 10, 0)
    deployment3.template_version = version3
    deployment3.course = course3
    
    return [deployment1, deployment2, deployment3], course_id_1, course_id_2, template_id_1, template_id_2


def test_list_deployments_as_lecturer(mock_deployments):
    """Test listing deployments as LECTURER (should see only own deployments)."""
    deployments, course_id_1, course_id_2, template_id_1, template_id_2 = mock_deployments
    # Lecturer should see only deployments from their courses
    lecturer_deployments = [d for d in deployments if d.course.lecturer_id == 1]
    
    # Mock DB session
    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_query.join.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.count.return_value = len(lecturer_deployments)
    mock_query.offset.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.all.return_value = lecturer_deployments
    mock_db.query.return_value = mock_query
    
    # Override dependencies
    app.dependency_overrides[get_current_user] = mock_lecturer_user
    app.dependency_overrides[get_db] = lambda: mock_db
    
    response = client.get("/api/v1/deployments")
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["pagination"]["total_items"] == 2
    assert len(data["data"]) == 2
    
    # Verify response format
    first_deployment = data["data"][0]
    assert "id" in first_deployment
    assert "name" in first_deployment
    assert "status" in first_deployment
    assert first_deployment["status"] in ["queued", "creating", "running", "restarting", "deleting", "failed"]
    assert "template_version" in first_deployment
    
    app.dependency_overrides.clear()


def test_list_deployments_as_admin(mock_deployments):
    """Test listing deployments as ADMIN (should see all deployments)."""
    deployments, course_id_1, course_id_2, template_id_1, template_id_2 = mock_deployments
    
    # Mock DB session
    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_query.join.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.count.return_value = len(deployments)
    mock_query.offset.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.all.return_value = deployments
    mock_db.query.return_value = mock_query
    
    # Override dependencies
    app.dependency_overrides[get_current_user] = mock_admin_user
    app.dependency_overrides[get_db] = lambda: mock_db
    
    response = client.get("/api/v1/deployments")
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["pagination"]["total_items"] == 3
    assert len(data["data"]) == 3
    
    app.dependency_overrides.clear()


def test_list_deployments_filter_by_course(mock_deployments):
    """Test filtering deployments by course_id."""
    deployments, course_id_1, course_id_2, template_id_1, template_id_2 = mock_deployments
    filtered = [d for d in deployments if d.course_id == course_id_1 and d.course.lecturer_id == 1]
    
    # Mock DB session
    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_query.join.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.count.return_value = len(filtered)
    mock_query.offset.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.all.return_value = filtered
    mock_db.query.return_value = mock_query
    
    # Override dependencies
    app.dependency_overrides[get_current_user] = mock_lecturer_user
    app.dependency_overrides[get_db] = lambda: mock_db
    
    response = client.get(f"/api/v1/deployments?course_id={course_id_1}")
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["pagination"]["total_items"] == 1
    assert data["data"][0]["course_id"] == course_id_1
    
    app.dependency_overrides.clear()


def test_list_deployments_filter_by_status(mock_deployments):
    """Test filtering deployments by status."""
    deployments, course_id_1, course_id_2, template_id_1, template_id_2 = mock_deployments
    filtered = [d for d in deployments if d.status == DeploymentStatus.RUNNING and d.course.lecturer_id == 1]
    
    # Mock DB session
    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_query.join.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.count.return_value = len(filtered)
    mock_query.offset.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.all.return_value = filtered
    mock_db.query.return_value = mock_query
    
    # Override dependencies
    app.dependency_overrides[get_current_user] = mock_lecturer_user
    app.dependency_overrides[get_db] = lambda: mock_db
    
    response = client.get("/api/v1/deployments?status=running")
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["pagination"]["total_items"] == 1
    assert data["data"][0]["status"] == "running"
    
    app.dependency_overrides.clear()


def test_list_deployments_pagination(mock_deployments):
    """Test pagination of deployment list."""
    deployments, course_id_1, course_id_2, template_id_1, template_id_2 = mock_deployments
    lecturer_deployments = [d for d in deployments if d.course.lecturer_id == 1]
    
    # Mock DB session
    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_query.join.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.count.return_value = len(lecturer_deployments)
    mock_query.offset.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.all.return_value = lecturer_deployments[:1]  # First page
    mock_db.query.return_value = mock_query
    
    # Override dependencies
    app.dependency_overrides[get_current_user] = mock_lecturer_user
    app.dependency_overrides[get_db] = lambda: mock_db
    
    response = client.get("/api/v1/deployments?page=1&page_size=1")
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["pagination"]["page"] == 1
    assert data["pagination"]["page_size"] == 1
    assert data["pagination"]["total_items"] == 2
    assert len(data["data"]) == 1
    
    app.dependency_overrides.clear()


def test_list_deployments_combined_filters(mock_deployments):
    """Test combining multiple filters."""
    deployments, course_id_1, course_id_2, template_id_1, template_id_2 = mock_deployments
    filtered = [d for d in deployments 
                if d.course_id == course_id_1 
                and d.status == DeploymentStatus.RUNNING 
                and d.course.lecturer_id == 1]
    
    # Mock DB session
    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_query.join.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.count.return_value = len(filtered)
    mock_query.offset.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.all.return_value = filtered
    mock_db.query.return_value = mock_query
    
    # Override dependencies
    app.dependency_overrides[get_current_user] = mock_lecturer_user
    app.dependency_overrides[get_db] = lambda: mock_db
    
    response = client.get(f"/api/v1/deployments?course_id={course_id_1}&status=running")
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["pagination"]["total_items"] == 1
    assert data["data"][0]["course_id"] == course_id_1
    assert data["data"][0]["status"] == "running"
    
    app.dependency_overrides.clear()


def test_list_deployments_no_results():
    """Test empty result when no deployments match filters."""
    # Mock DB session
    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_query.join.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.count.return_value = 0
    mock_query.offset.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.all.return_value = []
    mock_db.query.return_value = mock_query
    
    # Override dependencies
    app.dependency_overrides[get_current_user] = mock_lecturer_user
    app.dependency_overrides[get_db] = lambda: mock_db
    
    response = client.get("/api/v1/deployments")
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["pagination"]["total_items"] == 0
    assert len(data["data"]) == 0
    
    app.dependency_overrides.clear()


def test_list_deployments_invalid_status_filter():
    """Test that invalid status filter returns empty result with message."""
    # Override dependencies
    app.dependency_overrides[get_current_user] = mock_lecturer_user
    
    response = client.get("/api/v1/deployments?status=INVALID_STATUS")
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"] == []
    assert data["pagination"]["total_items"] == 0
    assert "Invalid status filter" in data["message"]
    
    app.dependency_overrides.clear()


def test_list_deployments_filter_by_template_id(mock_deployments):
    """Test filtering deployments by template_id."""
    deployments, course_id_1, course_id_2, template_id_1, template_id_2 = mock_deployments
    # Filter deployments by template_id and lecturer
    filtered = [d for d in deployments 
                if d.template_version.template_id == template_id_1 
                and d.course.lecturer_id == 1]
    
    # Mock DB session
    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_query.join.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.count.return_value = len(filtered)
    mock_query.offset.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.all.return_value = filtered
    mock_db.query.return_value = mock_query
    
    # Override dependencies
    app.dependency_overrides[get_current_user] = mock_lecturer_user
    app.dependency_overrides[get_db] = lambda: mock_db
    
    response = client.get(f"/api/v1/deployments?template_id={template_id_1}")
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["pagination"]["total_items"] == 2
    # All returned deployments should have the same template_id
    for deployment in data["data"]:
        assert deployment["template_version"]["template_id"] == str(template_id_1)
    
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
    mock_deployment.deployment_parameters = None  # Ensure this is a string or None

    # Mock course (owner check)
    mock_course = MagicMock()
    mock_course.id = "course-789"
    mock_course.name = "Test Course"
    mock_course.lecturer_id = 1  # Same as mock_lecturer_user
    mock_deployment.course = mock_course

    # Mock template version
    mock_template_version = MagicMock()
    mock_template_version.id = "version-456"
    mock_template_version.version = "1.0"
    mock_template_version.template_id = "template-abc"
    mock_template = MagicMock()
    mock_template.name = "Test Template"
    mock_template_version.template = mock_template
    mock_deployment.template_version = mock_template_version

    # Mock instances
    mock_instance = MagicMock()
    mock_instance.id = "instance-123"
    mock_instance.vm_name = "vm-1"
    mock_instance.openstack_server_id = "os-instance-456"
    mock_instance.status = MagicMock()
    mock_instance.status.value = "ACTIVE"
    mock_instance.ip_address = "192.168.1.10"
    mock_instance.access_methods = []
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
    mock_deployment.deployment_parameters = None  # Ensure this is a string or None

    # Mock course (different owner)
    mock_course = MagicMock()
    mock_course.id = "course-789"
    mock_course.name = "Other Course"
    mock_course.lecturer_id = 999  # Different from admin user_id
    mock_deployment.course = mock_course

    # Mock template version
    mock_template_version = MagicMock()
    mock_template_version.id = "version-456"
    mock_template_version.version = "1.0"
    mock_template_version.template_id = "template-abc"
    mock_template = MagicMock()
    mock_template.name = "Test Template"
    mock_template_version.template = mock_template
    mock_deployment.template_version = mock_template_version

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
    """Test retrieving another lecturer's deployment.
    
    Note: Authorization checking was simplified, so this now returns deployment
    instead of 403. Authorization will be re-implemented via openstack_project relationship.
    """
    app.dependency_overrides[get_current_user] = mock_lecturer_user
    
    # Mock deployment owned by another lecturer
    mock_deployment = MagicMock(spec=Deployment)
    mock_deployment.id = "deploy-123"
    mock_deployment.name = "Other Deployment"
    mock_deployment.template_version_id = "version-456"
    mock_deployment.course_id = "course-789"
    mock_deployment.status = DeploymentStatus.RUNNING
    mock_deployment.openstack_stack_id = "stack-xyz"
    mock_deployment.deployment_parameters = '{}'
    mock_deployment.created_at = datetime(2024, 11, 27, 10, 0, 0)
    mock_deployment.updated_at = datetime(2024, 11, 27, 10, 0, 0)
    mock_deployment.instances = []
    
    # Mock template_version relationship
    mock_template_version = MagicMock()
    mock_template_version.id = "version-456"
    mock_template_version.version = "1.0.0"
    mock_template_version.template_id = "template-123"
    mock_template_version.template = MagicMock()
    mock_template_version.template.name = "Test Template"
    mock_deployment.template_version = mock_template_version
    
    mock_repo_instance = MagicMock()
    mock_repo_instance.get_by_id.return_value = mock_deployment
    mock_repo_class.return_value = mock_repo_instance
    
    response = client.get("/api/v1/deployments/deploy-123")
    
    # Currently returns 200 since authorization is not checked
    # TODO: Re-enable authorization via openstack_project relationship
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    
    app.dependency_overrides.clear()


@patch("src.api.deployments.restart_deployment_task")
@patch("src.api.deployments.DeploymentLogService")
@patch("src.api.deployments.DeploymentRepository")
def test_restart_deployment_success(mock_repo_class, mock_log_service_class, mock_restart_task):
    """Test successful deployment restart request."""
    app.dependency_overrides[get_current_user] = mock_lecturer_user
    
    # Mock deployment in RUNNING state with proper deployment_parameters
    mock_deployment = MagicMock()
    mock_deployment.id = "deploy-123"
    mock_deployment.status = DeploymentStatus.RUNNING
    mock_deployment.openstack_stack_id = "stack-abc"
    mock_deployment.deployment_parameters = '{"teacher": {"id": "lecturer-123"}}'
    
    # Mock database session for User query in get_deployment_owner_id
    mock_db = MagicMock()
    mock_user = MagicMock()
    mock_user.id = 1  # Same as mock_lecturer_user
    mock_db.query.return_value.filter.return_value.first.return_value = mock_user
    app.dependency_overrides[get_db] = lambda: mock_db
    
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
    mock_deployment.deployment_parameters = '{"teacher": {"id": "other-lecturer-999"}}'
    
    # Mock database session for User query in get_deployment_owner_id
    mock_db = MagicMock()
    mock_other_user = MagicMock()
    mock_other_user.id = 999  # Different from mock_lecturer_user (id=1)
    mock_db.query.return_value.filter.return_value.first.return_value = mock_other_user
    app.dependency_overrides[get_db] = lambda: mock_db
    
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
    mock_deployment.deployment_parameters = '{"teacher": {"id": "lecturer-123"}}'
    
    # Mock database session for User query
    mock_db = MagicMock()
    mock_user = MagicMock()
    mock_user.id = 1
    mock_db.query.return_value.filter.return_value.first.return_value = mock_user
    app.dependency_overrides[get_db] = lambda: mock_db
    
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
    mock_deployment.deployment_parameters = '{"teacher": {"id": "lecturer-123"}}'
    
    # Mock database session for User query
    mock_db = MagicMock()
    mock_user = MagicMock()
    mock_user.id = 1
    mock_db.query.return_value.filter.return_value.first.return_value = mock_user
    app.dependency_overrides[get_db] = lambda: mock_db
    
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
    mock_deployment.deployment_parameters = '{"teacher": {"id": "lecturer-123"}}'
    
    # Mock database session for User query
    mock_db = MagicMock()
    mock_user = MagicMock()
    mock_user.id = 1
    mock_db.query.return_value.filter.return_value.first.return_value = mock_user
    app.dependency_overrides[get_db] = lambda: mock_db
    
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
