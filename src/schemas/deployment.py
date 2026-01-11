"""Deployment schemas for request/response validation."""
from pydantic import BaseModel, Field, ConfigDict, field_validator
from datetime import datetime
from typing import Optional

from sqlalchemy import values


class DeploymentCreate(BaseModel):
    """Schema for creating a deployment."""
    template_version_id: str = Field(..., description="Template version ID to deploy")
    course_id: str = Field(..., description="Course ID")
    deployment_mode: str = Field(..., description="Deployment mode (per_course, per_group, per_student)")
    config_json: Optional[str] = Field(None, description="Deployment configuration as JSON string")
    
    # Target groups/students (required depending on mode)
    group_ids: Optional[list[str]] = Field(None, description="Group IDs (required for per_group mode)")
    course_member_ids: Optional[list[str]] = Field(None, description="Course member IDs (required for per_student mode)")
    
    # Desired access methods for instances
    access_types: Optional[list[str]] = Field(
        default=["ssh"],
        description="Desired access types for instances (ssh, web_url, guacamole, rdp, vnc)"
    )
    
    @field_validator("group_ids")
    @classmethod
    def validate_group_ids(cls, v, info):
        """Validate group_ids is provided for per_group mode."""
        deployment_mode = values.get("deployment_mode")
        if deployment_mode == "per_group" and not v:
            raise ValueError("group_ids is required when deployment_mode is 'per_group'")
        return v
    
    @field_validator("course_member_ids")
    @classmethod
    def validate_course_member_ids(cls, v, info):
        """Validate course_member_ids for per_student mode.
        
        - Required when deployment_mode is 'per_student'
        - Optional otherwise (None means "all course members")
        """
        deployment_mode = values.get("deployment_mode")
        if deployment_mode == "per_student" and not v:
            raise ValueError("course_member_ids is required when deployment_mode is 'per_student'")
        return v
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "template_version_id": "version-123",
                "course_id": "course-456",
                "deployment_mode": "per_group",
                "group_ids": ["group-789", "group-abc"],
                "course_member_ids": None,
                "access_types": ["ssh", "web_url"],
                "config_json": '{"cpu": 2, "ram": 4096}'
            }
        }
    )


class DeploymentResponse(BaseModel):
    """Schema for deployment response."""
    id: str = Field(..., description="Deployment ID")
    template_version_id: str = Field(..., description="Template version ID")
    course_id: str = Field(..., description="Course ID")
    deployment_mode: str = Field(..., description="Deployment mode")
    status: str = Field(..., description="Current status")
    openstack_stack_id: Optional[str] = Field(None, description="OpenStack Heat stack ID")
    config_json: Optional[str] = Field(None, description="Deployment configuration")
    access_types_json: str = Field(..., description="Requested access types as JSON array")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "deploy-123",
                "template_version_id": "version-123",
                "course_id": "course-456",
                "deployment_mode": "per_group",
                "status": "queued",
                "openstack_stack_id": None,
                "config_json": '{"cpu": 2, "ram": 4096}',
                "access_types_json": '["ssh", "web_url"]',
                "created_at": "2024-11-27T10:00:00Z",
                "updated_at": "2024-11-27T10:00:00Z"
            }
        }
    )
