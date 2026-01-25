import json
from typing import Optional, Union
from uuid import UUID
from sqlalchemy.orm import Session

from src.repositories.deployment_repository import DeploymentRepository
from src.repositories.openstack_project_repository import OpenstackProjectRepository
from src.services.deployment_log_service import DeploymentLogService
from src.services.openstack_heat_service import HeatStackService
from src.schemas.deployment import DeploymentCreate
from src.models.deployment import Deployment, DeploymentStatus, DeploymentMode
from src.models.deployment_log import DeploymentLogEventType, DeploymentLogLevel
from src.models.template_version import TemplateVersion
from src.models.course import Course
from src.models.openstack_project import OpenstackProject
from src.core.exceptions import NotFoundException
from src.core.exceptions import BadRequestException
from src.services.template_version_file_service import TemplateVersionFileService
from src.tasks.deploy_tasks import deploy_stack


class DeploymentService:
    """Service for deployment business logic."""
    
    def __init__(self, db: Session):
        """Initialize DeploymentService with database session."""
        self.db = db
        self.deployment_repo = DeploymentRepository(db)
        self.openstack_repo = OpenstackProjectRepository(db)
        self.log_service = DeploymentLogService(db)
    
    def create_deployment(self, deployment_data: DeploymentCreate, request_id: Union[str, None] = None) -> Deployment:
        """Create a new deployment and trigger async deployment task.
        
        Args:
            deployment_data: Validated deployment creation data
            request_id: Request ID for tracing
            
        Returns:
            Created Deployment with status set to QUEUED
            
        Raises:
            NotFoundException: If template_version_id or course_id does not exist, or app.yaml not found
            BadRequestException: If required heat_parameters are missing or have invalid types
        """
        # Validate template_version_id exists
        template_version = self.db.query(TemplateVersion).filter(
            TemplateVersion.id == deployment_data.template_version_id
        ).first()
        
        if not template_version:
            raise NotFoundException(
                f"Template version with ID '{deployment_data.template_version_id}' not found"
            )
        
        # Validate course_id exists
        course = self.db.query(Course).filter(
            Course.id == deployment_data.course_id
        ).first()
        
        if not course:
            raise NotFoundException(
                f"Course with ID '{deployment_data.course_id}' not found"
            )
        
        # Convert access_types list to JSON string
        access_types_json = json.dumps(deployment_data.access_types or ["ssh"])
        
        # Serialize heat_parameters to JSON if provided
        deployment_parameters = None
        # Validate template parameters required by the template version
        template_file_service = TemplateVersionFileService(self.db)
        try:
            template_params_resp = template_file_service.get_template_parameters(deployment_data.template_version_id)
            template_params_map = {p.name: p for p in template_params_resp.parameters}
            required_params = [p.name for p in template_params_resp.parameters if p.required]
        except NotFoundException:
            # If app.yaml not found, bubble up as NotFoundException
            raise
        except Exception as e:
            # Any parsing/validation error is translated to BadRequest
            raise BadRequestException(f"Failed to read template parameters: {e}")

        provided = deployment_data.heat_parameters or {}
        
        # Check for missing required parameters
        if required_params:
            missing = [p for p in required_params if p not in provided or provided.get(p) is None]
            if missing:
                raise BadRequestException(f"Missing required template parameters: {', '.join(missing)}")
        
        # Type validation for provided parameters
        type_errors = []
        for param_name, param_value in provided.items():
            if param_name not in template_params_map:
                # Allow extra parameters (Heat will ignore them)
                continue
            
            expected_type = template_params_map[param_name].type.lower()
            actual_value = param_value
            
            # Type checking based on declared parameter type
            if expected_type == "boolean":
                if not isinstance(actual_value, bool):
                    type_errors.append(f"{param_name}: expected boolean, got {type(actual_value).__name__}")
            elif expected_type in ["number", "int", "integer"]:
                if not isinstance(actual_value, (int, float)):
                    type_errors.append(f"{param_name}: expected number, got {type(actual_value).__name__}")
            elif expected_type == "string":
                if not isinstance(actual_value, str):
                    type_errors.append(f"{param_name}: expected string, got {type(actual_value).__name__}")
        
        if type_errors:
            raise BadRequestException(f"Type validation errors: {'; '.join(type_errors)}")

        if deployment_data.heat_parameters:
            deployment_parameters = json.dumps(deployment_data.heat_parameters)
        
        # Parse deployment_mode string to enum (case-insensitive)
        deployment_mode = DeploymentMode(deployment_data.deployment_mode.lower())
        
        # Create deployment record with initial status QUEUED
        deployment = self.deployment_repo.create(
            name=deployment_data.name,
            template_version_id=deployment_data.template_version_id,
            course_id=deployment_data.course_id,
            deployment_mode=deployment_mode,
            status=DeploymentStatus.QUEUED,
            config_json=deployment_data.config_json,
            deployment_parameters=deployment_parameters,
            access_types_json=access_types_json,
        )
        
        # Create initial log entry
        self.log_service.log(
            deployment_id=str(deployment.id),
            event_type=DeploymentLogEventType.DEPLOYMENT_STARTED,
            message=f"Deployment request received for template version {deployment_data.template_version_id}",
            level=DeploymentLogLevel.INFO,
            details={
                "template_version_id": deployment_data.template_version_id,
                "course_id": deployment_data.course_id,
                "deployment_mode": deployment_data.deployment_mode,
                "access_types": deployment_data.access_types,
                "has_heat_parameters": deployment_data.heat_parameters is not None
            },
            request_id=request_id
        )
        
        # Trigger async Celery task for Heat stack orchestration
        deploy_stack.delay(str(deployment.id))
        
        return deployment
    
    def list_deployments(
        self,
        skip: int = 0,
        limit: int = 100,
        course_id: Optional[UUID] = None,
        status: Optional[DeploymentStatus] = None,
    ) -> tuple[list[Deployment], int]:
        """List deployments with optional filters and pagination.
        
        Args:
            skip: Number of records to skip
            limit: Maximum number of records to return
            course_id: Filter by course ID
            status: Filter by deployment status
            
        Returns:
            Tuple of (list of deployments, total count)
        """
        return self.deployment_repo.get_all_filtered(
            skip=skip,
            limit=limit,
            course_id=course_id,
            status=status,
        )
    
    def enrich_with_openstack_data(self, deployment: Deployment) -> dict:
        """Enrich deployment with live OpenStack Heat stack data.
        
        Fetches current stack status, resources, and outputs from OpenStack API.
        Falls back to database values if OpenStack data is unavailable.
        
        Args:
            deployment: Deployment instance to enrich
            
        Returns:
            Dictionary with deployment data enriched with OpenStack information
        """
        deployment_dict: dict = {
            "id": str(deployment.id),
            "template_version_id": str(deployment.template_version_id),
            "course_id": str(deployment.course_id),
            "deployment_mode": deployment.deployment_mode.value,
            "status": deployment.status.value,
            "openstack_stack_id": deployment.openstack_stack_id,
            "config_json": deployment.config_json,
            "access_types_json": deployment.access_types_json,
            "created_at": deployment.created_at.isoformat() if deployment.created_at else None,
            "updated_at": deployment.updated_at.isoformat() if deployment.updated_at else None,
            "openstack_data": None
        }
        
        # Only fetch OpenStack data if stack_id exists and deployment is not deleted
        if not deployment.openstack_stack_id or deployment.status == DeploymentStatus.DELETED:
            return deployment_dict
        
        try:
            # Get lecturer's OpenStack project
            lecturer_id = deployment.course.lecturer_id
            openstack_projects = self.openstack_repo.get_by_owner(lecturer_id)
            
            if not openstack_projects:
                return deployment_dict
            
            openstack_project = openstack_projects[0]
            heat_service = HeatStackService(openstack_project)
            
            # Fetch live stack data from OpenStack
            stack_info = heat_service.get_stack(deployment.openstack_stack_id)
            
            # Try to get resources (non-critical)
            try:
                resources = heat_service.get_stack_resources(deployment.openstack_stack_id)
            except Exception:
                resources = []
            
            # Try to get outputs (non-critical)
            try:
                outputs = heat_service.get_stack_outputs(deployment.openstack_stack_id)
            except Exception:
                outputs = {}
            
            deployment_dict["openstack_data"] = {
                "stack": stack_info,
                "resources": resources,
                "outputs": outputs
            }
            
        except Exception as e:
            # Log error but don't fail the entire request
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                f"Failed to fetch OpenStack data for deployment {deployment.id}: {e}",
                exc_info=True
            )
        
        return deployment_dict
    
    def list_all_openstack_stacks(self, user_id: Optional[str] = None) -> list[dict]:
        """List all OpenStack Heat stacks with optional user filtering.
        
        Fetches stacks directly from OpenStack API and enriches them with
        deployment information from database if available.
        
        Args:
            user_id: Optional user ID to filter by. If None, returns all stacks (admin mode).
            
        Returns:
            List of stack information dicts with optional deployment metadata
        """
        import logging
        logger = logging.getLogger(__name__)
        
        # Get OpenStack projects based on user_id filter
        if user_id:
            # Lecturer mode: Get only user's projects
            openstack_projects = self.openstack_repo.get_by_owner(user_id)
            
            if not openstack_projects:
                logger.info("No OpenStack credentials found for user")
                return []
        else:
            # Admin mode: Get all projects from database
            openstack_projects = self.db.query(OpenstackProject).all()
            
            if not openstack_projects:
                logger.info("No OpenStack projects found in database")
                return []
        
        all_stacks = []
        
        # Fetch stacks from each OpenStack project
        for openstack_project in openstack_projects:
            try:
                heat_service = HeatStackService(openstack_project)
                stacks = heat_service.list_all_stacks()
                
                # Enrich with deployment data if available
                for stack in stacks:
                    stack_data = stack.copy()
                    stack_data['openstack_project_id'] = openstack_project.openstack_project_id
                    stack_data['openstack_project_name'] = openstack_project.openstack_project_name
                    stack_data['owner_user_id'] = openstack_project.owner_user_id
                    
                    # Try to find matching deployment in database
                    deployment = self.deployment_repo.db.query(Deployment).filter(
                        Deployment.openstack_stack_id == stack['stack_id']
                    ).first()
                    
                    if deployment:
                        stack_data['deployment_id'] = str(deployment.id)
                        stack_data['course_id'] = str(deployment.course_id)
                        stack_data['deployment_mode'] = deployment.deployment_mode.value
                        stack_data['deployment_status'] = deployment.status.value
                    else:
                        stack_data['deployment_id'] = None
                        stack_data['course_id'] = None
                        stack_data['deployment_mode'] = None
                        stack_data['deployment_status'] = None
                    
                    # Try to get stack resources (non-critical)
                    try:
                        resources = heat_service.get_stack_resources(stack['stack_id'])
                        stack_data['resources'] = resources
                    except Exception:
                        stack_data['resources'] = []
                    
                    # Try to get stack outputs (non-critical)
                    try:
                        outputs = heat_service.get_stack_outputs(stack['stack_id'])
                        stack_data['outputs'] = outputs
                    except Exception:
                        stack_data['outputs'] = {}
                    
                    all_stacks.append(stack_data)
                
                logger.info(
                    f"Retrieved {len(stacks)} stacks from OpenStack project {openstack_project.openstack_project_name}"
                )
                
            except Exception as e:
                logger.error(
                    f"Failed to fetch stacks from OpenStack project {openstack_project.openstack_project_id}: {e}",
                    exc_info=True
                )
                continue
        
        return all_stacks