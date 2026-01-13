"""Unit tests for Keycloak authentication."""
import pytest
from unittest.mock import Mock, patch
from fastapi import HTTPException

from src.core.auth import verify_jwt_token, get_current_user
from src.core.dependencies import require_roles
from src.core.exceptions import AuthorizationError
from src.models.user import UserRole


@pytest.fixture
def mock_token_payload():
    """Mock decoded JWT token payload."""
    return {
        "sub": "user-123",
        "email": "lecturer@example.com",
        "name": "Test Lecturer",
        "preferred_username": "test.lecturer",
        "azp": "appstore-frontend",
        "realm_access": {
            "roles": ["lecturer", "offline_access"]
        },
        "resource_access": {
            "appstore-frontend": {
                "roles": ["user"]
            }
        }
    }


@patch("src.core.auth.get_keycloak_public_keys")
@patch("src.core.auth.jwt.decode")
@patch("src.core.auth.jwt.get_unverified_header")
def test_verify_jwt_token_success(
    mock_get_header, mock_jwt_decode, mock_get_keys, mock_token_payload
):
    """Test successful token verification."""
    # Setup mocks
    mock_get_header.return_value = {"kid": "test-key-id"}
    mock_get_keys.return_value = {
        "keys": [{"kid": "test-key-id", "kty": "RSA", "use": "sig"}]
    }
    mock_jwt_decode.return_value = mock_token_payload
    
    result = verify_jwt_token("valid.jwt.token")
    
    assert result == mock_token_payload
    assert result["sub"] == "user-123"
    assert result["azp"] == "appstore-frontend"


@patch("src.core.auth.get_keycloak_public_keys")
@patch("src.core.auth.jwt.get_unverified_header")
def test_verify_jwt_token_missing_kid(mock_get_header, mock_get_keys):
    """Test token verification fails when kid is missing."""
    mock_get_header.return_value = {}
    
    with pytest.raises(HTTPException) as exc_info:
        verify_jwt_token("invalid.jwt.token")
    
    assert exc_info.value.status_code == 401
    assert "missing key ID" in str(exc_info.value.detail).lower()


@patch("src.core.auth.get_keycloak_public_keys")
@patch("src.core.auth.jwt.decode")
@patch("src.core.auth.jwt.get_unverified_header")
def test_verify_jwt_token_untrusted_client(
    mock_get_header, mock_jwt_decode, mock_get_keys
):
    """Test token verification fails for untrusted client."""
    mock_get_header.return_value = {"kid": "test-key-id"}
    mock_get_keys.return_value = {
        "keys": [{"kid": "test-key-id", "kty": "RSA", "use": "sig"}]
    }
    mock_jwt_decode.return_value = {
        "sub": "user-123",
        "azp": "untrusted-client"
    }
    
    with pytest.raises(HTTPException) as exc_info:
        verify_jwt_token("untrusted.jwt.token")
    
    assert exc_info.value.status_code == 401
    assert "untrusted client" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
@patch("src.core.auth.verify_jwt_token")
async def test_get_current_user_with_bearer_token(mock_verify, mock_token_payload):
    """Test get_current_user with valid Bearer token."""
    mock_credentials = Mock()
    mock_credentials.credentials = "valid.jwt.token"
    mock_verify.return_value = mock_token_payload
    
    user_info = await get_current_user(credentials=mock_credentials)
    
    assert user_info["sub"] == "user-123"
    assert user_info["email"] == "lecturer@example.com"


@pytest.mark.asyncio
async def test_require_roles_success():
    """Test require_roles allows access for user with correct role."""
    mock_user = {
        "sub": "user-123",
        "roles": ["lecturer"]
    }
    
    check_roles = require_roles(UserRole.LECTURER)
    result = await check_roles(user=mock_user)
    
    assert result == mock_user


@pytest.mark.asyncio
async def test_require_roles_forbidden():
    """Test require_roles denies access for user without role."""
    mock_user = {
        "sub": "user-123",
        "roles": ["student"]
    }
    
    check_roles = require_roles(UserRole.LECTURER, UserRole.ADMIN)
    
    with pytest.raises(AuthorizationError, match="Access denied"):
        await check_roles(user=mock_user)


@pytest.mark.asyncio
async def test_require_roles_admin_allowed():
    """Test require_roles allows admin access."""
    mock_user = {
        "sub": "user-123",
        "roles": ["admin"]
    }
    
    check_roles = require_roles(UserRole.ADMIN, UserRole.LECTURER)
    result = await check_roles(user=mock_user)
    
    assert result == mock_user
