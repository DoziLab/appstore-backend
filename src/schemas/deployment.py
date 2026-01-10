"""Deployment schemas for request/response validation."""
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional
from uuid import UUID


class DeploymentCreate(BaseModel):
    """Schema for creating a deployment."""
    template_ref: str = Field(..., description="Git template reference (URL or repo identifier)")
    name: Optional[str] = Field(None, description="Optional deployment name (auto-generated if not provided)")
    course_id: UUID = Field(..., description="Course ID this deployment belongs to")
    openstack_project_id: Optional[str] = Field(None, description="OpenStack project ID (optional, uses default if not provided)")
    openstack_credentials: Optional[dict] = Field(None, description="OpenStack credentials (optional)")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "template_ref": "https://github.com/org/template-repo.git",
                "name": "student-lab-environment",
                "course_id": "123e4567-e89b-12d3-a456-426614174000",
                "openstack_project_id": null,
                "openstack_credentials": null
            }
        }
    )


class DeploymentResponse(BaseModel):
    """Schema for deployment response."""
    id: UUID = Field(..., description="Deployment ID")
    name: str = Field(..., description="Deployment name")
    template_ref: str = Field(..., description="Git template reference")
    course_id: UUID = Field(..., description="Course ID")
    status: str = Field(..., description="Current deployment status")
    stack_id: Optional[str] = Field(None, description="OpenStack Heat stack ID")
    error_message: Optional[str] = Field(None, description="Error message if deployment failed")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: Optional[datetime] = Field(None, description="Last update timestamp")
    
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "name": "student-lab-environment",
                "template_ref": "https://github.com/org/template-repo.git",
                "course_id": "123e4567-e89b-12d3-a456-426614174001",
                "status": "pending",
                "stack_id": null,
                "error_message": null,
                "created_at": "2026-01-09T10:00:00Z",
                "updated_at": null
            }
        }
    )
