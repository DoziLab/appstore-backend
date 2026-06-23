"""Integration tests for the deployment credentials endpoints.

Covers:
- ``GET /deployments/{id}/credentials`` returns ``ssh_private_key`` in the JSON.
- ``GET /deployments/{id}/credentials/access/{access_id}/ssh-key`` returns the
  decrypted PEM with the right headers (download flow used by the frontend).
"""
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from src.main import app
from src.core.dependencies import get_current_user, get_db
from src.models.user import UserRole


# Same fixed-UUID pattern the rest of tests/api/ uses.
TEST_OS_PROJECT_ID = "11111111-1111-1111-1111-111111111111"

_SAMPLE_PEM = (
    "-----BEGIN OPENSSH PRIVATE KEY-----\n"
    "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZWQy\n"
    "NTUxOQAAACBJYWWFAKEKEYZ0123456789AAAAAAAAAAAAAAAAAAAAA==\n"
    "-----END OPENSSH PRIVATE KEY-----\n"
)


def _mock_lecturer():
    return {
        "sub": "lecturer-123",
        "email": "lecturer@example.com",
        "preferred_username": "lecturer",
        "roles": [UserRole.LECTURER.value],
        "user_id": 1,
    }


def _mock_admin():
    return {
        "sub": "admin-123",
        "email": "admin@example.com",
        "preferred_username": "admin",
        "roles": [UserRole.ADMIN.value],
        "user_id": 2,
    }


def _patched_openstack_repo(owner_user_id: int = 1):
    """Tell ``authorize_deployment_access`` that TEST_OS_PROJECT_ID belongs to the user."""
    proj = MagicMock()
    proj.id = TEST_OS_PROJECT_ID
    proj.owner_user_id = owner_user_id
    repo = MagicMock()
    repo.get_by_id.return_value = proj
    return patch("src.api.deployments.OpenstackProjectRepository", return_value=repo)


def _build_deployment(*, deployment_id="deploy-1"):
    """Minimal Deployment mock that passes authorize_deployment_access for the lecturer."""
    d = MagicMock()
    d.id = deployment_id
    d.openstack_project_id = TEST_OS_PROJECT_ID
    # authorize_deployment_access reads teacher.id and looks the User row up by sub.
    d.deployment_parameters = '{"teacher": {"id": "lecturer-123"}}'
    return d


def _build_access(
    *,
    access_id="access-abc",
    username="gruppe-1",
    ssh_private_key=_SAMPLE_PEM,
    password="P@ssw0rd-1234567",
):
    """Mirror of a DeploymentInstanceAccess row (post-decryption)."""
    access = MagicMock()
    access.id = access_id
    access.username = username
    access.password = password
    access.ssh_private_key = ssh_private_key
    access.connection_url = f"ssh {username}@1.2.3.4"
    access.port = 22
    access.access_type = MagicMock()
    access.access_type.value = "ssh"
    return access


client = TestClient(app)


# ---------------------------------------------------------------------------
# GET /credentials — JSON response now includes ssh_private_key
# ---------------------------------------------------------------------------


@patch("src.api.deployments.DeploymentRepository")
def test_get_credentials_includes_ssh_private_key(mock_repo_class):
    """The full credentials response surfaces the decrypted SSH key alongside the password."""
    app.dependency_overrides[get_current_user] = _mock_lecturer

    deployment = _build_deployment()
    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = deployment
    mock_repo_class.return_value = mock_repo

    access = _build_access()
    instance = MagicMock()
    instance.id = "instance-1"
    instance.vm_name = "vm-1"
    instance.openstack_server_id = "stack-1"
    instance.access_methods = [access]

    db = MagicMock()
    user_row = MagicMock()
    user_row.id = 1  # matches _mock_lecturer's user_id → owner check passes
    db.query.return_value.filter.return_value.first.return_value = user_row
    # The endpoint also runs a separate query for DeploymentInstance — return our list.
    db.query.return_value.filter.return_value.all.return_value = [instance]
    app.dependency_overrides[get_db] = lambda: db

    with _patched_openstack_repo(owner_user_id=1):
        response = client.get(
            "/api/v1/deployments/deploy-1/credentials"
            f"?openstack_project_id={TEST_OS_PROJECT_ID}"
        )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert len(payload["instances"]) == 1
    entry = payload["instances"][0]["accesses"][0]
    # The id MUST be exposed — the download endpoint takes it as a path param,
    # and /credentials is the only place the frontend can discover it.
    assert entry["id"] == "access-abc"
    assert entry["ssh_private_key"] == _SAMPLE_PEM
    assert entry["password"] == "P@ssw0rd-1234567"

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /credentials/access/{id}/ssh-key — download endpoint
# ---------------------------------------------------------------------------


