"""Tests for OpenStack Projects API endpoints."""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from src.main import app


@pytest.fixture
def mock_token():
    """Mock Keycloak token for testing."""
    return "Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.test"


@pytest.fixture
def mock_user():
    """Mock user data."""
    return {
        "sub": "user-123",
        "preferred_username": "testuser",
        "email": "test@example.com",
        "realm_access": {"roles": ["lecturer"]},
    }


@pytest.mark.skip("Requires Keycloak mock and DB setup")
def test_create_credentials(mock_token, mock_user):
    """Test creating OpenStack credentials."""
    client = TestClient(app)
    
    with patch("src.core.auth.verify_jwt_token", return_value=mock_user):
        response = client.post(
            "/api/v1/openstack-projects/new/credentials",
            json={
                "auth_url": "https://openstack.example.com:5000/v3",
                "username": "admin",
                "password": "secretpassword123",
                "user_domain_name": "Default",
                "region_name": "RegionOne",
                "openstack_project_id": "project-abc-123",
                "openstack_project_name": "Test Project",
            },
            headers={"Authorization": mock_token},
        )
    
    assert response.status_code == 201
    data = response.json()["data"]
    
    # Verify password is masked
    assert data["password"] == "********"
    # Verify username is partially masked
    assert "***" in data["username"]
    # Verify other fields
    assert data["auth_url"] == "https://openstack.example.com:5000/v3"
    assert data["openstack_project_name"] == "Test Project"


@pytest.mark.skip("Requires Keycloak mock and DB setup")
def test_get_credentials_masked(mock_token, mock_user):
    """Test retrieving masked credentials."""
    client = TestClient(app)
    project_id = "test-project-id"
    
    with patch("src.core.auth.verify_jwt_token", return_value=mock_user):
        response = client.get(
            f"/api/v1/openstack-projects/{project_id}/credentials",
            headers={"Authorization": mock_token},
        )
    
    assert response.status_code == 200
    data = response.json()["data"]
    
    # Verify credentials are masked
    assert data["password"] == "********"
    assert "***" in data["username"]


@pytest.mark.skip("Requires Keycloak mock and DB setup")
def test_delete_credentials(mock_token, mock_user):
    """Test deleting OpenStack credentials."""
    client = TestClient(app)
    project_id = "test-project-id"
    
    with patch("src.core.auth.verify_jwt_token", return_value=mock_user):
        response = client.delete(
            f"/api/v1/openstack-projects/{project_id}/credentials",
            headers={"Authorization": mock_token},
        )
    
    assert response.status_code == 204


@pytest.mark.skip("Requires Keycloak mock and DB setup")
def test_unauthorized_access(mock_token):
    """Test that unauthorized users cannot access credentials."""
    client = TestClient(app)
    project_id = "other-user-project"
    
    mock_user = {
        "sub": "user-456",  # Different user
        "preferred_username": "otheruser",
        "email": "other@example.com",
        "realm_access": {"roles": ["lecturer"]},
    }
    
    with patch("src.core.auth.verify_jwt_token", return_value=mock_user):
        response = client.get(
            f"/api/v1/openstack-projects/{project_id}/credentials",
            headers={"Authorization": mock_token},
        )
    
    assert response.status_code == 403
