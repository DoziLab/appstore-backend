"""Tests for course listing endpoint with OpenStack-project scoping.

These tests guard the second deployment-leak fix (the first one lived in
``/api/v1/deployments`` and is covered by ``test_deployment_routes.py``):
``GET /api/v1/courses`` eager-loads ``course.deployments`` and used to do so
with no owner/project filter. The contract here mirrors ``list_deployments``:

- Non-admin without ``openstack_project_id``  → 400
- Non-admin with someone else's project       → 403
- Non-admin with their own project            → embedded deployments are filtered
  to (project == arg) AND (teacher.id == caller)
- Admin                                       → no scoping enforced
"""
from unittest.mock import patch, MagicMock
import pytest
from uuid import uuid4
from datetime import datetime
from fastapi.testclient import TestClient

from src.main import app
from src.core.dependencies import get_current_user, get_db
from src.models.user import UserRole
from src.models.course import Course
from src.models.deployment import Deployment, DeploymentStatus


TEST_OS_PROJECT_ID = "11111111-1111-1111-1111-111111111111"


def _patched_openstack_repo(owner_user_id: int = 1):
    """Make ``OpenstackProjectRepository.get_by_id`` return a project owned by
    ``owner_user_id`` so the courses-API auth helper (which lives in
    ``src.api.courses``) accepts ``TEST_OS_PROJECT_ID``."""
    proj = MagicMock()
    proj.id = TEST_OS_PROJECT_ID
    proj.owner_user_id = owner_user_id
    repo = MagicMock()
    repo.get_by_id.return_value = proj
    return patch("src.api.courses.OpenstackProjectRepository", return_value=repo)


def mock_lecturer_user():
    return {
        "sub": "lecturer-123",
        "email": "lecturer@example.com",
        "name": "Test Lecturer",
        "preferred_username": "lecturer",
        "roles": [UserRole.LECTURER.value],
        "user_id": 1,
    }


def mock_admin_user():
    return {
        "sub": "admin-123",
        "email": "admin@example.com",
        "name": "Test Admin",
        "preferred_username": "admin",
        "roles": [UserRole.ADMIN.value],
        "user_id": 2,
    }


client = TestClient(app)


def _make_deployment(*, did: str, teacher_keycloak: str | None) -> Deployment:
    """Build a Deployment mock with the minimal attrs the response schema needs.

    ``teacher_keycloak`` is the value embedded into ``deployment_parameters``
    JSON; ``get_deployment_owner_id`` walks the JSON to resolve it back to a
    local user_id via the User-table lookup we mock below.
    """
    d = MagicMock(spec=Deployment)
    d.id = did
    d.name = f"Deployment {did}"
    d.template_version_id = str(uuid4())
    d.status = DeploymentStatus.RUNNING
    d.created_at = datetime(2024, 11, 27, 10, 0, 0)
    d.openstack_project_id = TEST_OS_PROJECT_ID
    if teacher_keycloak is None:
        d.deployment_parameters = None
    else:
        d.deployment_parameters = (
            '{"teacher": {"id": "' + teacher_keycloak + '"}}'
        )
    return d


@pytest.fixture
def mock_course_with_mixed_deployments():
    """One course with two deployments: one owned by the lecturer, one by
    someone else. The repository's project-filter is mocked separately, so this
    fixture only exercises the API-layer owner filter."""
    own = _make_deployment(did="deploy-own", teacher_keycloak="lecturer-123")
    foreign = _make_deployment(did="deploy-foreign", teacher_keycloak="other-456")

    course = MagicMock(spec=Course)
    course.id = str(uuid4())
    course.name = "CS101"
    course.keycloak_course_id = "kc-course-1"
    course.created_at = datetime(2024, 11, 27, 10, 0, 0)
    course.updated_at = datetime(2024, 11, 27, 10, 0, 0)
    # Both deployments are eager-loaded by the (mocked) repo. The endpoint will
    # strip ``deploy-foreign`` after owner-resolution because its teacher.id
    # doesn't map to user_id=1.
    course.deployments = [own, foreign]
    return course


def _install_db_with_courses(courses: list, owner_lookup_user_id: int | None = 1):
    """Configure ``app.dependency_overrides`` so the route gets a DB whose
    ``CourseRepository`` returns ``courses`` and whose User-lookup (used by
    ``get_deployment_owner_id``) only resolves ``"lecturer-123"`` to user_id=1.

    Returns the mock_db so callers can introspect it if needed.
    """
    mock_db = MagicMock()

    # Course-list query: a chain that ends in ``.all()`` — used by
    # CourseRepository.get_all_filtered.
    course_query = MagicMock()
    course_query.filter.return_value = course_query
    course_query.order_by.return_value = course_query
    course_query.count.return_value = len(courses)
    course_query.offset.return_value = course_query
    course_query.limit.return_value = course_query
    course_query.options.return_value = course_query
    course_query.all.return_value = courses
    # CourseRepository.get_by_id_with_deployments ends in ``.first()`` — return
    # the first course so the route's get_course path works too.
    course_query.first.return_value = courses[0] if courses else None

    # User-lookup query: ``db.query(User).filter(User.external_id == kc).first()``.
    # We need different return values per kc-id so the owner-filter actually
    # discriminates. Using a side_effect on filter() that captures the kc-id
    # via the SQLAlchemy expression's right-hand side is brittle — instead we
    # build a MagicMock whose .first() returns a user with id=1 when the most
    # recent filter() arg encodes "lecturer-123", else None.
    def make_user_query():
        user_query = MagicMock()
        captured = {"kc": None}

        def filter_side_effect(*args, **kwargs):
            # SQLAlchemy passes a BinaryExpression like (User.external_id == "kc-id").
            # Pull the literal off the expression's right-hand side; fall back to
            # str() for the rare case it's pre-bound.
            if args:
                expr = args[0]
                rhs = getattr(expr, "right", None)
                if rhs is not None:
                    captured["kc"] = getattr(rhs, "value", str(rhs))
                else:
                    captured["kc"] = str(expr)
            return user_query

        user_query.filter.side_effect = filter_side_effect

        def first_side_effect():
            if captured["kc"] == "lecturer-123" and owner_lookup_user_id is not None:
                u = MagicMock()
                u.id = owner_lookup_user_id
                return u
            return None

        user_query.first.side_effect = first_side_effect
        return user_query

    # Two model classes are queried via db.query(): Course and User. Dispatch
    # by what was passed in.
    def query_side_effect(model):
        # CourseRepository passes the Course class; get_deployment_owner_id passes
        # the User class. Distinguish by name to avoid importing the model just
        # to do an isinstance check.
        if getattr(model, "__name__", "") == "User":
            return make_user_query()
        return course_query

    mock_db.query.side_effect = query_side_effect

    app.dependency_overrides[get_current_user] = mock_lecturer_user
    app.dependency_overrides[get_db] = lambda: mock_db
    return mock_db