@patch("src.api.deployments.DeploymentRepository")
def test_download_ssh_key_returns_pem_with_attachment_header(mock_repo_class):
    """Happy path: PEM body, correct media type, attachment filename includes username."""
    app.dependency_overrides[get_current_user] = _mock_lecturer

    deployment = _build_deployment()
    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = deployment
    mock_repo_class.return_value = mock_repo

    access = _build_access(access_id="acc-1", username="gruppe-1")
    db = MagicMock()
    user_row = MagicMock()
    user_row.id = 1
    db.query.return_value.filter.return_value.first.return_value = user_row
    # The endpoint's access lookup chains .join().filter().first() — keep the
    # call chain alive by routing everything back to the same MagicMock and
    # making .first() the access row at the end.
    access_query = MagicMock()
    access_query.join.return_value.filter.return_value.first.return_value = access
    # First .query() call is for User, second for DeploymentInstanceAccess.
    db.query.side_effect = [db.query.return_value, access_query]
    app.dependency_overrides[get_db] = lambda: db

    with _patched_openstack_repo(owner_user_id=1):
        response = client.get(
            "/api/v1/deployments/deploy-1/credentials/access/acc-1/ssh-key"
            f"?openstack_project_id={TEST_OS_PROJECT_ID}"
        )

    assert response.status_code == 200, response.text
    assert response.text == _SAMPLE_PEM
    assert response.headers["content-type"].startswith("application/x-pem-file")
    assert 'attachment; filename="id_ed25519_gruppe-1"' in response.headers["content-disposition"]

    app.dependency_overrides.clear()


@patch("src.api.deployments.DeploymentRepository")
def test_download_ssh_key_404_when_access_has_no_key(mock_repo_class):
    """An access row that exists but has no key returns 404, not a 200 with empty body."""
    app.dependency_overrides[get_current_user] = _mock_lecturer

    deployment = _build_deployment()
    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = deployment
    mock_repo_class.return_value = mock_repo

    access = _build_access(ssh_private_key=None)
    db = MagicMock()
    user_row = MagicMock()
    user_row.id = 1
    db.query.return_value.filter.return_value.first.return_value = user_row
    access_query = MagicMock()
    access_query.join.return_value.filter.return_value.first.return_value = access
    db.query.side_effect = [db.query.return_value, access_query]
    app.dependency_overrides[get_db] = lambda: db

    with _patched_openstack_repo(owner_user_id=1):
        response = client.get(
            "/api/v1/deployments/deploy-1/credentials/access/acc-1/ssh-key"
            f"?openstack_project_id={TEST_OS_PROJECT_ID}"
        )

    assert response.status_code == 404
    assert "No SSH private key" in response.text

    app.dependency_overrides.clear()


@patch("src.api.deployments.DeploymentRepository")
def test_download_ssh_key_404_when_access_id_unknown(mock_repo_class):
    """Unknown access_id returns 404 even if the deployment itself exists."""
    app.dependency_overrides[get_current_user] = _mock_lecturer

    deployment = _build_deployment()
    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = deployment
    mock_repo_class.return_value = mock_repo

    db = MagicMock()
    user_row = MagicMock()
    user_row.id = 1
    db.query.return_value.filter.return_value.first.return_value = user_row
    access_query = MagicMock()
    access_query.join.return_value.filter.return_value.first.return_value = None
    db.query.side_effect = [db.query.return_value, access_query]
    app.dependency_overrides[get_db] = lambda: db

    with _patched_openstack_repo(owner_user_id=1):
        response = client.get(
            "/api/v1/deployments/deploy-1/credentials/access/missing/ssh-key"
            f"?openstack_project_id={TEST_OS_PROJECT_ID}"
        )

    assert response.status_code == 404

    app.dependency_overrides.clear()


@patch("src.api.deployments.DeploymentRepository")
def test_download_ssh_key_404_when_deployment_missing(mock_repo_class):
    """Unknown deployment returns 404 before any access lookup."""
    app.dependency_overrides[get_current_user] = _mock_lecturer

    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = None
    mock_repo_class.return_value = mock_repo

    app.dependency_overrides[get_db] = lambda: MagicMock()

    response = client.get(
        "/api/v1/deployments/does-not-exist/credentials/access/whatever/ssh-key"
        f"?openstack_project_id={TEST_OS_PROJECT_ID}"
    )

    assert response.status_code == 404

    app.dependency_overrides.clear()


