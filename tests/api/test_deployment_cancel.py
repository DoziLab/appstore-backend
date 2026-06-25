"""Integration tests for ``DELETE /deployments/{id}`` with the new
cooperative-cancel behaviour.

The endpoint now flips the deployment's status to ``DELETING`` *before*
enqueueing the delete task, so any in-flight ``deploy_stack`` worker
picks up the signal at its next checkpoint and bails out. The tests below
verify the flip happens and that the call stays idempotent for
deployments already in DELETING/DELETED state.
"""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from src.core.dependencies import get_current_user, get_db
from src.main import app
from src.models.deployment import DeploymentStatus
from src.models.user import UserRole


TEST_OS_PROJECT_ID = "11111111-1111-1111-1111-111111111111"


def _admin_user():
    return {
        "sub": "admin-123",
        "email": "admin@example.com",
        "preferred_username": "admin",
        "roles": [UserRole.ADMIN.value],
        "user_id": "admin-local-id",
    }


def _mock_deployment(status=DeploymentStatus.CREATING):
    """Mock a Deployment row in the given status."""
    dep = MagicMock()
    dep.id = "dep-xyz"
    dep.status = status
    dep.deployment_parameters = '{"teacher": {"id": "admin-123"}}'
    dep.openstack_project_id = TEST_OS_PROJECT_ID
    return dep


client = TestClient(app)


@patch("src.api.deployments.delete_deployment_task")
@patch("src.api.deployments.DeploymentRepository")
def test_delete_flips_creating_to_deleting_before_enqueue(mock_repo_class, mock_task):
    """When a CREATING deployment is deleted, the API must set DELETING
    *first*, then enqueue. The deploy task polls status at every
    checkpoint and will see the flag the moment the flip commits."""
    deployment = _mock_deployment(status=DeploymentStatus.CREATING)
    repo = MagicMock()
    repo.get_by_id.return_value = deployment
    mock_repo_class.return_value = repo

    app.dependency_overrides[get_current_user] = _admin_user
    app.dependency_overrides[get_db] = lambda: MagicMock()
    try:
        response = client.delete(f"/api/v1/deployments/{deployment.id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 204
    # update_status was called with DELETING — verify the cooperative-cancel flag.
    repo.update_status.assert_called_once_with(deployment.id, DeploymentStatus.DELETING)
    # And the Celery task was enqueued.
    mock_task.delay.assert_called_once_with(deployment.id)


@patch("src.api.deployments.delete_deployment_task")
@patch("src.api.deployments.DeploymentRepository")
def test_delete_idempotent_for_already_deleting(mock_repo_class, mock_task):
    """A second DELETE on a deployment already in DELETING must not
    re-flip the status (avoids spurious status churn) but should still
    enqueue another delete-task call so transient Celery losses are
    tolerated. Idempotency at the status level, retry-friendly at the
    queue level."""
    deployment = _mock_deployment(status=DeploymentStatus.DELETING)
    repo = MagicMock()
    repo.get_by_id.return_value = deployment
    mock_repo_class.return_value = repo

    app.dependency_overrides[get_current_user] = _admin_user
    app.dependency_overrides[get_db] = lambda: MagicMock()
    try:
        response = client.delete(f"/api/v1/deployments/{deployment.id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 204
    repo.update_status.assert_not_called()
    mock_task.delay.assert_called_once_with(deployment.id)


@patch("src.api.deployments.delete_deployment_task")
@patch("src.api.deployments.DeploymentRepository")
def test_delete_idempotent_for_already_deleted(mock_repo_class, mock_task):
    """A DELETE on a deployment that's already DELETED also skips the status
    update — there's nothing left to cancel."""
    deployment = _mock_deployment(status=DeploymentStatus.DELETED)
    repo = MagicMock()
    repo.get_by_id.return_value = deployment
    mock_repo_class.return_value = repo

    app.dependency_overrides[get_current_user] = _admin_user
    app.dependency_overrides[get_db] = lambda: MagicMock()
    try:
        response = client.delete(f"/api/v1/deployments/{deployment.id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 204
    repo.update_status.assert_not_called()
    mock_task.delay.assert_called_once_with(deployment.id)


@patch("src.api.deployments.delete_deployment_task")
@patch("src.api.deployments.DeploymentRepository")
def test_delete_running_deployment_flips_to_deleting(mock_repo_class, mock_task):
    """The status flip happens for any non-terminal state — the regular
    'delete a finished deployment' path also benefits from the flag
    (harmless when no deploy task is running)."""
    deployment = _mock_deployment(status=DeploymentStatus.RUNNING)
    repo = MagicMock()
    repo.get_by_id.return_value = deployment
    mock_repo_class.return_value = repo

    app.dependency_overrides[get_current_user] = _admin_user
    app.dependency_overrides[get_db] = lambda: MagicMock()
    try:
        response = client.delete(f"/api/v1/deployments/{deployment.id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 204
    repo.update_status.assert_called_once_with(deployment.id, DeploymentStatus.DELETING)
    mock_task.delay.assert_called_once_with(deployment.id)


@patch("src.api.deployments.delete_deployment_task")
@patch("src.api.deployments.DeploymentRepository")
def test_delete_404_when_deployment_missing(mock_repo_class, mock_task):
    """No deployment → 404, no status flip, no enqueue."""
    repo = MagicMock()
    repo.get_by_id.return_value = None
    mock_repo_class.return_value = repo

    app.dependency_overrides[get_current_user] = _admin_user
    app.dependency_overrides[get_db] = lambda: MagicMock()
    try:
        response = client.delete("/api/v1/deployments/does-not-exist")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    repo.update_status.assert_not_called()
    mock_task.delay.assert_not_called()
