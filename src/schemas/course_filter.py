"""Course filter schemas for request/response validation."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CourseFilterCreate(BaseModel):
    """Schema for creating a course filter."""

    name: str = Field(..., description="Filter-String (z. B. „SQL“)", min_length=1, max_length=255)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v

    model_config = ConfigDict(json_schema_extra={"example": {"name": "SQL"}})


class CourseFilterUpdate(BaseModel):
    """Schema for renaming a course filter."""

    name: Optional[str] = Field(None, description="Neuer Filter-String", min_length=1, max_length=255)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v

    model_config = ConfigDict(json_schema_extra={"example": {"name": "SQL Grundlagen"}})


class CourseFilterResponse(BaseModel):
    """Schema for course filter response."""

    id: str = Field(..., description="Filter-ID")
    name: str = Field(..., description="Filter-String")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "filter-123",
                "name": "SQL",
                "created_at": "2026-06-30T10:00:00Z",
                "updated_at": "2026-06-30T10:00:00Z",
            }
        },
    )
