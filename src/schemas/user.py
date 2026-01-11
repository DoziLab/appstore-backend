"""User schemas for request/response validation."""
from pydantic import BaseModel, Field, EmailStr, ConfigDict
from datetime import datetime
from typing import Optional


class UserCreate(BaseModel):
    """Schema for creating a user."""
    external_id: str = Field(..., description="External ID (e.g., from SSO)", max_length=255)
    email: EmailStr = Field(..., description="User email address")
    name: str = Field(..., description="User full name", max_length=255)
    role: str = Field(..., description="User role (admin/lecturer/student)")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "external_id": "sso-12345",
                "email": "john.doe@example.com",
                "name": "John Doe",
                "role": "student"
            }
        }
    )


class UserUpdate(BaseModel):
    """Schema for updating a user."""
    email: Optional[EmailStr] = Field(None, description="User email address")
    name: Optional[str] = Field(None, description="User full name", max_length=255)
    role: Optional[str] = Field(None, description="User role (admin/lecturer/student)")
    is_active: Optional[bool] = Field(None, description="User active status")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "John Updated Doe",
                "is_active": false
            }
        }
    )


class UserResponse(BaseModel):
    """Schema for user response."""
    id: str = Field(..., description="User ID")
    external_id: str = Field(..., description="External ID")
    email: str = Field(..., description="User email address")
    name: str = Field(..., description="User full name")
    role: str = Field(..., description="User role")
    is_active: bool = Field(..., description="User active status")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "user-123",
                "external_id": "sso-12345",
                "email": "john.doe@example.com",
                "name": "John Doe",
                "role": "student",
                "is_active": true,
                "created_at": "2024-11-27T10:00:00Z",
                "updated_at": "2024-11-27T10:00:00Z"
            }
        }
    )
