"""Keycloak authentication and authorization."""
from typing import Any
from functools import lru_cache
import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from jose.backends import RSAKey

from src.core.config import get_settings


security = HTTPBearer()


@lru_cache(maxsize=1)
def get_keycloak_public_keys() -> dict[str, Any]:
    """Fetch and cache Keycloak public keys for JWT verification.
    
    Keys are cached to avoid repeated network calls.
    Cache is cleared on application restart.
    """
    settings = get_settings()
    certs_url = f"{settings.keycloak_realm_url}/protocol/openid-connect/certs"
    
    try:
        response = httpx.get(certs_url, timeout=10.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        raise RuntimeError(f"Failed to fetch Keycloak public keys: {e}")


def verify_jwt_token(token: str) -> dict[str, Any]:
    """Verify JWT token from Keycloak and extract claims.
    
    Args:
        token: JWT access token string
        
    Returns:
        Token payload with user claims
        
    Raises:
        HTTPException: If token is invalid, expired, or verification fails
    """
    settings = get_settings()
    
    try:
        # Get unverified header to extract kid (key ID)
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        
        if not kid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token missing key ID (kid)"
            )
        
        # Fetch Keycloak public keys
        jwks = get_keycloak_public_keys()
        
        # Find matching key by kid
        public_key: Any = None
        for key_data in jwks.get("keys", []):
            if key_data.get("kid") == kid:
                # Convert JWK to PEM format for python-jose
                public_key = RSAKey(key_data, algorithm="RS256")  # type: ignore[misc]
                break
        
        if public_key is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unable to find matching public key"
            )
        
        # Verify and decode token
        # Note: Tokens issued by appstore-frontend may not have appstore-backend in audience
        # We verify the authorized party (azp) instead for cross-client validation
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            issuer=settings.keycloak_realm_url,
            options={
                "verify_signature": True,
                "verify_aud": False,  # Allow tokens from frontend client
                "verify_iss": True,
                "verify_exp": True,
            }
        )
        
        # Validate authorized party (azp) - must be from trusted client
        azp = payload.get("azp")
        if azp not in ["appstore-frontend", "appstore-backend"]:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Token from untrusted client: {azp}"
            )
        
        return payload
        
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict[str, Any]:
    """FastAPI dependency to extract and verify current user from JWT token.
    
    Returns:
        User claims from token including:
        - sub: User ID (UUID)
        - preferred_username: Username
        - email: User email
        - name: Full name
        - realm_access.roles: List of realm roles
        - resource_access: Client-specific roles
    
    Usage:
        @router.get("/protected")
        async def protected_route(user: dict = Depends(get_current_user)):
            user_id = user["sub"]
            username = user["preferred_username"]
    """
    token = credentials.credentials
    return verify_jwt_token(token)


def require_role(required_role: str):
    """Dependency factory to require specific Keycloak realm role.
    
    Args:
        required_role: Role name to check (e.g., "lecturer", "admin", "student")
        
    Returns:
        Dependency function that validates role presence
        
    Raises:
        HTTPException 403: If user doesn't have required role
        
    Usage:
        @router.post("/templates", dependencies=[Depends(require_role("lecturer"))])
        async def create_template(...):
            pass
    """
    async def check_role(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        realm_roles = user.get("realm_access", {}).get("roles", [])
        
        if required_role not in realm_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required role: {required_role}"
            )
        
        return user
    
    return check_role


def require_client_role(client_id: str, required_role: str):
    """Dependency factory to require specific client-level role.
    
    Args:
        client_id: Client ID to check roles for (e.g., "appstore-backend")
        required_role: Role name to check (e.g., "read:templates", "write:deployments")
        
    Returns:
        Dependency function that validates client role presence
        
    Raises:
        HTTPException 403: If user doesn't have required client role
        
    Usage:
        @router.post("/deployments")
        async def create_deployment(
            user: dict = Depends(require_client_role("appstore-backend", "write:deployments"))
        ):
            pass
    """
    async def check_client_role(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        resource_access = user.get("resource_access", {})
        client_roles = resource_access.get(client_id, {}).get("roles", [])
        
        if required_role not in client_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required client role: {client_id}.{required_role}"
            )
        
        return user
    
    return check_client_role


def get_user_id(user: dict[str, Any] = Depends(get_current_user)) -> str:
    """Extract user ID from token claims.
    
    Returns:
        User UUID as string from 'sub' claim
        
    Usage:
        @router.get("/my-deployments")
        async def my_deployments(user_id: str = Depends(get_user_id)):
            return db.query(Deployment).filter_by(lecturer_id=user_id).all()
    """
    return user["sub"]


def is_lecturer(user: dict[str, Any] = Depends(get_current_user)) -> bool:
    """Check if user has lecturer role.
    
    Returns:
        True if user is lecturer, False otherwise
    """
    realm_roles = user.get("realm_access", {}).get("roles", [])
    return "lecturer" in realm_roles


def is_admin(user: dict[str, Any] = Depends(get_current_user)) -> bool:
    """Check if user has admin role.
    
    Returns:
        True if user is admin, False otherwise
    """
    realm_roles = user.get("realm_access", {}).get("roles", [])
    return "admin" in realm_roles