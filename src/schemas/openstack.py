"""OpenStack Project schemas for request/response validation."""
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional


class OpenstackProjectCreate(BaseModel):
    """Schema for creating an OpenStack project."""
    owner_user_id: str = Field(..., description="Owner user ID")
    openstack_project_id: str = Field(..., description="OpenStack project ID", max_length=255)
    openstack_project_name: str = Field(..., description="OpenStack project name", max_length=255)
    
    # Authentication details
    auth_url: str = Field(..., description="OpenStack auth URL", max_length=500)
    username: str = Field(..., description="OpenStack username", max_length=255)
    password: str = Field(..., description="OpenStack password")
    user_domain_name: str = Field(default="Default", description="User domain name", max_length=255)
    region_name: str = Field(..., description="Region name", max_length=100)
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "owner_user_id": "user-123",
                "openstack_project_id": "abc123def456ghi789jkl012mno345pq",
                "openstack_project_name": "my_project_ws2024",
                "auth_url": "https://openstack.example.com:5000",
                "username": "john.doe@example.com",
                "password": "your-secure-password",
                "user_domain_name": "Default",
                "region_name": "RegionOne"
            }
        }
    )


class OpenstackProjectUpdate(BaseModel):
    """Schema for updating an OpenStack project."""
    openstack_project_name: Optional[str] = Field(None, description="OpenStack project name", max_length=255)
    password: Optional[str] = Field(None, description="OpenStack password")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "vm_quota": 15,
                "vcpu_quota": 30
            }
        }
    )


class OpenstackProjectResponse(BaseModel):
    """Schema for OpenStack project response."""
    id: str = Field(..., description="Project ID")
    owner_user_id: str = Field(..., description="Owner user ID")
    openstack_project_id: str = Field(..., description="OpenStack project ID")
    openstack_project_name: str = Field(..., description="OpenStack project name")
    
    # Connection details (password excluded for security)
    auth_url: str = Field(..., description="OpenStack auth URL")
    username: str = Field(..., description="OpenStack username")
    user_domain_name: str = Field(..., description="User domain name")
    region_name: str = Field(..., description="Region name")
    
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "proj-123",
                "owner_user_id": "user-123",
                "openstack_project_id": "abc123def456ghi789jkl012mno345pq",
                "openstack_project_name": "my_project_ws2024",
                "auth_url": "https://openstack.example.com:5000",
                "username": "john.doe@example.com",
                "user_domain_name": "Default",
                "region_name": "RegionOne",
                "created_at": "2024-11-27T10:00:00Z",
                "updated_at": "2024-11-27T10:00:00Z"
            }
        }
    )


class ResourceUsageResponse(BaseModel):
    """Schema for resource usage response (from Redis cache)."""
    used_vms: int = Field(..., description="Used VMs")
    used_vcpus: int = Field(..., description="Used vCPUs")
    used_ram_mb: int = Field(..., description="Used RAM in MB")
    fetched_at: str = Field(..., description="Fetch timestamp (ISO format)")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "used_vms": 5,
                "used_vcpus": 10,
                "used_ram_mb": 20480,
                "fetched_at": "2024-11-27T10:00:00Z"
            }
        }
    )
