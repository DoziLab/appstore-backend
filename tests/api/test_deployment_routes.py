"""Tests for deployment API endpoints."""
import pytest
from unittest.mock import Mock, patch
from uuid import uuid4
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from jose import jwt

from src.main import app
from src.core.config import get_settings
from src.models.deployment import DeploymentStatus
from src.models.user import UserRole


settings = get_settings()


def create_test_jwt(user_id: str = "test-user", role: str = "ADMIN") -> str:
    """Create a test JWT token.
    
    Args:
        user_id: User external ID
        role: User role
        
    Returns:
        JWT token string
    """
    payload = {
        "sub": user_id,
        "email": "test@example.com",
        "name": "Test User",
        "role": role,
        "exp": int(datetime.now(timezone.utc).timestamp()) + 3600,
        "iat": int(datetime.now(timezone.utc).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


@pytest.fixture
def client():
    """Test client fixture."""
    return TestClient(app)


@pytest.fixture
def admin_token():
    """Admin JWT token fixture."""
    return create_test_jwt(role="ADMIN")


@pytest.fixture
def lecturer_token():
    """Lecturer JWT token fixture."""
    return create_test_jwt(role="LECTURER")


@pytest.fixture
def student_token():
    """Student JWT token fixture."""
    return create_test_jwt(role="STUDENT")


class TestCreateDeployment:
    """Tests for POST /deployments endpoint."""
    
    def test_create_deployment_as_admin(self, client, admin_token):
        """Test creating deployment as admin user."""
        payload = {
            "template_ref": "https://github.com/org/template-repo.git",
            "name": "test-deployment",
            "course_id": str(uuid4()),
        }
        
        with patch("src.api.deployments.DeploymentService") as mock_service:
            mock_deployment = Mock()
            mock_deployment.id = uuid4()
            mock_deployment.name = payload["name"]
            mock_deployment.template_ref = payload["template_ref"]
            mock_deployment.course_id = payload["course_id"]
            mock_deployment.status = DeploymentStatus.PENDING
            mock_deployment.stack_id = None
            mock_deployment.error_message = None
            mock_deployment.created_at = datetime.now(timezone.utc)
            mock_deployment.updated_at = None
            
            mock_service.return_value.create_deployment.return_value = mock_deployment
            
            response = client.post(
                "/deployments",
                json=payload,
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            
            assert response.status_code == 201
            data = response.json()
            assert data["success"] is True
            assert data["data"]["name"] == payload["name"]
            assert data["data"]["template_ref"] == payload["template_ref"]
    
    def test_create_deployment_as_lecturer(self, client, lecturer_token):
        """Test creating deployment as lecturer user."""
        payload = {
            "template_ref": "org/template-repo",
            "course_id": str(uuid4()),
        }
        
        with patch("src.api.deployments.DeploymentService") as mock_service:
            mock_deployment = Mock()
            mock_deployment.id = uuid4()
            mock_deployment.name = "template-repo-deployment"
            mock_deployment.template_ref = payload["template_ref"]
            mock_deployment.course_id = payload["course_id"]
            mock_deployment.status = DeploymentStatus.PENDING
            mock_deployment.stack_id = None
            mock_deployment.error_message = None
            mock_deployment.created_at = datetime.now(timezone.utc)
            mock_deployment.updated_at = None
            
            mock_service.return_value.create_deployment.return_value = mock_deployment
            
            response = client.post(
                "/deployments",
                json=payload,
                headers={"Authorization": f"Bearer {lecturer_token}"}
            )
            
            assert response.status_code == 201
            data = response.json()
            assert data["success"] is True
    
    def test_create_deployment_as_student_forbidden(self, client, student_token):
        """Test that students cannot create deployments."""
        payload = {
            "template_ref": "https://github.com/org/template-repo.git",
            "course_id": str(uuid4()),
        }
        
        response = client.post(
            "/deployments",
            json=payload,
            headers={"Authorization": f"Bearer {student_token}"}
        )
        
        assert response.status_code == 403
        data = response.json()
        assert data["success"] is False
        assert "Insufficient permissions" in data["message"]
    
    def test_create_deployment_without_auth(self, client):
        """Test that unauthenticated requests are rejected."""
        payload = {
            "template_ref": "https://github.com/org/template-repo.git",
            "course_id": str(uuid4()),
        }
        
        response = client.post("/deployments", json=payload)
        
        assert response.status_code == 403
    
    def test_create_deployment_invalid_template_ref(self, client, admin_token):
        """Test validation error for invalid template_ref."""
        payload = {
            "template_ref": "invalid template ref!!!",
            "course_id": str(uuid4()),
        }
        
        with patch("src.api.deployments.DeploymentService") as mock_service:
            mock_service.return_value.create_deployment.side_effect = ValueError(
                "Invalid template_ref format"
            )
            
            response = client.post(
                "/deployments",
                json=payload,
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            
            assert response.status_code == 400
            data = response.json()
            assert "Invalid template_ref" in str(data["detail"])
