"""OpenStack cache service for Redis-based resource usage caching."""
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import redis

from src.core.config import get_settings

logger = logging.getLogger(__name__)


class OpenstackCacheService:
    """Service for caching OpenStack resource usage in Redis.
    
    This service provides fast, in-memory caching for OpenStack resource
    usage data with automatic expiration (TTL). Cache entries expire after
    5 minutes to ensure data freshness while reducing OpenStack API calls.
    """
    
    def __init__(self):
        """Initialize Redis connection and cache TTL."""
        settings = get_settings()
        self.redis = redis.from_url(settings.redis_url, decode_responses=True)
        self.ttl = timedelta(minutes=5)  # Cache for 5 minutes
    
    def get_usage(self, project_id: str) -> Optional[dict]:
        """Get cached resource usage for an OpenStack project.
        
        Args:
            project_id: OpenStack project ID
            
        Returns:
            Dictionary with usage data or None if not cached:
            {
                "used_vms": int,
                "used_vcpus": int,
                "used_ram_mb": int,
                "fetched_at": str (ISO timestamp)
            }
        """
        key = f"openstack:usage:{project_id}"
        try:
            data = self.redis.get(key)
            if data:
                logger.debug(f"Cache hit for OpenStack project {project_id}")
                return json.loads(data)
            logger.debug(f"Cache miss for OpenStack project {project_id}")
            return None
        except redis.RedisError as e:
            logger.error(f"Redis error getting usage for project {project_id}: {e}")
            return None
    
    def set_usage(
        self,
        project_id: str,
        used_vms: int,
        used_vcpus: int,
        used_ram_mb: int
    ) -> bool:
        """Cache resource usage data for an OpenStack project.
        
        Args:
            project_id: OpenStack project ID
            used_vms: Number of VMs in use
            used_vcpus: Number of vCPUs in use
            used_ram_mb: Amount of RAM in use (MB)
            
        Returns:
            True if cached successfully, False otherwise
        """
        key = f"openstack:usage:{project_id}"
        data = {
            "used_vms": used_vms,
            "used_vcpus": used_vcpus,
            "used_ram_mb": used_ram_mb,
            "fetched_at": datetime.now(timezone.utc).isoformat()
        }
        try:
            self.redis.setex(
                key,
                self.ttl,
                json.dumps(data)
            )
            logger.info(
                f"Cached usage for project {project_id}: "
                f"{used_vms} VMs, {used_vcpus} vCPUs, {used_ram_mb} MB RAM"
            )
            return True
        except redis.RedisError as e:
            logger.error(f"Redis error setting usage for project {project_id}: {e}")
            return False
    
    def delete_usage(self, project_id: str) -> bool:
        """Delete cached usage data for a project.
        
        Args:
            project_id: OpenStack project ID
            
        Returns:
            True if deleted successfully, False otherwise
        """
        key = f"openstack:usage:{project_id}"
        try:
            result = self.redis.delete(key)
            if result:
                logger.info(f"Deleted cache for OpenStack project {project_id}")
            return bool(result)
        except redis.RedisError as e:
            logger.error(f"Redis error deleting usage for project {project_id}: {e}")
            return False
    
    def get_all_cached_projects(self) -> list[str]:
        """Get list of all project IDs with cached usage data.
        
        Returns:
            List of OpenStack project IDs
        """
        try:
            keys = self.redis.keys("openstack:usage:*")
            # Extract project IDs from keys
            return [key.split(":")[-1] for key in keys]
        except redis.RedisError as e:
            logger.error(f"Redis error getting cached projects: {e}")
            return []
