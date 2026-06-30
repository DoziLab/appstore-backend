"""Tests for /api/v1/course-filters endpoints.

The resource is a flat admin-managed list of strings the frontend renders as
filter-chips above the course list. The interesting contract pieces:

- Reads are open to any authenticated user (lecturer too — frontend needs them).
- Writes (POST/PATCH/DELETE) are ADMIN-only; a lecturer must get a 403.
- ``name`` is unique → duplicate create returns 409 (ConflictException),
  the service falls back on IntegrityError if the pre-check races.
- 404 on unknown id for both PATCH and DELETE.

We mock at the dependency level (DB session + ``get_current_user``) like the
sibling courses tests instead of spinning up a real DB.
"""
from datetime import datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from src.core.dependencies import get_current_user, get_db
from src.main import app
from src.models.course_filter import CourseFilter
from src.models.user import UserRole


client = TestClient(app)


def _admin_user():
    return {
        "sub": "admin-1",
        "email": "admin@example.com",
        "name": "Admin",
        "preferred_username": "admin",
        "roles": [UserRole.ADMIN.value],
        "user_id": 1,
    }


def _lecturer_user():
    return {
        "sub": "lecturer-1",
        "email": "lecturer@example.com",
        "name": "Lecturer",
        "preferred_username": "lecturer",
        "roles": [UserRole.LECTURER.value],
        "user_id": 2,
    }


def _make_filter(name: str = "SQL", fid: str | None = None) -> CourseFilter:
    """Build a ``CourseFilter`` row sufficient for response-validation.

    We use ``spec=CourseFilter`` so Pydantic's ``from_attributes`` sees the
    expected fields without hitting the SQLAlchemy session.
    """
    f = MagicMock(spec=CourseFilter)
    f.id = fid or str(uuid4())
    f.name = name
    f.created_at = datetime(2026, 6, 30, 10, 0, 0)
    f.updated_at = datetime(2026, 6, 30, 10, 0, 0)
    return f


@pytest.fixture(autouse=True)
def _clear_overrides():
    """Each test installs its own overrides; reset between cases."""
    yield
    app.dependency_overrides.clear()


# ── list ──────────────────────────────────────────────────────────────────────


def test_list_filters_returns_paginated_payload():
    """A lecturer (non-admin) is allowed to read the list — the frontend chip
    bar needs to render for every signed-in user."""
    rows = [_make_filter("SQL"), _make_filter("Web")]

    repo = MagicMock()
    repo.get_all_filtered.return_value = (rows, len(rows))

    app.dependency_overrides[get_current_user] = _lecturer_user
    app.dependency_overrides[get_db] = lambda: MagicMock()

    with patch(
        "src.services.course_filter_service.CourseFilterRepository",
        return_value=repo,
    ):
        response = client.get("/api/v1/course-filters")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert [item["name"] for item in body["data"]] == ["SQL", "Web"]
    # Pagination block is present (ResponseBuilder.paginated contract).
    assert body["pagination"]["total_items"] == 2


def test_list_filters_passes_search_to_repo():
    """``?search=foo`` flows through to ``get_all_filtered(search="foo")`` so
    the case-insensitive substring filter actually runs in the DB layer."""
    repo = MagicMock()
    repo.get_all_filtered.return_value = ([], 0)

    app.dependency_overrides[get_current_user] = _admin_user
    app.dependency_overrides[get_db] = lambda: MagicMock()

    with patch(
        "src.services.course_filter_service.CourseFilterRepository",
        return_value=repo,
    ):
        response = client.get("/api/v1/course-filters?search=sq")

    assert response.status_code == 200
    repo.get_all_filtered.assert_called_once()
    assert repo.get_all_filtered.call_args.kwargs["search"] == "sq"


# ── create: admin path ────────────────────────────────────────────────────────


def test_create_filter_admin_succeeds():
    """Happy path: admin posts a fresh name, repo creates and returns it."""
    created = _make_filter("SQL")
    repo = MagicMock()
    repo.get_by_name.return_value = None  # not a duplicate
    repo.create.return_value = created

    app.dependency_overrides[get_current_user] = _admin_user
    app.dependency_overrides[get_db] = lambda: MagicMock()

    with patch(
        "src.services.course_filter_service.CourseFilterRepository",
        return_value=repo,
    ):
        response = client.post("/api/v1/course-filters", json={"name": "SQL"})

    assert response.status_code == 201
    assert response.json()["data"]["name"] == "SQL"
    repo.create.assert_called_once_with(name="SQL")


def test_create_filter_strips_whitespace():
    """``"  SQL  "`` → ``"SQL"``. The Pydantic validator trims before the
    duplicate-check and the DB insert."""
    repo = MagicMock()
    repo.get_by_name.return_value = None
    repo.create.side_effect = lambda **kw: _make_filter(kw["name"])

    app.dependency_overrides[get_current_user] = _admin_user
    app.dependency_overrides[get_db] = lambda: MagicMock()

    with patch(
        "src.services.course_filter_service.CourseFilterRepository",
        return_value=repo,
    ):
        response = client.post(
            "/api/v1/course-filters", json={"name": "  SQL  "}
        )

    assert response.status_code == 201
    assert repo.create.call_args.kwargs["name"] == "SQL"


def test_create_filter_blank_name_returns_422():
    """An all-whitespace name fails Pydantic validation before reaching the
    service — duplicate-check would otherwise incorrectly look up ``""``."""
    app.dependency_overrides[get_current_user] = _admin_user
    app.dependency_overrides[get_db] = lambda: MagicMock()

    response = client.post("/api/v1/course-filters", json={"name": "   "})
    assert response.status_code == 422


