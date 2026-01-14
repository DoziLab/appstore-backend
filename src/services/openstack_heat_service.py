"""OpenStack Heat service for stack management."""
import logging
import openstack
from openstack.exceptions import HttpException, SDKException
from typing import Optional

from src.models.openstack_project import OpenstackProject


logger = logging.getLogger(__name__)


class HeatStackService:
    """Service for managing OpenStack Heat stacks."""
    
    def __init__(self, openstack_project: OpenstackProject):
        """Initialize Heat service with OpenStack project credentials.
        
        Args:
            openstack_project: OpenstackProject with decrypted credentials
        """
        self.openstack_project = openstack_project
        self.conn: Optional[openstack.connection.Connection] = None
    
    def _get_connection(self) -> openstack.connection.Connection:
        """Get or create OpenStack connection using project credentials.
        
        Returns:
            OpenStack connection instance
            
        Raises:
            Exception: If connection fails
        """
        if self.conn is None:
            try:
                # Use credentials from database (automatically decrypted)
                self.conn = openstack.connect(
                    auth_url=self.openstack_project.auth_url,
                    project_name=self.openstack_project.openstack_project_name,
                    project_id=self.openstack_project.openstack_project_id,
                    username=self.openstack_project.username,
                    password=self.openstack_project.password,
                    user_domain_name=self.openstack_project.user_domain_name,
                    project_domain_name=self.openstack_project.user_domain_name,
                    region_name=self.openstack_project.region_name,
                )
                logger.info(
                    "OpenStack connection established successfully",
                    extra={
                        "project_id": self.openstack_project.openstack_project_id,
                        "region": self.openstack_project.region_name,
                    }
                )
            except Exception as e:
                logger.error(
                    f"Failed to establish OpenStack connection: {e}",
                    extra={
                        "project_id": self.openstack_project.openstack_project_id,
                        "auth_url": self.openstack_project.auth_url,
                    }
                )
                raise
        return self.conn
    
    def create_stack(
        self,
        stack_name: str,
        template: str,
        parameters: dict | None = None,
        tags: dict | None = None,
        timeout_mins: int = 60
    ) -> dict:
        """Create a new Heat stack.
        
        Args:
            stack_name: Name for the stack
            template: Heat template content (YAML string)
            parameters: Stack parameters
            tags: Tags to apply to the stack
            timeout_mins: Stack creation timeout in minutes
            
        Returns:
            Dict with stack information including stack_id
            
        Raises:
            HttpException: If OpenStack API call fails
            SDKException: If SDK operation fails
        """
        try:
            conn = self._get_connection()
            
            # Prepare stack creation parameters
            stack_params = {
                'name': stack_name,
                'template': template,
                'parameters': parameters or {},
                'timeout_mins': timeout_mins,
            }
            
            # Add tags if provided
            if tags:
                stack_params['tags'] = ','.join([f'{k}:{v}' for k, v in tags.items()])
            
            logger.info(f"Creating Heat stack: {stack_name}")
            logger.debug(f"Stack parameters: {parameters}")
            
            # Create stack
            stack = conn.orchestration.create_stack(**stack_params)
            
            logger.info(f"Heat stack created successfully: {stack.id}")
            
            return {
                'stack_id': stack.id,
                'stack_name': stack.name,
                'status': stack.status,
                'status_reason': stack.status_reason,
                'creation_time': str(stack.created_at) if stack.created_at else None,
            }
            
        except HttpException as e:
            logger.error(f"OpenStack API error creating stack {stack_name}: {e}")
            raise
        except SDKException as e:
            logger.error(f"OpenStack SDK error creating stack {stack_name}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error creating stack {stack_name}: {e}")
            raise
    
    def get_stack(self, stack_id: str) -> dict:
        """Get stack details.
        
        Args:
            stack_id: Stack ID or name
            
        Returns:
            Dict with stack information
            
        Raises:
            HttpException: If stack not found or API call fails
        """
        try:
            conn = self._get_connection()
            stack = conn.orchestration.find_stack(stack_id)
            
            if not stack:
                raise ValueError(f"Stack not found: {stack_id}")
            
            return {
                'stack_id': stack.id,
                'stack_name': stack.name,
                'status': stack.status,
                'status_reason': stack.status_reason,
                'creation_time': str(stack.created_at) if stack.created_at else None,
                'updated_time': str(stack.updated_at) if stack.updated_at else None,
            }
        except Exception as e:
            logger.error(f"Error getting stack {stack_id}: {e}")
            raise
    
    def delete_stack(self, stack_id: str) -> bool:
        """Delete a Heat stack.
        
        Args:
            stack_id: Stack ID or name
            
        Returns:
            True if deletion initiated successfully
            
        Raises:
            HttpException: If API call fails
        """
        try:
            conn = self._get_connection()
            
            logger.info(f"Deleting Heat stack: {stack_id}")
            conn.orchestration.delete_stack(stack_id)
            
            logger.info(f"Heat stack deletion initiated: {stack_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error deleting stack {stack_id}: {e}")
            raise
    
    def get_stack_resources(self, stack_id: str) -> list[dict]:
        """Get resources created by a stack.
        
        Args:
            stack_id: Stack ID or name
            
        Returns:
            List of resource information dicts
        """
        try:
            conn = self._get_connection()
            resources = conn.orchestration.resources(stack_id)
            
            return [
                {
                    'resource_name': r.name,
                    'resource_type': r.resource_type,
                    'physical_resource_id': r.physical_resource_id,
                    'status': r.status,
                    'status_reason': r.status_reason,
                }
                for r in resources
            ]
        except Exception as e:
            logger.error(f"Error getting stack resources for {stack_id}: {e}")
            raise
    
    def get_stack_outputs(self, stack_id: str) -> dict:
        """Get stack outputs.
        
        Args:
            stack_id: Stack ID or name
            
        Returns:
            Dict mapping output keys to their values
        """
        try:
            conn = self._get_connection()
            stack = conn.orchestration.find_stack(stack_id)
            
            if not stack or not stack.outputs:
                return {}
            
            return {
                output.get('output_key'): output.get('output_value')
                for output in stack.outputs
            }
        except Exception as e:
            logger.error(f"Error getting stack outputs for {stack_id}: {e}")
            raise