@patch("src.api.deployments.DeploymentRepository")
def test_download_ssh_key_admin_can_download_any_deployments_key(mock_repo_class):
    """ADMINs bypass the lecturer-ownership check (matches the existing pattern)."""
    app.dependency_overrides[get_current_user] = _mock_admin

    # Deployment owned by someone else — admin can still access.
    deployment = _build_deployment()
    deployment.deployment_parameters = '{"teacher": {"id": "someone-else-999"}}'
    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = deployment
    mock_repo_class.return_value = mock_repo

    access = _build_access(username="prof-berg")
    db = MagicMock()
    # Admin path skips the User-ownership lookup entirely; only the access query runs.
    db.query.return_value.join.return_value.filter.return_value.first.return_value = access
    app.dependency_overrides[get_db] = lambda: db

    response = client.get(
        "/api/v1/deployments/deploy-1/credentials/access/acc-1/ssh-key"
    )

    assert response.status_code == 200
    assert 'filename="id_ed25519_prof-berg"' in response.headers["content-disposition"]

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Ownership enforcement — the crown jewel: no lecturer steals another's keys
# ---------------------------------------------------------------------------


@patch("src.api.deployments.DeploymentRepository")
def test_download_ssh_key_forbidden_for_non_owning_lecturer(mock_repo_class):
    """A lecturer who is NOT the deployment owner gets 403, not the PEM.

    This is the security-critical case: lecturers must only access their own
    deployments. Without this guard, any lecturer with the deployment_id and
    access_id could download another lecturer's admin/group keys.
    """
    app.dependency_overrides[get_current_user] = _mock_lecturer  # user_id=1

    # Deployment is owned by a DIFFERENT teacher (keycloak id "someone-else").
    deployment = _build_deployment()
    deployment.deployment_parameters = '{"teacher": {"id": "someone-else-keycloak-id"}}'
    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = deployment
    mock_repo_class.return_value = mock_repo

    # get_deployment_owner_id resolves the keycloak id to a User row with id=42 — not us.
    other_owner = MagicMock()
    other_owner.id = 42
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = other_owner
    app.dependency_overrides[get_db] = lambda: db

    with _patched_openstack_repo(owner_user_id=1):
        response = client.get(
            "/api/v1/deployments/deploy-1/credentials/access/acc-1/ssh-key"
            f"?openstack_project_id={TEST_OS_PROJECT_ID}"
        )

    assert response.status_code == 403
    # And critically: no PEM in the body, no Content-Disposition attachment header.
    assert "BEGIN OPENSSH PRIVATE KEY" not in response.text
    assert "content-disposition" not in {k.lower() for k in response.headers}

    app.dependency_overrides.clear()


@patch("src.api.deployments.DeploymentRepository")
def test_download_ssh_key_forbidden_when_project_id_mismatches(mock_repo_class):
    """Even the owning lecturer is rejected if the deployment lives in a different project.

    Guards against a scoped-project mix-up: passing the wrong openstack_project_id
    must fail closed instead of returning data tied to a different project.
    """
    app.dependency_overrides[get_current_user] = _mock_lecturer

    deployment = _build_deployment()
    # Different project than the one the caller passes in the query string.
    deployment.openstack_project_id = "99999999-9999-9999-9999-999999999999"
    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = deployment
    mock_repo_class.return_value = mock_repo

    db = MagicMock()
    owner = MagicMock()
    owner.id = 1
    db.query.return_value.filter.return_value.first.return_value = owner
    app.dependency_overrides[get_db] = lambda: db

    with _patched_openstack_repo(owner_user_id=1):
        response = client.get(
            "/api/v1/deployments/deploy-1/credentials/access/acc-1/ssh-key"
            f"?openstack_project_id={TEST_OS_PROJECT_ID}"
        )

    assert response.status_code == 403

    app.dependency_overrides.clear()


@patch("src.api.deployments.DeploymentRepository")
def test_download_ssh_key_400_without_openstack_project_id(mock_repo_class):
    """Non-admin caller must supply openstack_project_id — else 400 (defence in depth)."""
    app.dependency_overrides[get_current_user] = _mock_lecturer

    deployment = _build_deployment()
    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = deployment
    mock_repo_class.return_value = mock_repo

    app.dependency_overrides[get_db] = lambda: MagicMock()

    # No openstack_project_id query param!
    response = client.get(
        "/api/v1/deployments/deploy-1/credentials/access/acc-1/ssh-key"
    )

    assert response.status_code == 400

    app.dependency_overrides.clear()
