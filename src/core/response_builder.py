"""Standardized API response builder.

This module provides the ResponseBuilder class for creating consistent
JSON responses across all API endpoints. All responses follow the same
structure defined in responses.py (APIResponse and PaginatedResponse).
"""
from datetime import datetime
from typing import Any, List
import logging

from fastapi import status
from fastapi.responses import JSONResponse

from .responses import APIResponse, PaginatedResponse, PaginationMeta

logger = logging.getLogger(__name__)


class ResponseBuilder:
    """Builder for creating standardized API responses.
    
    All API endpoints should use these methods to ensure consistent
    response format across the application.
    """
    
    @staticmethod
    def success(
        data: Any = None,
        message: str = "Operation successful",
        request_id: str | None = None,
        status_code: int = status.HTTP_200_OK,
    ) -> JSONResponse:
        """Build a successful response.
        
        Args:
            data: Response payload (will be serialized to JSON)
            message: Human-readable success message
            request_id: Unique request identifier from middleware
            status_code: HTTP status code (default 200)
            
        Returns:
            JSONResponse with standardized format
        """
        response_data = APIResponse(
            success=True,
            message=message,
            data=data,
            errors=None,
            timestamp=datetime.utcnow(),
            request_id=request_id,
        )
        return JSONResponse(
            content=response_data.model_dump(mode="json"),
            status_code=status_code,
        )
    
    @staticmethod
    def created(
        data: Any = None,
        message: str = "Resource created successfully",
        request_id: str | None = None,
    ) -> JSONResponse:
        """Build a created (201) response.
        
        Args:
            data: Created resource data
            message: Success message
            request_id: Unique request identifier
            
        Returns:
            JSONResponse with 201 status code
        """
        return ResponseBuilder.success(
            data=data,
            message=message,
            request_id=request_id,
            status_code=status.HTTP_201_CREATED,
        )
    
    @staticmethod
    def no_content(
        message: str = "Operation successful",
        request_id: str | None = None,
    ) -> JSONResponse:
        """Build a no content (204) response.
        
        Used for successful operations that don't return data (e.g., DELETE).
        
        Args:
            message: Success message
            request_id: Unique request identifier
            
        Returns:
            JSONResponse with 204 status code
        """
        response_data = APIResponse(
            success=True,
            message=message,
            data=None,
            errors=None,
            timestamp=datetime.utcnow(),
            request_id=request_id,
        )
        return JSONResponse(
            content=response_data.model_dump(mode="json"),
            status_code=status.HTTP_204_NO_CONTENT,
        )
    
    @staticmethod
    def error(
        message: str = "An error occurred",
        errors: Any = None,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        request_id: str | None = None,
    ) -> JSONResponse:
        """Build an error response.
        
        Args:
            message: Human-readable error message
            errors: Detailed error information (e.g., validation errors list)
            status_code: HTTP status code (default 400)
            request_id: Unique request identifier
            
        Returns:
            JSONResponse with error format
        """
        response_data = APIResponse(
            success=False,
            message=message,
            data=None,
            errors=errors,
            timestamp=datetime.utcnow(),
            request_id=request_id,
        )
        return JSONResponse(
            content=response_data.model_dump(mode="json"),
            status_code=status_code,
        )
    
    @staticmethod
    def not_found(
        message: str | None = None,
        resource: str = "Resource",
        request_id: str | None = None,
    ) -> JSONResponse:
        """Build a not found (404) response.
        
        Args:
            message: Custom error message. If None, generates "{resource} not found"
            resource: Resource type name for default message
            request_id: Unique request identifier
            
        Returns:
            JSONResponse with 404 status code
        """
        if message is None:
            message = f"{resource} not found"
        
        return ResponseBuilder.error(
            message=message,
            status_code=status.HTTP_404_NOT_FOUND,
            request_id=request_id,
        )
    
    @staticmethod
    def validation_error(
        message: str = "Validation failed",
        errors: Any = None,
        request_id: str | None = None,
    ) -> JSONResponse:
        """Build a validation error (422) response.
        
        Args:
            message: Human-readable error message
            errors: List of validation errors with field/message details
            request_id: Unique request identifier
            
        Returns:
            JSONResponse with 422 status code
        """
        return ResponseBuilder.error(
            message=message,
            errors=errors,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            request_id=request_id,
        )
    
    @staticmethod
    def unauthorized(
        message: str = "Authentication required",
        request_id: str | None = None,
    ) -> JSONResponse:
        """Build an unauthorized (401) response.
        
        Args:
            message: Error message
            request_id: Unique request identifier
            
        Returns:
            JSONResponse with 401 status code
        """
        return ResponseBuilder.error(
            message=message,
            status_code=status.HTTP_401_UNAUTHORIZED,
            request_id=request_id,
        )
    
    @staticmethod
    def forbidden(
        message: str = "Access forbidden",
        request_id: str | None = None,
    ) -> JSONResponse:
        """Build a forbidden (403) response.
        
        Args:
            message: Error message
            request_id: Unique request identifier
            
        Returns:
            JSONResponse with 403 status code
        """
        return ResponseBuilder.error(
            message=message,
            status_code=status.HTTP_403_FORBIDDEN,
            request_id=request_id,
        )
    
    @staticmethod
    def server_error(
        message: str = "Internal server error",
        request_id: str | None = None,
    ) -> JSONResponse:
        """Build a server error (500) response.
        
        Args:
            message: Error message (should be generic for security)
            request_id: Unique request identifier for tracking
            
        Returns:
            JSONResponse with 500 status code
        """
        logger.error(
            f"Internal server error response generated [request_id: {request_id}]"
        )
        return ResponseBuilder.error(
            message=message,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            request_id=request_id,
        )
    
    @staticmethod
    def paginated(
        data: List[Any],
        page: int,
        page_size: int,
        total: int,
        message: str = "Data retrieved successfully",
        request_id: str | None = None,
    ) -> JSONResponse:
        """Build a paginated response.
        
        Args:
            data: List of items for current page
            page: Current page number (1-indexed)
            page_size: Number of items per page
            total: Total number of items across all pages
            message: Success message
            request_id: Unique request identifier
            
        Returns:
            JSONResponse with pagination metadata
        """
        total_pages = PaginationMeta.calculate_total_pages(total, page_size)
        
        pagination_meta = PaginationMeta(
            page=page,
            page_size=page_size,
            total_items=total,
            total_pages=total_pages,
        )
        
        response_data = PaginatedResponse(
            success=True,
            message=message,
            data=data,
            pagination=pagination_meta,
            errors=None,
            timestamp=datetime.utcnow(),
            request_id=request_id,
        )
        
        return JSONResponse(
            content=response_data.model_dump(mode="json"),
            status_code=status.HTTP_200_OK,
        )
