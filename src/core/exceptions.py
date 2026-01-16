"""Centralized exception handling for the application.

This module provides custom exception handlers for FastAPI to ensure
consistent error responses across all endpoints using ResponseBuilder.
"""
import logging

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .response_builder import ResponseBuilder

logger = logging.getLogger(__name__)


# Custom domain exceptions
class NotFoundException(StarletteHTTPException):
    """Exception raised when a resource is not found."""
    
    def __init__(self, message: str = "Resource not found"):
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=message)


class ForbiddenException(StarletteHTTPException):
    """Exception raised when user lacks permission for an action."""
    
    def __init__(self, message: str = "You do not have permission to perform this action"):
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=message)


class BadRequestException(StarletteHTTPException):
    """Exception raised for invalid client requests."""
    
    def __init__(self, message: str = "Invalid request"):
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=message)


class ConflictException(StarletteHTTPException):
    """Exception raised when request conflicts with current state."""
    
    def __init__(self, message: str = "Request conflicts with current state"):
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=message)

        
class AuthenticationError(Exception):
    """Raised when token validation fails."""
    pass


class AuthorizationError(Exception):
    """Raised when user lacks required permissions."""
    pass


async def http_exception_handler(
    request: Request, 
    exc: StarletteHTTPException
) -> JSONResponse:
    """Handle HTTP exceptions with standardized response format.
    
    Catches HTTPException raised throughout the application and formats
    them using ResponseBuilder for consistency.
    
    Args:
        request: The FastAPI request object
        exc: The HTTP exception that was raised
        
    Returns:
        Standardized JSON error response
    """
    request_id = getattr(request.state, "request_id", None)
    
    # Extract user info if available
    user_id = None
    user_email = None
    try:
        if hasattr(request.state, 'user'):
            user_id = str(request.state.user.id) if hasattr(request.state.user, 'id') else None
            user_email = request.state.user.email if hasattr(request.state.user, 'email') else None
    except Exception:
        pass
    
    logger.warning(
        f"HTTP {exc.status_code} exception on {request.method} {request.url.path}",
        extra={
            "status_code": exc.status_code,
            "detail": str(exc.detail),
            "method": request.method,
            "path": request.url.path,
            "query_params": dict(request.query_params) if request.query_params else None,
            "user_id": user_id,
            "user_email": user_email,
            "client_host": request.client.host if request.client else None,
            "user_agent": request.headers.get('user-agent'),
            "request_id": request_id,
            "event": "http_exception"
        }
    )
    
    return ResponseBuilder.error(
        message=str(exc.detail),
        status_code=exc.status_code,
        request_id=request_id,
    )


async def validation_exception_handler(
    request: Request, 
    exc: RequestValidationError
) -> JSONResponse:
    """Handle request validation errors (422).
    
    Formats Pydantic validation errors into a structured error response.
    
    Args:
        request: The FastAPI request object
        exc: The validation error exception
        
    Returns:
        Standardized JSON validation error response with field-level details
    """
    request_id = getattr(request.state, "request_id", None)
    
    # Extract user info if available
    user_id = None
    try:
        if hasattr(request.state, 'user'):
            user_id = str(request.state.user.id) if hasattr(request.state.user, 'id') else None
    except Exception:
        pass
    
    # Format validation errors into structured list
    errors = []
    for error in exc.errors():
        field_path = ".".join(str(loc) for loc in error["loc"])
        errors.append({
            "field": field_path,
            "message": error["msg"],
            "type": error["type"],
        })
    
    logger.warning(
        f"Validation error on {request.method} {request.url.path}: {len(errors)} field(s)",
        extra={
            "error_count": len(errors),
            "method": request.method,
            "path": request.url.path,
            "errors": errors,
            "user_id": user_id,
            "client_host": request.client.host if request.client else None,
            "request_id": request_id,
            "event": "validation_error"
        }
    )
    
    return ResponseBuilder.validation_error(
        message="Request validation failed",
        errors=errors,
        request_id=request_id,
    )


