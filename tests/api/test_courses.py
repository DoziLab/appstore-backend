"""Tests for Course API endpoints."""

import pytest
from fastapi.testclient import TestClient
from src.main import app
from jose import jwt
from datetime import datetime, timedelta, timezone

SECRET_KEY = "test-secret-key"  # Must match your test setup
ALGORITHM = "HS256"

client = TestClient(app)

def create_test_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(hours=1)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

@pytest.fixture
def auth_headers_admin():
    token_data = {
        "sub": "admin-uuid-123",
        "preferred_username": "admin",
        "realm_access": {"roles": ["admin"]}
    }
    token = create_test_token(token_data)
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture
def auth_headers_lecturer():
    token_data = {
        "sub": "lecturer-uuid-456",
        "preferred_username": "lecturer",
        "realm_access": {"roles": ["lecturer"]}
    }
    token = create_test_token(token_data)
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture
def auth_headers_student():
    token_data = {
        "sub": "student-uuid-789",
        "preferred_username": "student",
        "realm_access": {"roles": ["student"]}
    }
    token = create_test_token(token_data)
    return {"Authorization": f"Bearer {token}"}


def test_create_course_as_lecturer(auth_headers_lecturer):
    payload = {
        "name": "Test Course",
        "semester": "WS2026"
    }
    response = client.post("/api/v1/courses", json=payload, headers=auth_headers_lecturer)
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["name"] == "Test Course"
    assert data["semester"] == "WS2026"
    assert "id" in data


def test_list_courses_as_admin(auth_headers_admin):
    response = client.get("/api/v1/courses", headers=auth_headers_admin)
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True
    assert "data" in result
    assert isinstance(result["data"], list)


def test_list_courses_as_lecturer(auth_headers_lecturer):
    response = client.get("/api/v1/courses", headers=auth_headers_lecturer)
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True
    assert "data" in result
    assert isinstance(result["data"], list)
    # Only own courses should be listed
    for course in result["data"]:
        assert course["lecturer_id"] == "lecturer-uuid-456"


def test_get_course(auth_headers_lecturer):
    # Create a course first
    payload = {"name": "Get Course", "semester": "WS2026"}
    create_resp = client.post("/api/v1/courses", json=payload, headers=auth_headers_lecturer)
    course_id = create_resp.json()["data"]["id"]
    # Get the course
    response = client.get(f"/api/v1/courses/{course_id}", headers=auth_headers_lecturer)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == course_id
    assert data["name"] == "Get Course"


def test_update_course(auth_headers_lecturer):
    # Create a course first
    payload = {"name": "Update Course", "semester": "WS2026"}
    create_resp = client.post("/api/v1/courses", json=payload, headers=auth_headers_lecturer)
    course_id = create_resp.json()["data"]["id"]
    # Update the course
    update_payload = {"name": "Updated Name"}
    response = client.patch(f"/api/v1/courses/{course_id}", json=update_payload, headers=auth_headers_lecturer)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["name"] == "Updated Name"


def test_delete_course(auth_headers_lecturer):
    # Create a course first
    payload = {"name": "Delete Course", "semester": "WS2026"}
    create_resp = client.post("/api/v1/courses", json=payload, headers=auth_headers_lecturer)
    course_id = create_resp.json()["data"]["id"]
    # Delete the course
    response = client.delete(f"/api/v1/courses/{course_id}", headers=auth_headers_lecturer)
    assert response.status_code == 200
    assert response.json()["data"] is None


def test_forbidden_for_student(auth_headers_student):
    response = client.get("/api/v1/courses", headers=auth_headers_student)
    assert response.status_code == 403
    assert response.json()["success"] is False
    assert "Missing required role" in response.json()["message"]
