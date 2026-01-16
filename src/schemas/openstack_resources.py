"""OpenStack Resources schemas for quota and usage responses."""
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any


class QuotaResource(BaseModel):
    """Schema for a single quota resource (limit, used, available)."""
    
    limit: int = Field(..., description="Maximum allowed (or -1 for unlimited)")
    used: int = Field(..., description="Currently used amount")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "limit": 10,
                "used": 3
            }
        }
    }


class ComputeQuotas(BaseModel):
    """Schema for compute quotas."""
    
    instances: Optional[QuotaResource] = Field(None, description="VM instances quota")
    cores: Optional[QuotaResource] = Field(None, description="vCPU cores quota")
    ram: Optional[QuotaResource] = Field(None, description="RAM quota (in MB)")
    key_pairs: Optional[QuotaResource] = Field(None, description="SSH key pairs quota")
    metadata_items: Optional[QuotaResource] = Field(None, description="Metadata items quota")
    server_groups: Optional[QuotaResource] = Field(None, description="Server groups quota")
    server_group_members: Optional[QuotaResource] = Field(None, description="Server group members quota")
    injected_files: Optional[QuotaResource] = Field(None, description="Injected files quota")
    injected_file_content_bytes: Optional[QuotaResource] = Field(None, description="Injected file content bytes quota")
    injected_file_path_bytes: Optional[QuotaResource] = Field(None, description="Injected file path bytes quota")


class NetworkQuotas(BaseModel):
    """Schema for network quotas."""
    
    floatingip: Optional[QuotaResource] = Field(None, description="Floating IPs quota")
    networks: Optional[QuotaResource] = Field(None, description="Networks quota")
    ports: Optional[QuotaResource] = Field(None, description="Ports quota")
    rbac_policy: Optional[QuotaResource] = Field(None, description="RBAC policies quota")
    routers: Optional[QuotaResource] = Field(None, description="Routers quota")
    security_groups: Optional[QuotaResource] = Field(None, description="Security groups quota")
    security_group_rules: Optional[QuotaResource] = Field(None, description="Security group rules quota")
    subnets: Optional[QuotaResource] = Field(None, description="Subnets quota")
    subnetpool: Optional[QuotaResource] = Field(None, description="Subnet pools quota")


class VolumeQuotas(BaseModel):
    """Schema for volume quotas."""
    
    volumes: Optional[QuotaResource] = Field(None, description="Volumes quota")
    snapshots: Optional[QuotaResource] = Field(None, description="Snapshots quota")
    gigabytes: Optional[QuotaResource] = Field(None, description="Storage quota (in GB)")
    backups: Optional[QuotaResource] = Field(None, description="Backups quota")
    backup_gigabytes: Optional[QuotaResource] = Field(None, description="Backup storage quota (in GB)")
    per_volume_gigabytes: Optional[QuotaResource] = Field(None, description="Per-volume size limit (in GB)")
    groups: Optional[QuotaResource] = Field(None, description="Volume groups quota")
    group_snapshots: Optional[QuotaResource] = Field(None, description="Volume group snapshots quota")


class QuotaResponse(BaseModel):
    """Schema for quota and usage response."""
    
    project_id: str = Field(..., description="OpenStack project ID")
    project_name: str = Field(..., description="OpenStack project name")
    owner_user_id: Optional[str] = Field(None, description="Owner user ID (only for admins)")
    compute: Optional[ComputeQuotas] = Field(None, description="Compute quotas")
    volume: Optional[VolumeQuotas] = Field(None, description="Volume quotas")
    network: Optional[NetworkQuotas] = Field(None, description="Network quotas")
    fetched_at: Optional[str] = Field(None, description="Timestamp when data was fetched (ISO format)")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "project_id": "abc123def456",
                "project_name": "my_project_ws2024",
                "owner_user_id": "user-123",
                "compute": {
                    "instances": {"limit": 10, "used": 3, "available": 7},
                    "cores": {"limit": 20, "used": 6, "available": 14},
                    "ram": {"limit": 40960, "used": 12288, "available": 28672}
                },
                "volume": {
                    "volumes": {"limit": 10, "used": 2, "available": 8},
                    "gigabytes": {"limit": 1000, "used": 200, "available": 800}
                },
                "network": {
                    "floatingip": {"limit": 5, "used": 2, "available": 3},
                    "network": {"limit": 10, "used": 1, "available": 9}
                },
                "fetched_at": "2024-11-27T10:00:00Z"
            }
        }
    }
    
    @classmethod
    def from_service_dict(cls, data: Dict[str, Any], owner_user_id: Optional[str] = None) -> "QuotaResponse":
        """Create QuotaResponse from service dictionary.
        
        Args:
            data: Dictionary from OpenstackResourceService.get_quotas()
            owner_user_id: Optional owner user ID to include (for admin access)
            
        Returns:
            QuotaResponse instance
        """
        # Convert compute quotas
        compute_data = data.get("compute", {})
        compute = None
        if compute_data:
            compute = ComputeQuotas(**{
                key: QuotaResource(**value) if isinstance(value, dict) else None
                for key, value in compute_data.items()
            })
        
        # Convert volume quotas
        volume_data = data.get("volume", {})
        volume = None
        if volume_data:
            volume = VolumeQuotas(**{
                key: QuotaResource(**value) if isinstance(value, dict) else None
                for key, value in volume_data.items()
            })
        
        
        # Convert network quotas
        network_data = data.get("network", {})
        network = None
        if network_data:
            network = NetworkQuotas(**{
                key: QuotaResource(**value) if isinstance(value, dict) else None
                for key, value in network_data.items()
            })
        
        return cls(
            project_id=data.get("project_id", ""),
            project_name=data.get("project_name", ""),
            owner_user_id=owner_user_id,
            compute=compute,
            volume=volume,
            network=network,
            fetched_at=data.get("fetched_at")
        )
