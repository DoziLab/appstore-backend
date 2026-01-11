"""Deployment Instance Access schemas for request/response validation."""
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional


class DeploymentInstanceAccessCreate(BaseModel):
    """Schema for creating an access method."""
    deployment_instance_id: str = Field(..., description="Deployment instance ID")
    access_type: str = Field(..., description="Access type (ssh, web_url, guacamole, rdp, vnc)")
    connection_url: Optional[str] = Field(None, description="Connection URL", max_length=500)
    username: Optional[str] = Field(None, description="Username", max_length=255)
    password: Optional[str] = Field(None, description="Password (will be encrypted)")
    ssh_private_key: Optional[str] = Field(None, description="SSH private key (will be encrypted)")
    port: Optional[int] = Field(None, description="Port number")
    expires_at: Optional[datetime] = Field(None, description="Expiration timestamp")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "deployment_instance_id": "instance-123",
                "access_type": "ssh",
                "username": "ubuntu",
                "ssh_private_key": "-----BEGIN RSA PRIVATE KEY-----...",
                "port": 22
            }
        }
    )


class DeploymentInstanceAccessResponse(BaseModel):
    """Schema for access method response."""
    id: str = Field(..., description="Access method ID")
    deployment_instance_id: str = Field(..., description="Deployment instance ID")
    access_type: str = Field(..., description="Access type")
    connection_url: Optional[str] = Field(None, description="Connection URL")
    username: Optional[str] = Field(None, description="Username")
    port: Optional[int] = Field(None, description="Port number")
    is_active: bool = Field(..., description="Is access active")
    expires_at: Optional[datetime] = Field(None, description="Expiration timestamp")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    
    # Note: password and ssh_private_key are intentionally excluded for security
    
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "access-123",
                "deployment_instance_id": "instance-456",
                "access_type": "ssh",
                "connection_url": None,
                "username": "ubuntu",
                "port": 22,
                "is_active": True,
                "expires_at": None,
                "created_at": "2024-11-27T10:00:00Z",
                "updated_at": "2024-11-27T10:00:00Z"
            }
        }
    )


class DeploymentInstanceAccessWithCredentials(DeploymentInstanceAccessResponse):
    """Schema for access method response with credentials (admin only).
    
    WARNING: Only use this for authenticated admin endpoints.
    Never expose credentials in public APIs.
    """
    password: Optional[str] = Field(None, description="Password (decrypted)")
    ssh_private_key: Optional[str] = Field(None, description="SSH private key (decrypted)")
    
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "access-123",
                "deployment_instance_id": "instance-456",
                "access_type": "ssh",
                "username": "ubuntu",
                "password": None,
                "ssh_private_key": "-----BEGIN RSA PRIVATE KEY-----...",
                "port": 22,
                "is_active": True,
                "expires_at": None,
                "created_at": "2024-11-27T10:00:00Z",
                "updated_at": "2024-11-27T10:00:00Z"
            }
        }
    )
