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
    
    logger.warning(
        f"HTTP {exc.status_code} exception on {request.method} {request.url.path}",
        extra={
            "status_code": exc.status_code,
            "detail": str(exc.detail),
            "method": request.method,
            "path": request.url.path,
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
            "request_id": request_id,
            "event": "validation_error"
        }
    )
    
    return ResponseBuilder.validation_error(
        message="Request validation failed",
        errors=errors,
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
    
    logger.error(
        f"Unhandled exception on {request.method} {request.url.path}: {type(exc).__name__}",
        extra={
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "method": request.method,
            "path": request.url.path,
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
    app.add_exception_handler(Exception, generic_exception_handler)
    
    logger.info("Exception handlers registered successfully")
