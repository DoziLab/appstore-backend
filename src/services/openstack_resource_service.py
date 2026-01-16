"""Service for retrieving OpenStack resources."""
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from sqlalchemy.orm import Session
import openstack
from openstack.exceptions import HttpException, SDKException

from src.models.openstack_project import OpenstackProject
from src.repositories.openstack_project_repository import OpenstackProjectRepository
from src.services.openstack_cache_service import OpenstackCacheService
from src.core.exceptions import NotFoundException, BadRequestException, ForbiddenException


logger = logging.getLogger(__name__)


class OpenstackResourceService:
    """Service for retrieving OpenStack resources for a user."""
    
    def __init__(self, db: Session):
        """Initialize OpenstackResourceService with database session.
        
        Args:
            db: SQLAlchemy database session
        """
        self.db = db
        self.repository = OpenstackProjectRepository(db)
        self.cache_service = OpenstackCacheService()
    
    def _get_connection(self, openstack_project: OpenstackProject) -> openstack.connection.Connection:
        """Get or create OpenStack connection using project credentials.
        
        Args:
            openstack_project: OpenstackProject with decrypted credentials
            
        Returns:
            OpenStack connection instance
            
        Raises:
            BadRequestException: If connection fails
        """
        try:
            # Use credentials from database (automatically decrypted)
            conn = openstack.connect(
                auth_url=openstack_project.auth_url,
                project_name=openstack_project.openstack_project_name,
                project_id=openstack_project.openstack_project_id,
                username=openstack_project.username,
                password=openstack_project.password,
                user_domain_name=openstack_project.user_domain_name,
                project_domain_name=openstack_project.user_domain_name,
                region_name=openstack_project.region_name,
            )
            logger.info(
                "OpenStack connection established successfully",
                extra={
                    "project_id": openstack_project.openstack_project_id,
                    "region": openstack_project.region_name,
                }
            )
            return conn
        except Exception as e:
            logger.error(
                f"Failed to establish OpenStack connection: {e}",
                extra={"project_id": openstack_project.openstack_project_id}
            )
            raise BadRequestException(f"Failed to connect to OpenStack: {str(e)}")
    
    def _get_project_for_user(
        self, 
        user_id: str, 
        project_id: Optional[str] = None,
        allow_admin_access: bool = False
    ) -> OpenstackProject:
        """Get OpenStack project for user.
        
        Args:
            user_id: User ID
            project_id: Optional specific project ID
            allow_admin_access: If True, allows access to projects owned by other users
            
        Returns:
            OpenstackProject instance
            
        Raises:
            NotFoundException: If no project found
            ForbiddenException: If access is denied (project exists but user doesn't own it)
        """
        if project_id:
            # Get specific project
            project = self.repository.get_by_id(project_id)
            if not project:
                raise NotFoundException(f"OpenStack project {project_id} not found")
            
            # Check ownership unless admin access is allowed
            # Use ForbiddenException (403) for access control errors, not BadRequestException (400)
            # This properly distinguishes permission errors from resource-not-found errors
            if not allow_admin_access and project.owner_user_id != user_id:
                raise ForbiddenException(
                    f"You do not have permission to access project {project_id}"
                )
            
            return project
        else:
            # Get user's first project
            projects = self.repository.get_by_owner(user_id)
            if not projects:
                raise NotFoundException(f"No OpenStack projects found for user {user_id}")
            
            return projects[0]
    
    def _get_compute_quotas(self, conn, project_id: str) -> Optional[dict]:
        """Get compute quotas from OpenStack.
        
        Args:
            conn: OpenStack connection
            project_id: OpenStack project ID
        
        Returns:
            Dictionary with compute quota information, or None if retrieval failed
        """
        quotas = {}
        
        try:
            # Get quota set with usage=True to get used values
            quota_set = conn.compute.get_quota_set(project_id, usage=True)
            quota_dict = quota_set.to_dict() if hasattr(quota_set, 'to_dict') else {}
            
            # Extract usage dict
            usage = quota_dict.get('usage', {})
            
            # Fields to extract
            compute_fields = [
                'instances', 'cores', 'ram', 'key_pairs', 'metadata_items',
                'server_groups', 'server_group_members', 'injected_files',
                'injected_file_content_bytes', 'injected_file_path_bytes'
            ]
            
            for field in compute_fields:
                # Get limit (direct attribute in quota_dict)
                limit = quota_dict.get(field)
                if limit is not None:
                    # Get used value from usage dict
                    used = usage.get(field, 0)
                    available = limit - used if limit >= 0 else -1
                    
                    quotas[field] = {
                        'limit': limit,
                        'used': used,
                        'available': available
                    }
        except Exception as e:
            logger.warning(f"Could not retrieve compute quotas: {e}", exc_info=True)
        
        return quotas if quotas else None
    
    def _get_network_quotas(self, conn, project_id: str) -> Optional[dict]:
        """Get network quotas from OpenStack.
        
        Args:
            conn: OpenStack connection
            project_id: OpenStack project ID
        
        Returns:
            Dictionary with network quota information, or None if retrieval failed
        """
        quotas = {}
        
        try:
            # Get network quota with details=True to get used values
            quota_set = conn.network.get_quota(project_id, details=True)
            quota_dict = quota_set.to_dict() if hasattr(quota_set, 'to_dict') else {}
            
            # Fields to extract - each is a dict with 'limit', 'used', 'reserved'
            network_fields = [
                'floating_ips', 'networks', 'ports', 'rbac_policies', 'routers',
                'security_groups', 'security_group_rules', 'subnets', 'subnet_pools'
            ]
            
            for field in network_fields:
                quota_data = quota_dict.get(field)
                if quota_data and isinstance(quota_data, dict):
                    limit = quota_data.get('limit', -1)
                    used = quota_data.get('used', 0)
                    available = limit - used if limit >= 0 else -1
                    
                    # Map to our field names (remove underscores for some fields)
                    our_field = field
                    if field == 'floating_ips':
                        our_field = 'floatingip'
                    elif field == 'rbac_policies':
                        our_field = 'rbac_policy'
                    elif field == 'subnet_pools':
                        our_field = 'subnetpool'
                    
                    quotas[our_field] = {
                        'limit': limit,
                        'used': used,
                        'available': available
                    }
        except Exception as e:
            logger.warning(f"Could not retrieve network quotas: {e}", exc_info=True)
        
        return quotas if quotas else None
    
    def _get_volume_quotas(self, conn, project_id: str) -> Optional[dict]:
        """Get volume quotas from OpenStack.
        
        Args:
            conn: OpenStack connection
            project_id: OpenStack project ID
        
        Returns:
            Dictionary with volume quota information, or None if retrieval failed
        """
        quotas = {}
        
        try:
            # Get volume quota set with usage=True to get used values
            quota_set = conn.volume.get_quota_set(project_id, usage=True)
            quota_dict = quota_set.to_dict() if hasattr(quota_set, 'to_dict') else {}
            
            # Extract usage dict
            usage = quota_dict.get('usage', {})
            
            # Fields to extract
            volume_fields = [
                'volumes', 'snapshots', 'gigabytes', 'backups', 
                'backup_gigabytes', 'per_volume_gigabytes', 'groups'
            ]
            
            for field in volume_fields:
                # Get limit (direct attribute in quota_dict)
                limit = quota_dict.get(field)
                if limit is not None:
                    # Get used value from usage dict
                    used = usage.get(field, 0)
                    available = limit - used if limit >= 0 else -1
                    
                    quotas[field] = {
                        'limit': limit,
                        'used': used,
                        'available': available
                    }
        except Exception as e:
            logger.warning(f"Could not retrieve volume quotas: {e}", exc_info=True)
        
        return quotas if quotas else None

    def get_quotas(
        self,
        user_id: str,
        project_id: Optional[str] = None,
        use_cache: bool = True,
        force_refresh: bool = False,
        allow_admin_access: bool = False
    ) -> dict:
        """Get quotas and usage for an OpenStack project.
        
        Uses the OpenStack limits API to get accurate quota and usage information.
        
        Args:
            user_id: User ID to get quotas for
            project_id: Optional project ID (defaults to user's first project)
            use_cache: Whether to use cached data
            force_refresh: Force refresh from OpenStack (bypass cache)
            allow_admin_access: Allow admin to access any user's project
        
        Returns:
            Dict containing quotas and usage:
            {
                'compute': {
                    'instances': {'limit': int, 'used': int, 'available': int},
                    'cores': {'limit': int, 'used': int, 'available': int},
                    'ram': {'limit': int, 'used': int, 'available': int},
                    ...
                },
                'volume': {...},
                'network': {...},
                'project_id': str,
                'project_name': str,
                'owner_user_id': str,
                'fetched_at': str
            }
        """
        project = self._get_project_for_user(user_id, project_id, allow_admin_access)
        openstack_project_id = project.openstack_project_id
        
        # Check cache first if enabled
        if use_cache and not force_refresh:
            cached_quotas = self.cache_service.get_quotas(openstack_project_id)
            if cached_quotas:
                logger.info(f"Using cached quotas for user {user_id}")
                cached_quotas['owner_user_id'] = project.owner_user_id
                return cached_quotas
        
        # Get fresh data from OpenStack
        try:
            conn = self._get_connection(project)
            
            quotas: Dict[str, Any] = {
                'project_id': openstack_project_id,
                'project_name': project.openstack_project_name,
                'owner_user_id': project.owner_user_id,
            }
            
            # Get compute quotas
            quotas['compute'] = self._get_compute_quotas(conn, openstack_project_id)
            
            # Get network quotas
            quotas['network'] = self._get_network_quotas(conn, openstack_project_id)
            
            # Get volume quotas
            quotas['volume'] = self._get_volume_quotas(conn, openstack_project_id)
            
            logger.info(f"Successfully retrieved all quotas for project {openstack_project_id}")
            
            # Add timestamp
            quotas['fetched_at'] = datetime.now(timezone.utc).isoformat()
            
            logger.info(
                f"Retrieved quotas for user {user_id}",
                extra={"user_id": user_id, "project_id": project.openstack_project_id}
            )
            
            # Cache the quotas for future use
            if use_cache:
                self.cache_service.set_quotas(openstack_project_id, quotas)
            
            return quotas
            
        except BadRequestException:
            # Re-raise BadRequestException from _get_connection
            raise
        except HttpException as e:
            logger.error(f"OpenStack API error retrieving quotas: {e}")
            raise BadRequestException(f"Failed to retrieve quotas: {str(e)}")
        except SDKException as e:
            logger.error(f"OpenStack SDK error retrieving quotas: {e}")
            raise BadRequestException(f"Failed to retrieve quotas: {str(e)}")
    
    def check_availability(
        self,
        user_id: str,
        required_resources: Dict[str, Any],
        project_id: Optional[str] = None
    ) -> dict:
        """Check if required resources are available within quota limits.
        
        Args:
            user_id: User ID
            required_resources: Dict specifying required resources:
                {
                    'instances': int,
                    'cores': int,
                    'ram': int (MB),
                    'volumes': int,
                    'gigabytes': int (GB)
                }
            project_id: Optional specific project ID
            
        Returns:
            Dict with availability status and reasons:
            {
                'available': bool,
                'reasons': list[str],  # Empty if available
                'quotas': dict  # Current quota info
            }
        """
        quotas = self.get_quotas(user_id, project_id)
        
        available = True
        reasons = []
        
        # Check compute resources
        if 'compute' in quotas and quotas['compute'] is not None:
            compute = quotas['compute']
            
            if 'instances' in required_resources:
                req = required_resources['instances']
                avail = compute.get('instances', {}).get('available', 0)
                if req > avail:
                    available = False
                    reasons.append(f"Insufficient instances quota: need {req}, available {avail}")
            
            if 'cores' in required_resources:
                req = required_resources['cores']
                avail = compute.get('cores', {}).get('available', 0)
                if req > avail:
                    available = False
                    reasons.append(f"Insufficient CPU cores: need {req}, available {avail}")
            
            if 'ram' in required_resources:
                req = required_resources['ram']
                avail = compute.get('ram', {}).get('available', 0)
                if req > avail:
                    available = False
                    reasons.append(f"Insufficient RAM: need {req}MB, available {avail}MB")
        
        # Check volume resources
        if 'volume' in quotas and quotas['volume'] is not None:
            volume = quotas['volume']
            if 'volumes' in required_resources:
                req = required_resources['volumes']
                avail = volume.get('volumes', {}).get('available', 0)
                if req > avail:
                    available = False
                    reasons.append(f"Insufficient volume quota: need {req}, available {avail}")
            if 'gigabytes' in required_resources:
                req = required_resources['gigabytes']
                avail = volume.get('gigabytes', {}).get('available', 0)
                if req > avail:
                    available = False
                    reasons.append(f"Insufficient storage: need {req}GB, available {avail}GB")
        

        return {
            'available': available,
            'reasons': reasons,
            'quotas': quotas
        }