async def authentication_exception_handler(
    request: Request,
    exc: AuthenticationError
) -> JSONResponse:
    """Handle authentication errors (401 Unauthorized).
    
    Args:
        request: The FastAPI request object
        exc: The authentication error exception
        
    Returns:
        Standardized JSON error response with 401 status
    """
    request_id = getattr(request.state, "request_id", None)
    
    logger.warning(
        f"Authentication error on {request.method} {request.url.path}: {str(exc)}",
        extra={
            "method": request.method,
            "path": request.url.path,
            "client_host": request.client.host if request.client else None,
            "user_agent": request.headers.get('user-agent'),
            "authorization_header_present": 'authorization' in request.headers,
            "request_id": request_id,
            "event": "authentication_error"
        }
    )
    
    return ResponseBuilder.error(
        message=str(exc) or "Authentication failed",
        status_code=401,
        request_id=request_id,
    )


async def authorization_exception_handler(
    request: Request,
    exc: AuthorizationError
) -> JSONResponse:
    """Handle authorization errors (403 Forbidden).
    
    Args:
        request: The FastAPI request object
        exc: The authorization error exception
        
    Returns:
        Standardized JSON error response with 403 status
    """
    request_id = getattr(request.state, "request_id", None)
    
    # Extract user info if available
    user_id = None
    user_roles = None
    try:
        if hasattr(request.state, 'user'):
            user_id = str(request.state.user.id) if hasattr(request.state.user, 'id') else None
            user_roles = request.state.user.roles if hasattr(request.state.user, 'roles') else None
    except Exception:
        pass
    
    logger.warning(
        f"Authorization error on {request.method} {request.url.path}: {str(exc)}",
        extra={
            "method": request.method,
            "path": request.url.path,
            "user_id": user_id,
            "user_roles": user_roles,
            "request_id": request_id,
            "event": "authorization_error"
        }
    )
    
    return ResponseBuilder.error(
        message=str(exc) or "Insufficient permissions",
        status_code=403,
        request_id=request_id,
    )


async def generic_exception_handler(
    request: Request, 
    exc: Exception
) -> JSONResponse:
    """Handle unhandled exceptions (500).
    
    Catches any unexpected exceptions and returns a generic error message
    to avoid leaking implementation details.
    
    Args:
        request: The FastAPI request object
        exc: The unhandled exception
        
    Returns:
        Standardized JSON server error response
    """
    request_id = getattr(request.state, "request_id", None)
    
    # Extract user info if available
    user_id = None
    user_email = None
    try:
        if hasattr(request.state, 'user'):
            user_id = str(request.state.user.id) if hasattr(request.state.user, 'id') else None
            user_email = request.state.user.email if hasattr(request.state.user, 'email') else None
    except Exception:
        pass
    
    logger.error(
        f"Unhandled exception on {request.method} {request.url.path}: {type(exc).__name__}",
        extra={
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "method": request.method,
            "path": request.url.path,
            "query_params": dict(request.query_params) if request.query_params else None,
            "user_id": user_id,
            "user_email": user_email,
            "client_host": request.client.host if request.client else None,
            "user_agent": request.headers.get('user-agent'),
            "request_id": request_id,
            "event": "unhandled_exception"
        },
        exc_info=True,  # Include full traceback in logs
    )
    
    return ResponseBuilder.server_error(
        message="An unexpected error occurred. Please try again later.",
        request_id=request_id,
    )


def register_exception_handlers(app) -> None:
    """Register all exception handlers with the FastAPI application.
    
    This should be called during application startup to ensure all
    exceptions are properly caught and formatted.
    
    Args:
        app: The FastAPI application instance
    """
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(AuthenticationError, authentication_exception_handler)
    app.add_exception_handler(AuthorizationError, authorization_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)
    
    logger.info("Exception handlers registered successfully")
