"""FastAPI dependencies."""
from typing import Annotated, Callable
from fastapi import Request, Depends, Query, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.auth import verify_jwt_token
from src.core.exceptions import AuthenticationError, AuthorizationError
from src.models.user import UserRole


def get_request_id(request: Request) -> str | None:
    """Get request ID from request state."""
    return getattr(request.state, "request_id", None)


# HTTP Bearer token scheme for Swagger UI
security_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
    authorization: str | None = Header(None),
    db: Session = Depends(get_db)
) -> dict:
    """Extract and validate user from JWT token, sync to local database.
    
    This dependency:
    1. Validates JWT token from Keycloak
    2. Extracts user info and roles from token
    3. Syncs user to local database (create/update)
    4. Returns enriched user info with local user_id
    
    Accepts token from either:
    - Authorization header (Bearer scheme via HTTPBearer)
    - Direct Authorization header string (fallback)
    
    Args:
        credentials: Bearer token from security scheme
        authorization: Raw Authorization header value
        db: Database session for user sync
        
    Returns:
        User info dict with:
            - sub: Keycloak user UUID
            - email: User email
            - name: Display name
            - preferred_username: Username
            - roles: List of roles from token
            - user_id: Local database user ID (for foreign keys)
        
    Raises:
        AuthenticationError: If token is missing or invalid
    """
    token = None
    
    # Try HTTPBearer credentials first
    if credentials:
        token = credentials.credentials
    # Fallback to raw Authorization header
    elif authorization:
        if authorization.startswith("Bearer "):
            token = authorization[7:]  # Remove "Bearer " prefix
        else:
            token = authorization
    
    if not token:
        raise AuthenticationError("Missing authentication token")
    
    # Validate token and extract payload
    payload = verify_jwt_token(token)
    
    # Extract roles from token (Keycloak is source of truth)
    roles = payload.get("realm_access", {}).get("roles", [])
    
    # Sync user to local database (create if not exists, update if changed)
    from src.services.user_sync_service import UserSyncService
    
    sync_service = UserSyncService(db)
    user = sync_service.sync_user_from_token(payload)
    
    # Build enriched user info dict
    user_info = {
        "sub": payload.get("sub"),
        "email": payload.get("email"),
        "name": payload.get("name"),
        "preferred_username": payload.get("preferred_username"),
        "roles": roles,  # Roles from Keycloak token (NOT from database)
        "user_id": user.id,  # Local database ID for foreign key relationships
    }
    
    return user_info


def require_roles(*required_roles: UserRole) -> Callable:
    """Dependency factory for role-based access control.
    
    Creates a dependency that checks if the authenticated user has at least
    one of the required roles.
    
    Usage:
        @router.post("/deployments")
        async def create_deployment(
            user: dict = Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER))
        ):
            ...
    
    Args:
        *required_roles: One or more UserRole values required for access
        
    Returns:
        FastAPI dependency function
        
    Raises:
        AuthorizationError: If user lacks all required roles
    """
    async def check_roles(user: dict = Depends(get_current_user)) -> dict:
        """Check if user has required roles."""
        user_roles = user.get("roles", [])
        
        # Check if user has any of the required roles
        has_required_role = any(
            role.value in user_roles for role in required_roles
        )
        
        if not has_required_role:
            required_role_names = [role.value for role in required_roles]
            raise AuthorizationError(
                f"Access denied. Required roles: {', '.join(required_role_names)}"
            )
        
        return user
    
    return check_roles


class PaginationParams:
    """Pagination parameters."""
    
    def __init__(
        self,
        page: int = Query(1, ge=1, description="Page number"),
        page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    ):
        self.page = page
        self.page_size = page_size
        self.offset = (page - 1) * page_size


# Type aliases for dependency injection
RequestID = Annotated[str | None, Depends(get_request_id)]
DBSession = Annotated[Session, Depends(get_db)]
Pagination = Annotated[PaginationParams, Depends()]
CurrentUser = Annotated[dict, Depends(get_current_user)]
