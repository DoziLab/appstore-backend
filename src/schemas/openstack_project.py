"""OpenStack Project schemas."""
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


class OpenstackCredentialsCreate(BaseModel):
    """Schema for creating/updating OpenStack credentials."""
    
    auth_url: str = Field(..., description="OpenStack authentication URL")
    username: str = Field(..., min_length=1, description="OpenStack username")
    password: str = Field(..., min_length=1, description="OpenStack password")
    user_domain_name: str = Field(default="Default", description="User domain name")
    region_name: str = Field(..., description="OpenStack region")
    openstack_project_id: str = Field(..., description="OpenStack project ID")
    openstack_project_name: str = Field(..., description="OpenStack project name")
    
    @field_validator("auth_url")
    @classmethod
    def validate_auth_url(cls, v: str) -> str:
        """Validate auth URL format."""
        if not v.startswith(("http://", "https://")):
            raise ValueError("auth_url must start with http:// or https://")
        return v


class OpenstackCredentialsResponse(BaseModel):
    """Schema for OpenStack credentials response (masked password)."""
    
    model_config = {"from_attributes": True}
    
    id: str
    owner_user_id: str
    openstack_project_id: str
    openstack_project_name: str
    auth_url: str
    username: str  # Returns masked value like "ad***@example.com"
    password: str = Field(default="********", description="Always masked")
    user_domain_name: str
    region_name: str
    created_at: datetime
    updated_at: datetime
    
    @classmethod
    def from_orm_masked(cls, obj):
        """Create response with masked credentials."""
        # Mask username (show first 2 and last chars)
        username = obj.username
        if len(username) > 4:
            masked_username = f"{username[:2]}***{username[-2:]}"
        else:
            masked_username = "***"
        
        return cls(
            id=obj.id,
            owner_user_id=obj.owner_user_id,
            openstack_project_id=obj.openstack_project_id,
            openstack_project_name=obj.openstack_project_name,
            auth_url=obj.auth_url,
            username=masked_username,
            password="********",  # Never expose password
            user_domain_name=obj.user_domain_name,
            region_name=obj.region_name,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
        )


class OpenstackProjectResponse(BaseModel):
    """Schema for OpenStack project response without credentials."""
    
    model_config = {"from_attributes": True}
    
    id: str
    owner_user_id: str
    openstack_project_id: str
    openstack_project_name: str
    region_name: str
    created_at: datetime
    updated_at: datetime
