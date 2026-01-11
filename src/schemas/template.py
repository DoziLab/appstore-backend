"""Template schemas for request/response validation."""
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional


class TemplateCreate(BaseModel):
    """Schema for creating a template."""
    name: str = Field(..., description="Name of the template", max_length=255)
    description: Optional[str] = Field(None, description="Template description")
    repo_url: str = Field(..., description="Git repository URL", max_length=500)
    visibility: str = Field(default="private", description="Template visibility (private/public)")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Python Flask Template",
                "description": "A template for Flask web applications",
                "repo_url": "https://github.com/example/flask-template",
                "visibility": "public"
            }
        }
    )


class TemplateUpdate(BaseModel):
    """Schema for updating a template."""
    name: Optional[str] = Field(None, description="Name of the template", max_length=255)
    description: Optional[str] = Field(None, description="Template description")
    repo_url: Optional[str] = Field(None, description="Git repository URL", max_length=500)
    visibility: Optional[str] = Field(None, description="Template visibility (private/public)")
    approval_status: Optional[str] = Field(None, description="Approval status")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Updated Template Name",
                "approval_status": "approved"
            }
        }
    )


class TemplateResponse(BaseModel):
    """Schema for template response."""
    id: str = Field(..., description="Template ID")
    name: str = Field(..., description="Template name")
    description: Optional[str] = Field(None, description="Template description")
    owner_id: str = Field(..., description="Owner user ID")
    repo_url: str = Field(..., description="Git repository URL")
    visibility: str = Field(..., description="Template visibility")
    approval_status: str = Field(..., description="Approval status")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "tmpl-123",
                "name": "Python Flask Template",
                "description": "A template for Flask web applications",
                "owner_id": "user-456",
                "repo_url": "https://github.com/example/flask-template",
                "visibility": "public",
                "approval_status": "approved",
                "created_at": "2024-11-27T10:00:00Z",
                "updated_at": "2024-11-27T10:00:00Z"
            }
        }
    )
