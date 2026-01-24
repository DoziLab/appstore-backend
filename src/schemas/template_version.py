"""Template Version schemas for request/response validation."""
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional, Any


class TemplateVersionCreate(BaseModel):
    """Schema for creating a template version."""
    template_id: str = Field(..., description="ID of the template")
    version: str = Field(..., description="Semantic version (e.g., 0.2.0)", max_length=50)
    git_commit_sha: str = Field(..., description="Git commit SHA for this version", max_length=255)
    is_active: bool = Field(default=True, description="Whether this version is active")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "template_id": "tmpl-123",
                "version": "0.2.0",
                "git_commit_sha": "a1b2c3d4e5f6g7h8i9j0",
                "is_active": True
            }
        }
    )


class TemplateVersionUpdate(BaseModel):
    """Schema for updating a template version."""
    git_commit_sha: Optional[str] = Field(None, description="Git commit SHA for this version", max_length=255)
    is_active: Optional[bool] = Field(None, description="Whether this version is active")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "is_active": False
            }
        }
    )


class TemplateVersionResponse(BaseModel):
    """Schema for template version response."""
    id: str = Field(..., description="Version ID")
    template_id: str = Field(..., description="Template ID")
    version: str = Field(..., description="Semantic version (e.g., 0.2.0)")
    git_commit_sha: str = Field(..., description="Git commit SHA")
    is_active: bool = Field(..., description="Whether this version is active")
    created_at: datetime = Field(..., description="Creation timestamp")
    parameters: Optional[list[dict[str, Any]]] = Field(None, description="Template parameters from app.yaml")
    
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "ver-123",
                "template_id": "tmpl-123",
                "version": "0.2.0",
                "git_commit_sha": "a1b2c3d4e5f6g7h8i9j0",
                "is_active": True,
                "created_at": "2024-11-27T10:00:00Z",
                "parameters": [
                    {
                        "name": "image",
                        "type": "string",
                        "default": "Ubuntu 22.04",
                        "required": True
                    }
                ]
            }
        }
    )


class TemplateVersionWithFilesResponse(TemplateVersionResponse):
    """Schema for template version response with file count."""
    file_count: int = Field(..., description="Number of files in this version")
    
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "ver-123",
                "template_id": "tmpl-123",
                "version": "0.2.0",
                "git_commit_sha": "a1b2c3d4e5f6g7h8i9j0",
                "is_active": True,
                "created_at": "2024-11-27T10:00:00Z",
                "file_count": 3,
                "parameters": [
                    {
                        "name": "image",
                        "type": "string",
                        "default": "Ubuntu 22.04",
                        "required": True
                    }
                ]
            }
        }
    )
