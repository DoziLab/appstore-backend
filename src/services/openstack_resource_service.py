"""OpenStack Resource service for retrieving available resources."""
import logging
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
import openstack
from openstack.exceptions import HttpException, SDKException

from src.models.openstack_project import OpenstackProject
from src.repositories.openstack_project_repository import OpenstackProjectRepository
from src.services.openstack_cache_service import OpenstackCacheService
from src.core.exceptions import NotFoundException, BadRequestException


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
                extra={
                    "project_id": openstack_project.openstack_project_id,
                    "auth_url": openstack_project.auth_url,
                }
            )
            raise BadRequestException(f"Failed to connect to OpenStack: {str(e)}")
    
    def _get_project_for_user(
        self,
        user_id: str,
        project_id: Optional[str] = None
    ) -> OpenstackProject:
        """Get OpenStack project for user.
        
        Args:
            user_id: User ID
            project_id: Optional specific project ID, otherwise uses first project
            
        Returns:
            OpenstackProject instance
            
        Raises:
            NotFoundException: If no project found for user
        """
        if project_id:
            project = self.repository.get_by_id(project_id)
            if not project:
                raise NotFoundException(f"OpenStack project {project_id} not found")
            if project.owner_user_id != user_id:
                raise NotFoundException("OpenStack project not found for this user")
            return project
        
        # Get first project for user
        projects = self.repository.get_by_owner(user_id)
        if not projects:
            raise NotFoundException("No OpenStack project found for this user")
        return projects[0]
    
    def get_servers(
        self,
        user_id: str,
        project_id: Optional[str] = None,
        all_projects: bool = False
    ) -> list[dict]:
        """Get available compute servers/VMs for a user.
        
        Args:
            user_id: User ID
            project_id: Optional specific project ID
            all_projects: If True, retrieve servers from all user's projects
            
        Returns:
            List of server information dicts
            
        Raises:
            NotFoundException: If no project found
            BadRequestException: If OpenStack API call fails
        """
        try:
            if all_projects:
                projects = self.repository.get_by_owner(user_id)
                if not projects:
                    raise NotFoundException("No OpenStack projects found for this user")
            else:
                projects = [self._get_project_for_user(user_id, project_id)]
            
            all_servers = []
            for project in projects:
                conn = self._get_connection(project)
                servers = conn.compute.servers(details=True)
                
                for server in servers:
                    all_servers.append({
                        'id': server.id,
                        'name': server.name,
                        'status': server.status,
                        'flavor': {
                            'id': server.flavor.get('id') if server.flavor else None,
                            'name': server.flavor.get('name') if server.flavor else None,
                        } if server.flavor else None,
                        'image': {
                            'id': server.image.get('id') if server.image else None,
                            'name': server.image.get('name') if server.image else None,
                        } if server.image else None,
                        'networks': server.addresses if hasattr(server, 'addresses') else {},
                        'created': str(server.created_at) if server.created_at else None,
                        'updated': str(server.updated_at) if server.updated_at else None,
                        'project_id': project.openstack_project_id,
                    })
            
            logger.info(
                f"Retrieved {len(all_servers)} servers for user {user_id}",
                extra={"user_id": user_id, "count": len(all_servers)}
            )
            return all_servers
            
        except HttpException as e:
            logger.error(f"OpenStack API error retrieving servers: {e}")
            raise BadRequestException(f"Failed to retrieve servers: {str(e)}")
        except SDKException as e:
            logger.error(f"OpenStack SDK error retrieving servers: {e}")
            raise BadRequestException(f"Failed to retrieve servers: {str(e)}")
    
    def get_networks(
        self,
        user_id: str,
        project_id: Optional[str] = None
    ) -> list[dict]:
        """Get available networks for a user.
        
        Args:
            user_id: User ID
            project_id: Optional specific project ID
            
        Returns:
            List of network information dicts
            
        Raises:
            NotFoundException: If no project found
            BadRequestException: If OpenStack API call fails
        """
        try:
            project = self._get_project_for_user(user_id, project_id)
            openstack_project_id = project.openstack_project_id
            
            # Try to get from cache first
            if use_cache and not force_refresh:
                cached_quotas = self.cache_service.get_quotas(openstack_project_id)
                if cached_quotas:
                    logger.debug(f"Using cached quotas for project {openstack_project_id}")
                    return cached_quotas
            
            # Fetch fresh data from OpenStack
            conn = self._get_connection(project)
            networks = conn.network.networks()
            
            result = []
            for network in networks:
                result.append({
                    'id': network.id,
                    'name': network.name,
                    'status': network.status,
                    'admin_state_up': network.admin_state_up,
                    'shared': network.shared,
                    'subnets': [subnet.id for subnet in network.subnets] if hasattr(network, 'subnets') else [],
                    'created': str(network.created_at) if network.created_at else None,
                    'updated': str(network.updated_at) if network.updated_at else None,
                })
            
            logger.info(
                f"Retrieved {len(result)} networks for user {user_id}",
                extra={"user_id": user_id, "count": len(result)}
            )
            return result
            
        except HttpException as e:
            logger.error(f"OpenStack API error retrieving networks: {e}")
            raise BadRequestException(f"Failed to retrieve networks: {str(e)}")
        except SDKException as e:
            logger.error(f"OpenStack SDK error retrieving networks: {e}")
            raise BadRequestException(f"Failed to retrieve networks: {str(e)}")
    
    def get_volumes(
        self,
        user_id: str,
        project_id: Optional[str] = None
    ) -> list[dict]:
        """Get available volumes for a user.
        
        Args:
            user_id: User ID
            project_id: Optional specific project ID
            
        Returns:
            List of volume information dicts
            
        Raises:
            NotFoundException: If no project found
            BadRequestException: If OpenStack API call fails
        """
        try:
            project = self._get_project_for_user(user_id, project_id)
            openstack_project_id = project.openstack_project_id
            
            # Try to get from cache first
            if use_cache and not force_refresh:
                cached_quotas = self.cache_service.get_quotas(openstack_project_id)
                if cached_quotas:
                    logger.debug(f"Using cached quotas for project {openstack_project_id}")
                    return cached_quotas
            
            # Fetch fresh data from OpenStack
            conn = self._get_connection(project)
            volumes = conn.block_storage.volumes()
            
            result = []
            for volume in volumes:
                result.append({
                    'id': volume.id,
                    'name': volume.name,
                    'status': volume.status,
                    'size': volume.size,
                    'volume_type': volume.volume_type,
                    'attachments': volume.attachments if hasattr(volume, 'attachments') else [],
                    'created': str(volume.created_at) if volume.created_at else None,
                    'updated': str(volume.updated_at) if volume.updated_at else None,
                })
            
            logger.info(
                f"Retrieved {len(result)} volumes for user {user_id}",
                extra={"user_id": user_id, "count": len(result)}
            )
            return result
            
        except HttpException as e:
            logger.error(f"OpenStack API error retrieving volumes: {e}")
            raise BadRequestException(f"Failed to retrieve volumes: {str(e)}")
        except SDKException as e:
            logger.error(f"OpenStack SDK error retrieving volumes: {e}")
            raise BadRequestException(f"Failed to retrieve volumes: {str(e)}")
    
    def get_images(
        self,
        user_id: str,
        project_id: Optional[str] = None,
        include_public: bool = True
    ) -> list[dict]:
        """Get available images for a user.
        
        Args:
            user_id: User ID
            project_id: Optional specific project ID
            include_public: If True, include public images
            
        Returns:
            List of image information dicts
            
        Raises:
            NotFoundException: If no project found
            BadRequestException: If OpenStack API call fails
        """
        try:
            project = self._get_project_for_user(user_id, project_id)
            openstack_project_id = project.openstack_project_id
            
            # Try to get from cache first
            if use_cache and not force_refresh:
                cached_quotas = self.cache_service.get_quotas(openstack_project_id)
                if cached_quotas:
                    logger.debug(f"Using cached quotas for project {openstack_project_id}")
                    return cached_quotas
            
            # Fetch fresh data from OpenStack
            conn = self._get_connection(project)
            
            if include_public:
                images = conn.image.images()
            else:
                images = conn.image.images(owner=project.openstack_project_id)
            
            result = []
            for image in images:
                result.append({
                    'id': image.id,
                    'name': image.name,
                    'status': image.status,
                    'visibility': image.visibility if hasattr(image, 'visibility') else None,
                    'size': image.size if hasattr(image, 'size') else None,
                    'min_disk': image.min_disk if hasattr(image, 'min_disk') else None,
                    'min_ram': image.min_ram if hasattr(image, 'min_ram') else None,
                    'created': str(image.created_at) if image.created_at else None,
                    'updated': str(image.updated_at) if image.updated_at else None,
                })
            
            logger.info(
                f"Retrieved {len(result)} images for user {user_id}",
                extra={"user_id": user_id, "count": len(result)}
            )
            return result
            
        except HttpException as e:
            logger.error(f"OpenStack API error retrieving images: {e}")
            raise BadRequestException(f"Failed to retrieve images: {str(e)}")
        except SDKException as e:
            logger.error(f"OpenStack SDK error retrieving images: {e}")
            raise BadRequestException(f"Failed to retrieve images: {str(e)}")
    
    def get_flavors(
        self,
        user_id: str,
        project_id: Optional[str] = None
    ) -> list[dict]:
        """Get available flavors (VM sizes) for a user.
        
        Args:
            user_id: User ID
            project_id: Optional specific project ID
            
        Returns:
            List of flavor information dicts
            
        Raises:
            NotFoundException: If no project found
            BadRequestException: If OpenStack API call fails
        """
        try:
            project = self._get_project_for_user(user_id, project_id)
            openstack_project_id = project.openstack_project_id
            
            # Try to get from cache first
            if use_cache and not force_refresh:
                cached_quotas = self.cache_service.get_quotas(openstack_project_id)
                if cached_quotas:
                    logger.debug(f"Using cached quotas for project {openstack_project_id}")
                    return cached_quotas
            
            # Fetch fresh data from OpenStack
            conn = self._get_connection(project)
            flavors = conn.compute.flavors(details=True)
            
            result = []
            for flavor in flavors:
                result.append({
                    'id': flavor.id,
                    'name': flavor.name,
                    'vcpus': flavor.vcpus,
                    'ram': flavor.ram,
                    'disk': flavor.disk,
                    'ephemeral': flavor.ephemeral if hasattr(flavor, 'ephemeral') else 0,
                    'swap': flavor.swap if hasattr(flavor, 'swap') else 0,
                    'is_public': flavor.is_public if hasattr(flavor, 'is_public') else True,
                })
            
            logger.info(
                f"Retrieved {len(result)} flavors for user {user_id}",
                extra={"user_id": user_id, "count": len(result)}
            )
            return result
            
        except HttpException as e:
            logger.error(f"OpenStack API error retrieving flavors: {e}")
            raise BadRequestException(f"Failed to retrieve flavors: {str(e)}")
        except SDKException as e:
            logger.error(f"OpenStack SDK error retrieving flavors: {e}")
            raise BadRequestException(f"Failed to retrieve flavors: {str(e)}")
    
    def get_security_groups(
        self,
        user_id: str,
        project_id: Optional[str] = None
    ) -> list[dict]:
        """Get available security groups for a user.
        
        Args:
            user_id: User ID
            project_id: Optional specific project ID
            
        Returns:
            List of security group information dicts
            
        Raises:
            NotFoundException: If no project found
            BadRequestException: If OpenStack API call fails
        """
        try:
            project = self._get_project_for_user(user_id, project_id)
            openstack_project_id = project.openstack_project_id
            
            # Try to get from cache first
            if use_cache and not force_refresh:
                cached_quotas = self.cache_service.get_quotas(openstack_project_id)
                if cached_quotas:
                    logger.debug(f"Using cached quotas for project {openstack_project_id}")
                    return cached_quotas
            
            # Fetch fresh data from OpenStack
            conn = self._get_connection(project)
            security_groups = conn.network.security_groups()
            
            result = []
            for sg in security_groups:
                result.append({
                    'id': sg.id,
                    'name': sg.name,
                    'description': sg.description if hasattr(sg, 'description') else None,
                    'rules': [
                        {
                            'id': rule.id,
                            'direction': rule.direction,
                            'protocol': rule.protocol,
                            'port_range_min': rule.port_range_min,
                            'port_range_max': rule.port_range_max,
                            'remote_ip_prefix': rule.remote_ip_prefix,
                        }
                        for rule in sg.security_group_rules
                    ] if hasattr(sg, 'security_group_rules') else [],
                    'created': str(sg.created_at) if sg.created_at else None,
                    'updated': str(sg.updated_at) if sg.updated_at else None,
                })
            
            logger.info(
                f"Retrieved {len(result)} security groups for user {user_id}",
                extra={"user_id": user_id, "count": len(result)}
            )
            return result
            
        except HttpException as e:
            logger.error(f"OpenStack API error retrieving security groups: {e}")
            raise BadRequestException(f"Failed to retrieve security groups: {str(e)}")
        except SDKException as e:
            logger.error(f"OpenStack SDK error retrieving security groups: {e}")
            raise BadRequestException(f"Failed to retrieve security groups: {str(e)}")
    
    def get_keypairs(
        self,
        user_id: str,
        project_id: Optional[str] = None
    ) -> list[dict]:
        """Get available key pairs for a user.
        
        Args:
            user_id: User ID
            project_id: Optional specific project ID
            
        Returns:
            List of key pair information dicts (without private keys)
            
        Raises:
            NotFoundException: If no project found
            BadRequestException: If OpenStack API call fails
        """
        try:
            project = self._get_project_for_user(user_id, project_id)
            openstack_project_id = project.openstack_project_id
            
            # Try to get from cache first
            if use_cache and not force_refresh:
                cached_quotas = self.cache_service.get_quotas(openstack_project_id)
                if cached_quotas:
                    logger.debug(f"Using cached quotas for project {openstack_project_id}")
                    return cached_quotas
            
            # Fetch fresh data from OpenStack
            conn = self._get_connection(project)
            keypairs = conn.compute.keypairs()
            
            result = []
            for kp in keypairs:
                result.append({
                    'id': kp.id if hasattr(kp, 'id') else None,
                    'name': kp.name,
                    'fingerprint': kp.fingerprint if hasattr(kp, 'fingerprint') else None,
                    'public_key': kp.public_key if hasattr(kp, 'public_key') else None,
                    'type': kp.type if hasattr(kp, 'type') else None,
                    'created': str(kp.created_at) if hasattr(kp, 'created_at') and kp.created_at else None,
                })
            
            logger.info(
                f"Retrieved {len(result)} key pairs for user {user_id}",
                extra={"user_id": user_id, "count": len(result)}
            )
            return result
            
        except HttpException as e:
            logger.error(f"OpenStack API error retrieving key pairs: {e}")
            raise BadRequestException(f"Failed to retrieve key pairs: {str(e)}")
        except SDKException as e:
            logger.error(f"OpenStack SDK error retrieving key pairs: {e}")
            raise BadRequestException(f"Failed to retrieve key pairs: {str(e)}")
    
    def get_quotas(
        self,
        user_id: str,
        project_id: Optional[str] = None,
        use_cache: bool = True,
        force_refresh: bool = False
    ) -> dict:
        """Get quotas and usage for an OpenStack project.
        
        Retrieves quotas and current usage for compute, network, and block storage.
        Uses cache by default to reduce OpenStack API calls.
        
        Args:
            user_id: User ID
            project_id: Optional specific project ID
            use_cache: If True, use cached data if available (default: True)
            force_refresh: If True, bypass cache and fetch fresh data (default: False)
            
        Returns:
            Dict containing quotas and usage:
            {
                'compute': {
                    'instances': {'limit': int, 'used': int, 'available': int},
                    'cores': {'limit': int, 'used': int, 'available': int},
                    'ram': {'limit': int, 'used': int, 'available': int},
                    ...
                },
                'network': {...},
                'block_storage': {...}
            }
            
        Raises:
            NotFoundException: If no project found
            BadRequestException: If OpenStack API call fails
        """
        try:
            project = self._get_project_for_user(user_id, project_id)
            openstack_project_id = project.openstack_project_id
            
            # Try to get from cache first
            if use_cache and not force_refresh:
                cached_quotas = self.cache_service.get_quotas(openstack_project_id)
                if cached_quotas:
                    logger.debug(f"Using cached quotas for project {openstack_project_id}")
                    return cached_quotas
            
            # Fetch fresh data from OpenStack
            conn = self._get_connection(project)
            
            quotas = {
                'project_id': project.openstack_project_id,
                'project_name': project.openstack_project_name,
            }
            
            # Get compute quotas
            try:
                compute_quota = conn.compute.get_quota_set(project.openstack_project_id)
                quotas['compute'] = {}
                
                # Common compute quota fields
                compute_fields = [
                    'instances', 'cores', 'ram', 'key_pairs', 'metadata_items',
                    'server_groups', 'server_group_members', 'injected_files',
                    'injected_file_content_bytes', 'injected_file_path_bytes'
                ]
                
                for field in compute_fields:
                    limit = getattr(compute_quota, field, None)
                    if limit is not None:
                        used = getattr(compute_quota, f'{field}_used', 0) if hasattr(compute_quota, f'{field}_used') else 0
                        available = limit - used if limit >= 0 else -1  # -1 means unlimited
                        quotas['compute'][field] = {
                            'limit': limit,
                            'used': used,
                            'available': available
                        }
            except Exception as e:
                logger.warning(f"Could not retrieve compute quotas: {e}")
                quotas['compute'] = {}
            
            # Get network quotas
            try:
                network_quota = conn.network.get_quota(project.openstack_project_id)
                quotas['network'] = {}
                
                network_fields = [
                    'floatingip', 'network', 'port', 'rbac_policy', 'router',
                    'security_group', 'security_group_rule', 'subnet', 'subnetpool'
                ]
                
                for field in network_fields:
                    limit = getattr(network_quota, field, None)
                    if limit is not None:
                        used = getattr(network_quota, f'{field}_used', 0) if hasattr(network_quota, f'{field}_used') else 0
                        available = limit - used if limit >= 0 else -1
                        quotas['network'][field] = {
                            'limit': limit,
                            'used': used,
                            'available': available
                        }
            except Exception as e:
                logger.warning(f"Could not retrieve network quotas: {e}")
                quotas['network'] = {}
            
            # Get block storage quotas
            try:
                volume_quota = conn.block_storage.get_quota_set(project.openstack_project_id)
                quotas['block_storage'] = {}
                
                volume_fields = [
                    'volumes', 'snapshots', 'gigabytes', 'backups', 'backup_gigabytes',
                    'per_volume_gigabytes', 'groups', 'group_snapshots'
                ]
                
                for field in volume_fields:
                    limit = getattr(volume_quota, field, None)
                    if limit is not None:
                        used = getattr(volume_quota, f'{field}_used', 0) if hasattr(volume_quota, f'{field}_used') else 0
                        available = limit - used if limit >= 0 else -1
                        quotas['block_storage'][field] = {
                            'limit': limit,
                            'used': used,
                            'available': available
                        }
            except Exception as e:
                logger.warning(f"Could not retrieve block storage quotas: {e}")
                quotas['block_storage'] = {}
            
            logger.info(
                f"Retrieved quotas for user {user_id}",
                extra={"user_id": user_id, "project_id": project.openstack_project_id}
            )
            
            # Cache the quotas for future use
            if use_cache:
                self.cache_service.set_quotas(openstack_project_id, quotas)
            
            return quotas
            
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
        """Check if required resources are available in the project.
        
        Args:
            user_id: User ID
            required_resources: Dict specifying required resources, e.g.:
                {
                    'instances': int,  # Number of VMs
                    'cores': int,      # Number of vCPUs
                    'ram': int,        # RAM in MB
                    'volumes': int,    # Number of volumes
                    'gigabytes': int,  # Storage in GB
                    'networks': int,   # Number of networks
                    'ports': int,      # Number of ports
                    'floatingips': int, # Number of floating IPs
                    'security_groups': int, # Number of security groups
                }
            project_id: Optional specific project ID
            
        Returns:
            Dict with availability check results:
            {
                'available': bool,
                'checks': {
                    'instances': {'required': int, 'available': int, 'sufficient': bool},
                    ...
                },
                'insufficient_resources': [str],  # List of resource types that are insufficient
            }
            
        Raises:
            NotFoundException: If no project found
            BadRequestException: If OpenStack API call fails
        """
        try:
            # Get current quotas
            quotas = self.get_quotas(user_id, project_id)
            
            checks = {}
            insufficient_resources = []
            all_available = True
            
            # Check compute resources
            if 'instances' in required_resources:
                required = required_resources['instances']
                available = quotas.get('compute', {}).get('instances', {}).get('available', -1)
                sufficient = available == -1 or available >= required
                checks['instances'] = {
                    'required': required,
                    'available': available,
                    'sufficient': sufficient
                }
                if not sufficient:
                    all_available = False
                    insufficient_resources.append('instances')
            
            if 'cores' in required_resources:
                required = required_resources['cores']
                available = quotas.get('compute', {}).get('cores', {}).get('available', -1)
                sufficient = available == -1 or available >= required
                checks['cores'] = {
                    'required': required,
                    'available': available,
                    'sufficient': sufficient
                }
                if not sufficient:
                    all_available = False
                    insufficient_resources.append('cores')
            
            if 'ram' in required_resources:
                required = required_resources['ram']
                available = quotas.get('compute', {}).get('ram', {}).get('available', -1)
                sufficient = available == -1 or available >= required
                checks['ram'] = {
                    'required': required,
                    'available': available,
                    'sufficient': sufficient
                }
                if not sufficient:
                    all_available = False
                    insufficient_resources.append('ram')
            
            # Check block storage resources
            if 'volumes' in required_resources:
                required = required_resources['volumes']
                available = quotas.get('block_storage', {}).get('volumes', {}).get('available', -1)
                sufficient = available == -1 or available >= required
                checks['volumes'] = {
                    'required': required,
                    'available': available,
                    'sufficient': sufficient
                }
                if not sufficient:
                    all_available = False
                    insufficient_resources.append('volumes')
            
            if 'gigabytes' in required_resources:
                required = required_resources['gigabytes']
                available = quotas.get('block_storage', {}).get('gigabytes', {}).get('available', -1)
                sufficient = available == -1 or available >= required
                checks['gigabytes'] = {
                    'required': required,
                    'available': available,
                    'sufficient': sufficient
                }
                if not sufficient:
                    all_available = False
                    insufficient_resources.append('gigabytes')
            
            # Check network resources
            if 'networks' in required_resources:
                required = required_resources['networks']
                available = quotas.get('network', {}).get('network', {}).get('available', -1)
                sufficient = available == -1 or available >= required
                checks['networks'] = {
                    'required': required,
                    'available': available,
                    'sufficient': sufficient
                }
                if not sufficient:
                    all_available = False
                    insufficient_resources.append('networks')
            
            if 'ports' in required_resources:
                required = required_resources['ports']
                available = quotas.get('network', {}).get('port', {}).get('available', -1)
                sufficient = available == -1 or available >= required
                checks['ports'] = {
                    'required': required,
                    'available': available,
                    'sufficient': sufficient
                }
                if not sufficient:
                    all_available = False
                    insufficient_resources.append('ports')
            
            if 'floatingips' in required_resources:
                required = required_resources['floatingips']
                available = quotas.get('network', {}).get('floatingip', {}).get('available', -1)
                sufficient = available == -1 or available >= required
                checks['floatingips'] = {
                    'required': required,
                    'available': available,
                    'sufficient': sufficient
                }
                if not sufficient:
                    all_available = False
                    insufficient_resources.append('floatingips')
            
            if 'security_groups' in required_resources:
                required = required_resources['security_groups']
                available = quotas.get('network', {}).get('security_group', {}).get('available', -1)
                sufficient = available == -1 or available >= required
                checks['security_groups'] = {
                    'required': required,
                    'available': available,
                    'sufficient': sufficient
                }
                if not sufficient:
                    all_available = False
                    insufficient_resources.append('security_groups')
            
            result = {
                'available': all_available,
                'checks': checks,
                'insufficient_resources': insufficient_resources,
                'project_id': quotas.get('project_id'),
            }
            
            logger.info(
                f"Availability check for user {user_id}: {'available' if all_available else 'insufficient'}",
                extra={
                    "user_id": user_id,
                    "available": all_available,
                    "insufficient_resources": insufficient_resources
                }
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Error checking resource availability: {e}")
            raise BadRequestException(f"Failed to check resource availability: {str(e)}")
 
    def validate_deployment_resources(
        self,
        user_id: str,
        required_resources: Dict[str, Any],
        project_id: Optional[str] = None
    ) -> dict:
        """Validate resources for deployment - final check before deployment starts.
        
        This method performs a fresh check (bypasses cache) to ensure resources
        are still available at deployment time. Should be called immediately before
        starting a deployment.
        
        Args:
            user_id: User ID
            required_resources: Dict specifying required resources, e.g.:
                {
                    'instances': int,  # Number of VMs
                    'cores': int,      # Number of vCPUs
                    'ram': int,        # RAM in MB
                    'volumes': int,    # Number of volumes
                    'gigabytes': int,  # Storage in GB
                    'networks': int,   # Number of networks
                    'ports': int,      # Number of ports
                    'floatingips': int, # Number of floating IPs
                    'security_groups': int, # Number of security groups
                }
            project_id: Optional specific project ID
            
        Returns:
            Dict with validation results:
            {
                'valid': bool,  # True if deployment can proceed
                'checks': {
                    'instances': {'required': int, 'available': int, 'sufficient': bool},
                    ...
                },
                'insufficient_resources': [str],  # List of resource types that are insufficient
                'project_id': str,
            }
            
        Raises:
            NotFoundException: If no project found
            BadRequestException: If OpenStack API call fails or resources insufficient
        """
        try:
            # Force refresh to get latest quota data (bypass cache)
            quotas = self.get_quotas(user_id, project_id, use_cache=True, force_refresh=True)
            
            checks = {}
            insufficient_resources = []
            all_valid = True
            
            # Check compute resources
            if 'instances' in required_resources:
                required = required_resources['instances']
                available = quotas.get('compute', {}).get('instances', {}).get('available', -1)
                sufficient = available == -1 or available >= required
                checks['instances'] = {
                    'required': required,
                    'available': available,
                    'sufficient': sufficient
                }
                if not sufficient:
                    all_valid = False
                    insufficient_resources.append('instances')
            
            if 'cores' in required_resources:
                required = required_resources['cores']
                available = quotas.get('compute', {}).get('cores', {}).get('available', -1)
                sufficient = available == -1 or available >= required
                checks['cores'] = {
                    'required': required,
                    'available': available,
                    'sufficient': sufficient
                }
                if not sufficient:
                    all_valid = False
                    insufficient_resources.append('cores')
            
            if 'ram' in required_resources:
                required = required_resources['ram']
                available = quotas.get('compute', {}).get('ram', {}).get('available', -1)
                sufficient = available == -1 or available >= required
                checks['ram'] = {
                    'required': required,
                    'available': available,
                    'sufficient': sufficient
                }
                if not sufficient:
                    all_valid = False
                    insufficient_resources.append('ram')
            
            # Check block storage resources
            if 'volumes' in required_resources:
                required = required_resources['volumes']
                available = quotas.get('block_storage', {}).get('volumes', {}).get('available', -1)
                sufficient = available == -1 or available >= required
                checks['volumes'] = {
                    'required': required,
                    'available': available,
                    'sufficient': sufficient
                }
                if not sufficient:
                    all_valid = False
                    insufficient_resources.append('volumes')
            
            if 'gigabytes' in required_resources:
                required = required_resources['gigabytes']
                available = quotas.get('block_storage', {}).get('gigabytes', {}).get('available', -1)
                sufficient = available == -1 or available >= required
                checks['gigabytes'] = {
                    'required': required,
                    'available': available,
                    'sufficient': sufficient
                }
                if not sufficient:
                    all_valid = False
                    insufficient_resources.append('gigabytes')
            
            # Check network resources
            if 'networks' in required_resources:
                required = required_resources['networks']
                available = quotas.get('network', {}).get('network', {}).get('available', -1)
                sufficient = available == -1 or available >= required
                checks['networks'] = {
                    'required': required,
                    'available': available,
                    'sufficient': sufficient
                }
                if not sufficient:
                    all_valid = False
                    insufficient_resources.append('networks')
            
            if 'ports' in required_resources:
                required = required_resources['ports']
                available = quotas.get('network', {}).get('port', {}).get('available', -1)
                sufficient = available == -1 or available >= required
                checks['ports'] = {
                    'required': required,
                    'available': available,
                    'sufficient': sufficient
                }
                if not sufficient:
                    all_valid = False
                    insufficient_resources.append('ports')
            
            if 'floatingips' in required_resources:
                required = required_resources['floatingips']
                available = quotas.get('network', {}).get('floatingip', {}).get('available', -1)
                sufficient = available == -1 or available >= required
                checks['floatingips'] = {
                    'required': required,
                    'available': available,
                    'sufficient': sufficient
                }
                if not sufficient:
                    all_valid = False
                    insufficient_resources.append('floatingips')
            
            if 'security_groups' in required_resources:
                required = required_resources['security_groups']
                available = quotas.get('network', {}).get('security_group', {}).get('available', -1)
                sufficient = available == -1 or available >= required
                checks['security_groups'] = {
                    'required': required,
                    'available': available,
                    'sufficient': sufficient
                }
                if not sufficient:
                    all_valid = False
                    insufficient_resources.append('security_groups')
            
            result = {
                'valid': all_valid,
                'checks': checks,
                'insufficient_resources': insufficient_resources,
                'project_id': quotas.get('project_id'),
            }
            
            if not all_valid:
                error_msg = f"Insufficient resources for deployment: {', '.join(insufficient_resources)}"
                logger.warning(
                    f"Deployment validation failed for user {user_id}: {error_msg}",
                    extra={
                        "user_id": user_id,
                        "insufficient_resources": insufficient_resources,
                        "required_resources": required_resources
                    }
                )
                raise BadRequestException(error_msg)
            
            logger.info(
                f"Deployment validation passed for user {user_id}",
                extra={
                    "user_id": user_id,
                    "project_id": quotas.get('project_id'),
                    "required_resources": required_resources
                }
            )
            
            return result
            
        except BadRequestException:
            # Re-raise BadRequestException (e.g., insufficient resources)
            raise
        except Exception as e:
            logger.error(f"Error validating deployment resources: {e}")
            raise BadRequestException(f"Failed to validate deployment resources: {str(e)}")
