"""Standardized response models for API endpoints."""
from datetime import datetime
from typing import Generic, TypeVar, Any
from pydantic import BaseModel, Field

T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    """Standard API response format."""
    
    success: bool = Field(..., description="Whether the operation was successful")
    message: str | None = Field(None, description="Human-readable message")
    data: T | None = Field(None, description="Response payload")
    errors: Any | None = Field(None, description="Error details if any")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Response timestamp")
    request_id: str | None = Field(None, description="Unique request identifier")
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "Operation successful",
                "data": {"id": "123", "name": "Example"},
                "errors": None,
                "timestamp": "2024-11-27T10:00:00Z",
                "request_id": "req-123-456"
            }
        }


class PaginationMeta(BaseModel):
    """Pagination metadata."""
    
    page: int = Field(..., description="Current page number")
    page_size: int = Field(..., description="Number of items per page")
    total_items: int = Field(..., description="Total number of items")
    total_pages: int = Field(..., description="Total number of pages")
    
    @staticmethod
    def calculate_total_pages(total_items: int, page_size: int) -> int:
        """Calculate total pages."""
        return (total_items + page_size - 1) // page_size if page_size > 0 else 0


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated API response format."""
    
    success: bool = Field(..., description="Whether the operation was successful")
    message: str | None = Field(None, description="Human-readable message")
    data: list[T] = Field(..., description="List of items for current page")
    pagination: PaginationMeta = Field(..., description="Pagination metadata")
    errors: Any | None = Field(None, description="Error details if any")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Response timestamp")
    request_id: str | None = Field(None, description="Unique request identifier")
