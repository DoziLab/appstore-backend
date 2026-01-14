"""Template Version File schemas for request/response validation."""
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional


class TemplateVersionFileCreate(BaseModel):
    """Schema for creating a template version file."""
    template_version_id: str = Field(..., description="ID of the template version")
    file_name: str = Field(..., description="Name of the file", max_length=255)
    file_type: str = Field(..., description="Type of file (heat_template, cloud_init, etc.)")
    file_path: str = Field(..., description="Relative path in the git repository", max_length=500)
    content: Optional[str] = Field(None, description="File content (cached)")
    file_size: Optional[int] = Field(None, description="File size in bytes")
    description: Optional[str] = Field(None, description="File description")
    is_primary: bool = Field(default=False, description="Whether this is the primary deployment file")
    order: int = Field(default=0, description="Execution order if applicable")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "template_version_id": "ver-123",
                "file_name": "heat.yaml",
                "file_type": "heat_template",
                "file_path": "heat/heat.yaml",
                "content": "heat_template_version: 2021-04-16\n...",
                "file_size": 2048,
                "description": "Main Heat template for VM deployment",
                "is_primary": True,
                "order": 1
            }
        }
    )


class TemplateVersionFileUpdate(BaseModel):
    """Schema for updating a template version file."""
    file_name: Optional[str] = Field(None, description="Name of the file", max_length=255)
    file_type: Optional[str] = Field(None, description="Type of file")
    file_path: Optional[str] = Field(None, description="Relative path in the git repository", max_length=500)
    content: Optional[str] = Field(None, description="File content (cached)")
    file_size: Optional[int] = Field(None, description="File size in bytes")
    description: Optional[str] = Field(None, description="File description")
    is_primary: Optional[bool] = Field(None, description="Whether this is the primary deployment file")
    order: Optional[int] = Field(None, description="Execution order if applicable")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "file_name": "heat_updated.yaml",
                "description": "Updated Heat template"
            }
        }
    )


class TemplateVersionFileResponse(BaseModel):
    """Schema for template version file response."""
    id: str = Field(..., description="File ID")
    template_version_id: str = Field(..., description="Template version ID")
    file_name: str = Field(..., description="File name")
    file_type: str = Field(..., description="File type")
    file_path: str = Field(..., description="Relative path in repository")
    content: Optional[str] = Field(None, description="File content")
    file_size: Optional[int] = Field(None, description="File size in bytes")
    description: Optional[str] = Field(None, description="File description")
    is_primary: bool = Field(..., description="Is primary deployment file")
    order: int = Field(..., description="Execution order")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "file-123",
                "template_version_id": "ver-123",
                "file_name": "heat.yaml",
                "file_type": "heat_template",
                "file_path": "heat/heat.yaml",
                "content": "heat_template_version: 2021-04-16\n...",
                "file_size": 2048,
                "description": "Main Heat template",
                "is_primary": True,
                "order": 1,
                "created_at": "2024-11-27T10:00:00Z",
                "updated_at": "2024-11-27T10:00:00Z"
            }
        }
    )


class TemplateVersionFileListResponse(BaseModel):
    """Schema for listing template version files (without content)."""
    id: str = Field(..., description="File ID")
    template_version_id: str = Field(..., description="Template version ID")
    file_name: str = Field(..., description="File name")
    file_type: str = Field(..., description="File type")
    file_path: str = Field(..., description="Relative path in repository")
    file_size: Optional[int] = Field(None, description="File size in bytes")
    description: Optional[str] = Field(None, description="File description")
    is_primary: bool = Field(..., description="Is primary deployment file")
    order: int = Field(..., description="Execution order")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "file-123",
                "template_version_id": "ver-123",
                "file_name": "heat.yaml",
                "file_type": "heat_template",
                "file_path": "heat/heat.yaml",
                "file_size": 2048,
                "description": "Main Heat template",
                "is_primary": True,
                "order": 1,
                "created_at": "2024-11-27T10:00:00Z",
                "updated_at": "2024-11-27T10:00:00Z"
            }
        }
    )