def test_create_filter_duplicate_name_returns_409():
    """Pre-check path: the name already exists → ConflictException → 409."""
    repo = MagicMock()
    repo.get_by_name.return_value = _make_filter("SQL")

    app.dependency_overrides[get_current_user] = _admin_user
    app.dependency_overrides[get_db] = lambda: MagicMock()

    with patch(
        "src.services.course_filter_service.CourseFilterRepository",
        return_value=repo,
    ):
        response = client.post("/api/v1/course-filters", json={"name": "SQL"})

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]
    repo.create.assert_not_called()


def test_create_filter_race_integrity_error_returns_409():
    """Race path: pre-check returns None but the INSERT trips the unique
    constraint (concurrent admin). Service must catch IntegrityError and map
    to 409, not bubble a 500."""
    repo = MagicMock()
    repo.get_by_name.return_value = None
    repo.create.side_effect = IntegrityError("INSERT", {}, Exception("dup"))

    app.dependency_overrides[get_current_user] = _admin_user
    app.dependency_overrides[get_db] = lambda: MagicMock()

    with patch(
        "src.services.course_filter_service.CourseFilterRepository",
        return_value=repo,
    ):
        response = client.post("/api/v1/course-filters", json={"name": "SQL"})

    assert response.status_code == 409


# ── create: non-admin is rejected ─────────────────────────────────────────────


def test_create_filter_lecturer_returns_403():
    """Endpoint-level ``require_roles(ADMIN)`` blocks lecturers from writing."""
    app.dependency_overrides[get_current_user] = _lecturer_user
    app.dependency_overrides[get_db] = lambda: MagicMock()

    response = client.post("/api/v1/course-filters", json={"name": "SQL"})
    assert response.status_code == 403


# ── update: admin path ────────────────────────────────────────────────────────


def test_update_filter_admin_renames():
    fid = str(uuid4())
    existing = _make_filter("SQL", fid=fid)
    renamed = _make_filter("SQL Grundlagen", fid=fid)

    repo = MagicMock()
    # get_by_id is called twice: get_filter() and then update()'s internal
    # get_by_id. Return the same row both times.
    repo.get_by_id.return_value = existing
    repo.get_by_name.return_value = None  # new name is free
    repo.update.return_value = renamed

    app.dependency_overrides[get_current_user] = _admin_user
    app.dependency_overrides[get_db] = lambda: MagicMock()

    with patch(
        "src.services.course_filter_service.CourseFilterRepository",
        return_value=repo,
    ):
        response = client.patch(
            f"/api/v1/course-filters/{fid}",
            json={"name": "SQL Grundlagen"},
        )

    assert response.status_code == 200
    assert response.json()["data"]["name"] == "SQL Grundlagen"


def test_update_filter_to_existing_name_returns_409():
    """Renaming filter A to filter B's name must conflict."""
    fid_a = str(uuid4())
    fid_b = str(uuid4())
    a = _make_filter("Web", fid=fid_a)
    b = _make_filter("SQL", fid=fid_b)

    repo = MagicMock()
    repo.get_by_id.return_value = a
    repo.get_by_name.return_value = b  # taken by another row

    app.dependency_overrides[get_current_user] = _admin_user
    app.dependency_overrides[get_db] = lambda: MagicMock()

    with patch(
        "src.services.course_filter_service.CourseFilterRepository",
        return_value=repo,
    ):
        response = client.patch(
            f"/api/v1/course-filters/{fid_a}", json={"name": "SQL"}
        )

    assert response.status_code == 409
    repo.update.assert_not_called()


def test_update_filter_unknown_id_returns_404():
    repo = MagicMock()
    repo.get_by_id.return_value = None

    app.dependency_overrides[get_current_user] = _admin_user
    app.dependency_overrides[get_db] = lambda: MagicMock()

    with patch(
        "src.services.course_filter_service.CourseFilterRepository",
        return_value=repo,
    ):
        response = client.patch(
            f"/api/v1/course-filters/{uuid4()}", json={"name": "new"}
        )

    assert response.status_code == 404


def test_update_filter_lecturer_returns_403():
    app.dependency_overrides[get_current_user] = _lecturer_user
    app.dependency_overrides[get_db] = lambda: MagicMock()

    response = client.patch(
        f"/api/v1/course-filters/{uuid4()}", json={"name": "x"}
    )
    assert response.status_code == 403


# ── delete ────────────────────────────────────────────────────────────────────


def test_delete_filter_admin_succeeds():
    fid = str(uuid4())
    repo = MagicMock()
    repo.get_by_id.return_value = _make_filter("SQL", fid=fid)
    repo.delete.return_value = True

    app.dependency_overrides[get_current_user] = _admin_user
    app.dependency_overrides[get_db] = lambda: MagicMock()

    with patch(
        "src.services.course_filter_service.CourseFilterRepository",
        return_value=repo,
    ):
        response = client.delete(f"/api/v1/course-filters/{fid}")

    assert response.status_code == 200
    assert response.json()["success"] is True
    # delete() accepts either positional or keyword id; just assert it was hit.
    assert repo.delete.called


def test_delete_filter_unknown_id_returns_404():
    repo = MagicMock()
    repo.get_by_id.return_value = None

    app.dependency_overrides[get_current_user] = _admin_user
    app.dependency_overrides[get_db] = lambda: MagicMock()

    with patch(
        "src.services.course_filter_service.CourseFilterRepository",
        return_value=repo,
    ):
        response = client.delete(f"/api/v1/course-filters/{uuid4()}")

    assert response.status_code == 404
    repo.delete.assert_not_called()


def test_delete_filter_lecturer_returns_403():
    app.dependency_overrides[get_current_user] = _lecturer_user
    app.dependency_overrides[get_db] = lambda: MagicMock()

    response = client.delete(f"/api/v1/course-filters/{uuid4()}")
    assert response.status_code == 403