# ── 400: non-admin without openstack_project_id ───────────────────────────────


def test_list_courses_lecturer_without_project_id_returns_400():
    """The same contract as ``list_deployments``: a lecturer must always scope
    by project. Without it, the embedded deployments would leak again."""
    _install_db_with_courses([])
    response = client.get("/api/v1/courses")
    assert response.status_code == 400
    assert "openstack_project_id" in response.json()["detail"]
    app.dependency_overrides.clear()


# ── 403: non-admin with someone else's project ────────────────────────────────


def test_list_courses_lecturer_with_foreign_project_returns_403():
    """If the project doesn't belong to the caller, we reject before reading
    any course rows. ``owner_user_id=99`` ≠ ``user_id=1`` triggers it."""
    _install_db_with_courses([])
    response = client.get(
        f"/api/v1/courses?openstack_project_id={TEST_OS_PROJECT_ID}"
    )
    # No openstack-repo patch ⇒ default fallback would be a real DB call. Patch
    # explicitly to return a project NOT owned by the caller.
    with _patched_openstack_repo(owner_user_id=99):
        response = client.get(
            f"/api/v1/courses?openstack_project_id={TEST_OS_PROJECT_ID}"
        )
    assert response.status_code == 403
    assert "does not belong" in response.json()["detail"]
    app.dependency_overrides.clear()


# ── 200: lecturer with own project ⇒ owner-filter strips foreign deployments ──


def test_list_courses_lecturer_filters_embedded_deployments(
    mock_course_with_mixed_deployments,
):
    """Both project-filter (in repo) and owner-filter (in API) must apply.
    Repo is mocked to return the course unchanged with both deployments; the
    API layer should drop the foreign one."""
    _install_db_with_courses([mock_course_with_mixed_deployments])

    with _patched_openstack_repo():
        response = client.get(
            f"/api/v1/courses?openstack_project_id={TEST_OS_PROJECT_ID}"
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert len(data["data"]) == 1
    course = data["data"][0]
    deployment_ids = [d["id"] for d in course["deployments"]]
    assert deployment_ids == ["deploy-own"], (
        f"Owner-filter leaked: expected only ['deploy-own'], got {deployment_ids}"
    )
    app.dependency_overrides.clear()


# ── 200: admin without project_id ⇒ no scoping ────────────────────────────────


def test_list_courses_admin_without_project_id_sees_all_deployments(
    mock_course_with_mixed_deployments,
):
    """Admins keep their unrestricted view — the same exception we made in
    ``list_deployments``. They can pass ``openstack_project_id`` if they want
    to scope, but unset means no filter."""
    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_query.filter.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.count.return_value = 1
    mock_query.offset.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.options.return_value = mock_query
    mock_query.all.return_value = [mock_course_with_mixed_deployments]
    mock_db.query.return_value = mock_query

    app.dependency_overrides[get_current_user] = mock_admin_user
    app.dependency_overrides[get_db] = lambda: mock_db

    response = client.get("/api/v1/courses")

    assert response.status_code == 200
    data = response.json()
    assert len(data["data"]) == 1
    deployment_ids = [d["id"] for d in data["data"][0]["deployments"]]
    # Admin path: NEITHER filter ran, both deployments embedded as-is.
    assert sorted(deployment_ids) == ["deploy-foreign", "deploy-own"]
    app.dependency_overrides.clear()


# ── get_course mirrors the same contract ──────────────────────────────────────


def test_get_course_lecturer_filters_embedded_deployments(
    mock_course_with_mixed_deployments,
):
    """``GET /api/v1/courses/{id}`` shares the auth helper and owner-filter
    with ``list_courses``; verify the same outcome on the single-course path."""
    course = mock_course_with_mixed_deployments
    _install_db_with_courses([course])

    with _patched_openstack_repo():
        response = client.get(
            f"/api/v1/courses/{course.id}?openstack_project_id={TEST_OS_PROJECT_ID}"
        )

    assert response.status_code == 200
    data = response.json()["data"]
    deployment_ids = [d["id"] for d in data["deployments"]]
    assert deployment_ids == ["deploy-own"]
    app.dependency_overrides.clear()


def test_get_course_lecturer_without_project_id_returns_400(
    mock_course_with_mixed_deployments,
):
    """Single-course endpoint enforces the same query-param contract."""
    course = mock_course_with_mixed_deployments
    _install_db_with_courses([course])
    response = client.get(f"/api/v1/courses/{course.id}")
    assert response.status_code == 400
    app.dependency_overrides.clear()
