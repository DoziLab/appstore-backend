"""API tests for the redeploy endpoints.

Two endpoints are covered:

* ``POST /deployments/{id}/redeploy`` — fan-out over every instance
* ``POST /deployments/{id}/instances/{instance_id}/redeploy`` — single VM

Both flow through ``authorize_deployment_access`` for ownership, then
enqueue the matching Celery task with the body's override / preserve
flags. The actual task body is unit-tested in
``tests/unit/test_redeploy_tasks.py`` — here we cover only the HTTP
contract: status codes, body forwarding, transitional-state gating,
404s.
"""
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from src.main import app
from src.core.dependencies import get_current_user, get_db
from src.models.user import UserRole
from src.models.deployment import DeploymentStatus


TEST_OS_PROJECT_ID = "11111111-1111-1111-1111-111111111111"


def mock_lecturer_user():
    return {
        "sub": "lecturer-123", "email": "l@x.de", "name": "L",
        "preferred_username": "lec", "roles": [UserRole.LECTURER.value],
        "user_id": 1,
    }


def mock_admin_user():
    return {
        "sub": "admin-123", "email": "a@x.de", "name": "A",
        "preferred_username": "adm", "roles": [UserRole.ADMIN.value],
        "user_id": 2,
    }


client = TestClient(app)


def _mock_deployment_owned_by(user_id: int, *, status_=DeploymentStatus.RUNNING):
    """Build a deployment whose ``deployment_parameters`` claim ``user_id``
    as the owning lecturer (via the Keycloak ID mapping the API does)."""
    d = MagicMock()
    d.id = "deploy-123"
    d.status = status_
    d.openstack_stack_id = '["stack-1"]'
    d.deployment_parameters = '{"teacher": {"id": "lecturer-123"}}'
    d.openstack_project_id = TEST_OS_PROJECT_ID
    return d


def _patch_db_owner_lookup(user_id: int):
    """Make the User-table query in ``get_deployment_owner_id`` return a
    row with ``id=user_id`` so ownership checks pass for the lecturer.

    Also default the per-deployment "any instance already REDEPLOYING?" query
    to None so the deployment-wide endpoint's in-flight guard doesn't trip.
    Individual tests that want to assert that guard can override
    ``mock_db.query.return_value.filter.return_value.first`` afterwards.
    """
    mock_db = MagicMock()
    mock_user = MagicMock()
    mock_user.id = user_id
    # First call → User lookup (mock_user); subsequent .first() calls (e.g. the
    # REDEPLOYING-in-flight check) → None so the gate is open by default.
    mock_db.query.return_value.filter.return_value.first.side_effect = [
        mock_user, None, None, None, None
    ]
    return mock_db


# ---------------------------------------------------------------------------
# POST /{id}/redeploy — full deployment
# ---------------------------------------------------------------------------


