"""Deployment schemas for request/response validation."""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class DeploymentCreate(BaseModel):
    """Schema for creating a deployment."""
    name: str = Field(..., description="Name of the deployment")
    template_id: Optional[str] = Field(None, description="Template ID to deploy")
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "my-deployment",
                "template_id": "template-123"
            }
        }


class DeploymentResponse(BaseModel):
    """Schema for deployment response."""
    id: str = Field(..., description="Deployment ID")
    name: str = Field(..., description="Deployment name")
    status: str = Field(..., description="Current status")
    created_at: datetime = Field(..., description="Creation timestamp")
    
    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "example": {
                "id": "deploy-123",
                "name": "my-deployment",
                "status": "pending",
                "created_at": "2024-11-27T10:00:00Z"
            }
        }
    }
