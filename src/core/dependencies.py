"""FastAPI dependencies."""
from typing import Generator, Annotated
from fastapi import Request, Depends, Query, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from src.core.database import SessionLocal
from src.core.auth import decode_jwt_token
from src.models.user import User, UserRole
from src.repositories.user_repository import UserRepository
from src.schemas.user import UserCreate


security = HTTPBearer()


def get_request_id(request: Request) -> str | None:
    """Get request ID from request state."""
    return getattr(request.state, "request_id", None)


def get_db() -> Generator[Session, None, None]:
    """Dependency to get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


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


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """Get current authenticated user from JWT token.
    
    Args:
        credentials: HTTP Bearer token from Authorization header
        db: Database session
        
    Returns:
        User object for the authenticated user
        
    Raises:
        HTTPException: If token is invalid, expired, or user not found/inactive
    """
    # Decode and validate JWT token
    token_payload = decode_jwt_token(credentials.credentials)
    
    # Get or create user from token payload
    user_repo = UserRepository(db)
    user = user_repo.get_by_external_id(token_payload.sub)
    
    if not user:
        # Auto-create user on first login (JIT provisioning)
        user_data = UserCreate(
            external_id=token_payload.sub,
            email=token_payload.email,
            name=token_payload.name,
            role=UserRole(token_payload.role),
        )
        user = user_repo.create(user_data.model_dump())
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )
    
    return user


def require_role(*allowed_roles: UserRole):
    """Dependency factory to require specific user roles.
    
    Args:
        allowed_roles: Roles that are allowed to access the endpoint
        
    Returns:
        Dependency function that checks user role
        
    Example:
        @router.post("/admin-only")
        async def admin_endpoint(user: CurrentUser = Depends(require_role(UserRole.ADMIN))):
            ...
    """
    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required roles: {', '.join(r.value for r in allowed_roles)}",
            )
        return current_user
    return role_checker


# Type aliases for dependency injection
RequestID = Annotated[str | None, Depends(get_request_id)]
DBSession = Annotated[Session, Depends(get_db)]
Pagination = Annotated[PaginationParams, Depends()]
CurrentUser = Annotated[User, Depends(get_current_user)]