@patch("src.api.deployments.redeploy_deployment_task")
@patch("src.api.deployments.DeploymentRepository")
def test_redeploy_deployment_success(mock_repo_class, mock_task):
    """Happy path: 202 returned, task enqueued with body overrides."""
    app.dependency_overrides[get_current_user] = mock_lecturer_user
    dep = _mock_deployment_owned_by(1)

    db = _patch_db_owner_lookup(1)
    # The endpoint counts instances via db.query(DeploymentInstance).filter(...).count()
    db.query.return_value.filter.return_value.count.return_value = 3
    app.dependency_overrides[get_db] = lambda: db

    repo = MagicMock()
    repo.get_by_id.return_value = dep
    mock_repo_class.return_value = repo

    response = client.post(
        f"/api/v1/deployments/deploy-123/redeploy?openstack_project_id={TEST_OS_PROJECT_ID}",
        json={
            "deployment_parameter_overrides": {"flag": True},
            "instance_parameter_overrides": {"inst-a": {"flag": False}},
            "preserve_credentials": True,
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["data"]["status"] == "redeploy_queued"
    assert body["data"]["instance_count"] == 3
    mock_task.delay.assert_called_once_with(
        "deploy-123",
        deployment_parameter_overrides={"flag": True},
        instance_parameter_overrides={"inst-a": {"flag": False}},
        preserve_credentials=True,
    )
    app.dependency_overrides.clear()


@patch("src.api.deployments.redeploy_deployment_task")
@patch("src.api.deployments.DeploymentRepository")
def test_redeploy_deployment_no_body_defaults(mock_repo_class, mock_task):
    """Body is optional — defaults are forwarded (no overrides, fresh creds)."""
    app.dependency_overrides[get_current_user] = mock_lecturer_user
    dep = _mock_deployment_owned_by(1)

    db = _patch_db_owner_lookup(1)
    db.query.return_value.filter.return_value.count.return_value = 1
    app.dependency_overrides[get_db] = lambda: db

    repo = MagicMock()
    repo.get_by_id.return_value = dep
    mock_repo_class.return_value = repo

    response = client.post(
        f"/api/v1/deployments/deploy-123/redeploy?openstack_project_id={TEST_OS_PROJECT_ID}"
    )

    assert response.status_code == 202
    mock_task.delay.assert_called_once_with(
        "deploy-123",
        deployment_parameter_overrides=None,
        instance_parameter_overrides=None,
        preserve_credentials=False,
    )
    app.dependency_overrides.clear()


@patch("src.api.deployments.DeploymentRepository")
def test_redeploy_deployment_blocked_in_transitional_state(mock_repo_class):
    """A deployment that's CREATING/DELETING/RESTARTING can't be redeployed."""
    app.dependency_overrides[get_current_user] = mock_lecturer_user
    dep = _mock_deployment_owned_by(1, status_=DeploymentStatus.CREATING)
    app.dependency_overrides[get_db] = lambda: _patch_db_owner_lookup(1)

    repo = MagicMock()
    repo.get_by_id.return_value = dep
    mock_repo_class.return_value = repo

    response = client.post(
        f"/api/v1/deployments/deploy-123/redeploy?openstack_project_id={TEST_OS_PROJECT_ID}"
    )
    assert response.status_code == 400
    app.dependency_overrides.clear()


@patch("src.api.deployments.DeploymentRepository")
def test_redeploy_deployment_no_instances_400(mock_repo_class):
    """A deployment with zero instance rows — nothing to redeploy."""
    app.dependency_overrides[get_current_user] = mock_lecturer_user
    dep = _mock_deployment_owned_by(1)

    db = _patch_db_owner_lookup(1)
    db.query.return_value.filter.return_value.count.return_value = 0
    app.dependency_overrides[get_db] = lambda: db

    repo = MagicMock()
    repo.get_by_id.return_value = dep
    mock_repo_class.return_value = repo

    response = client.post(
        f"/api/v1/deployments/deploy-123/redeploy?openstack_project_id={TEST_OS_PROJECT_ID}"
    )
    assert response.status_code == 400
    app.dependency_overrides.clear()


@patch("src.api.deployments.DeploymentRepository")
def test_redeploy_deployment_404(mock_repo_class):
    app.dependency_overrides[get_current_user] = mock_lecturer_user
    repo = MagicMock()
    repo.get_by_id.return_value = None
    mock_repo_class.return_value = repo

    response = client.post(f"/api/v1/deployments/nope/redeploy?openstack_project_id={TEST_OS_PROJECT_ID}")
    assert response.status_code == 404
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /{id}/instances/{instance_id}/redeploy — single VM
# ---------------------------------------------------------------------------


@patch("src.api.deployments.redeploy_instance_task")
@patch("src.api.deployments.DeploymentRepository")
def test_redeploy_instance_success(mock_repo_class, mock_task):
    """Happy path for the per-VM endpoint."""
    app.dependency_overrides[get_current_user] = mock_lecturer_user
    dep = _mock_deployment_owned_by(1)

    db = _patch_db_owner_lookup(1)
    # Two .first() calls in flight: first one resolves the User row for
    # the ownership check; second resolves the DeploymentInstance row.
    # Order the side_effect to match.
    mock_user = MagicMock()
    mock_user.id = 1
    mock_instance = MagicMock()
    mock_instance.id = "inst-A"
    mock_instance.deployment_id = "deploy-123"
    db.query.return_value.filter.return_value.first.side_effect = [mock_user, mock_instance]
    app.dependency_overrides[get_db] = lambda: db

    repo = MagicMock()
    repo.get_by_id.return_value = dep
    mock_repo_class.return_value = repo

    response = client.post(
        f"/api/v1/deployments/deploy-123/instances/inst-A/redeploy?openstack_project_id={TEST_OS_PROJECT_ID}",
        json={"deployment_parameter_overrides": {"include_notebooks": False}},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["data"]["status"] == "redeploy_queued"
    assert body["data"]["instance_id"] == "inst-A"
    mock_task.delay.assert_called_once_with(
        "deploy-123",
        "inst-A",
        deployment_parameter_overrides={"include_notebooks": False},
        preserve_credentials=False,
    )
    app.dependency_overrides.clear()


@patch("src.api.deployments.DeploymentRepository")
def test_redeploy_instance_instance_not_found(mock_repo_class):
    """Deployment exists but the instance doesn't — 404."""
    app.dependency_overrides[get_current_user] = mock_lecturer_user
    dep = _mock_deployment_owned_by(1)

    db = _patch_db_owner_lookup(1)
    # User lookup returns the owner row, but the instance lookup returns None.
    # The ownership check uses .filter.first() (user), and the instance
    # lookup is the SAME shape, so we sequence the return values.
    db.query.return_value.filter.return_value.first.side_effect = [
        MagicMock(id=1),  # owner user
        None,             # instance
    ]
    app.dependency_overrides[get_db] = lambda: db

    repo = MagicMock()
    repo.get_by_id.return_value = dep
    mock_repo_class.return_value = repo

    response = client.post(
        f"/api/v1/deployments/deploy-123/instances/missing/redeploy?openstack_project_id={TEST_OS_PROJECT_ID}"
    )
    assert response.status_code == 404
    app.dependency_overrides.clear()


@patch("src.api.deployments.DeploymentRepository")
def test_redeploy_instance_blocked_in_transitional_state(mock_repo_class):
    app.dependency_overrides[get_current_user] = mock_lecturer_user
    dep = _mock_deployment_owned_by(1, status_=DeploymentStatus.DELETING)
    app.dependency_overrides[get_db] = lambda: _patch_db_owner_lookup(1)

    repo = MagicMock()
    repo.get_by_id.return_value = dep
    mock_repo_class.return_value = repo

    response = client.post(
        f"/api/v1/deployments/deploy-123/instances/inst-A/redeploy?openstack_project_id={TEST_OS_PROJECT_ID}"
    )
    assert response.status_code == 400
    app.dependency_overrides.clear()


@patch("src.api.deployments.DeploymentRepository")
def test_redeploy_instance_deployment_not_found(mock_repo_class):
    app.dependency_overrides[get_current_user] = mock_lecturer_user
    repo = MagicMock()
    repo.get_by_id.return_value = None
    mock_repo_class.return_value = repo

    response = client.post(
        f"/api/v1/deployments/nope/instances/inst-A/redeploy?openstack_project_id={TEST_OS_PROJECT_ID}"
    )
    assert response.status_code == 404
    app.dependency_overrides.clear()
