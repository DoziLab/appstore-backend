import json
from typing import Optional, Union
from uuid import UUID
from sqlalchemy.orm import Session

from src.repositories.deployment_repository import DeploymentRepository
from src.repositories.openstack_project_repository import OpenstackProjectRepository
from src.services.deployment_log_service import DeploymentLogService
from src.services.openstack_heat_service import HeatStackService
from src.schemas.deployment import DeploymentCreate
from src.models.deployment import Deployment, DeploymentStatus
from src.models.deployment_log import DeploymentLogEventType, DeploymentLogLevel
from src.models.template_version import TemplateVersion
from src.models.openstack_project import OpenstackProject
from src.core.exceptions import NotFoundException
from src.core.exceptions import BadRequestException
from src.services.template_version_file_service import TemplateVersionFileService
from src.tasks.deploy_tasks import deploy_stack
from src.utils.deployment_expiry import compute_expiry, compute_extension, utcnow


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
            deployment_data: Validated deployment creation data with stack_assignments and teacher
            request_id: Request ID for tracing
            
        Returns:
            Created Deployment with status set to QUEUED
            
        Raises:
            NotFoundException: If template_version_id does not exist, or app.yaml not found
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
        
        # Validate template parameters required by the template version
        template_file_service = TemplateVersionFileService(self.db)
        try:
            template_params_resp = template_file_service.get_template_parameters(
                str(template_version.id),
                skip_access_check=True
            )
            template_params_map = {p.name: p for p in template_params_resp.parameters}
        except NotFoundException:
            raise
        except Exception as e:
            raise BadRequestException(f"Failed to read template parameters: {e}")

        provided = deployment_data.parameters or {}

        # Backend always injects these — never required from the caller
        backend_managed = {"user_json", "admin_credentials", "key_name"}

        # Validate all required parameters from app.yaml are provided
        required_params = [
            p.name for p in template_params_resp.parameters
            if p.required and p.name not in backend_managed
        ]
        if required_params:
            missing = [p for p in required_params if p not in provided]
            if missing:
                raise BadRequestException(f"Missing required template parameters: {', '.join(missing)}")

        # Type validation for provided parameters
        type_errors = []
        for param_name, param_value in provided.items():
            if param_name not in template_params_map:
                continue
            expected_type = template_params_map[param_name].type.lower()
            if expected_type == "boolean":
                if not isinstance(param_value, bool):
                    type_errors.append(f"{param_name}: expected boolean, got {type(param_value).__name__}")
            elif expected_type in ["number", "int", "integer"]:
                if not isinstance(param_value, (int, float)):
                    type_errors.append(f"{param_name}: expected number, got {type(param_value).__name__}")
            elif expected_type == "string":
                if not isinstance(param_value, str):
                    type_errors.append(f"{param_name}: expected string, got {type(param_value).__name__}")
        if type_errors:
            raise BadRequestException(f"Type validation errors: {'; '.join(type_errors)}")

        # Get template name for template-specific user_json generation
        from src.models.template import Template
        template = self.db.query(Template).filter(
            Template.id == template_version.template_id
        ).first()
        
        if not template:
            raise NotFoundException(
                f"Template not found for version {template_version.id}"
            )
        
        # Get or create Course entry based on keycloak_course_id
        # The course_id from frontend is the Keycloak group ID
        from src.models.course import Course
        keycloak_course_id = deployment_data.course_id
        
        course = self.db.query(Course).filter(
            Course.keycloak_course_id == keycloak_course_id
        ).first()
        
        if not course:
            # Auto-create course entry with deployment name as course name
            course = Course(
                name=deployment_data.name,
                keycloak_course_id=keycloak_course_id
            )
            self.db.add(course)
            self.db.flush()  # Get the ID without committing
        
        # Resolve and validate the target OpenStack project: must belong to the
        # teacher submitting this request. Persisting the local FK here makes the
        # deployment-to-project relationship explicit instead of re-deriving it
        # from teacher.id at every read site (deploy/restart/delete tasks).
        from src.models.user import User as UserModel
        teacher_user = self.db.query(UserModel).filter(
            UserModel.external_id == deployment_data.teacher.id
        ).first()
        if not teacher_user:
            raise NotFoundException(
                f"Teacher user not found for Keycloak ID {deployment_data.teacher.id}"
            )

        openstack_project = self.openstack_repo.get_by_id(
            deployment_data.openstack_project_id
        )
        if not openstack_project:
            raise NotFoundException(
                f"OpenStack project {deployment_data.openstack_project_id} not found"
            )
        if openstack_project.owner_user_id != teacher_user.id:
            raise BadRequestException(
                "OpenStack project does not belong to teacher"
            )

        # Store complete deployment info as JSON
        deployment_parameters = json.dumps({
            "template_name": template.name,
            "parameters": provided,
            "stack_assignments": [sa.model_dump() for sa in deployment_data.stack_assignments],
            "teacher": deployment_data.teacher.model_dump()
        })

        # Create deployment record with initial status QUEUED
        # Use course.id (DB ID) instead of keycloak_course_id
        # Compute expiry timestamps from runtime_months so the daily Beat
        # sweep knows when to delete and the UI knows when to start warning.
        now = utcnow()
        expires_at, expiry_warning_at = compute_expiry(now, deployment_data.runtime_months)

        deployment = self.deployment_repo.create(
            name=deployment_data.name,
            template_version_id=deployment_data.template_version_id,
            course_id=str(course.id),  # Use DB course ID, not Keycloak group ID
            openstack_project_id=openstack_project.id,
            status=DeploymentStatus.QUEUED,
            deployment_parameters=deployment_parameters,
            expires_at=expires_at,
            expiry_warning_at=expiry_warning_at,
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
                "keycloak_group_id": deployment_data.course_id,
                "stack_count": len(deployment_data.stack_assignments),
                "total_groups": sum(len(sa.groups) for sa in deployment_data.stack_assignments),
                "has_parameters": bool(deployment_data.parameters),
                "runtime_months": deployment_data.runtime_months,
                "expires_at": expires_at.isoformat(),
            },
            request_id=request_id
        )
        
        # Trigger async Celery task for Heat stack orchestration
        deploy_stack.delay(str(deployment.id))

        return deployment

    def extend_deployment(self, deployment_id: str, runtime_months: int) -> Deployment:
        """Push ``expires_at`` out by ``runtime_months`` months.

        Anchored on ``max(now, current_expires_at)`` so that an
        already-expired-but-not-yet-deleted deployment is extended from now
        rather than from the stale past, while a still-valid deployment
        stacks the new window on top of its existing end date.

        The companion ``expiry_warning_at`` is recomputed from the new
        runtime so the UI banner timing matches.

        Args:
            deployment_id: ID of the deployment to extend.
            runtime_months: Months to add (validated by ``DeploymentExtend``).

        Returns:
            The updated deployment.

        Raises:
            NotFoundException: If no such deployment exists.
            BadRequestException: If the deployment is in a terminal state
                                 (DELETED) where extending makes no sense.
        """
        deployment = self.deployment_repo.get_by_id(deployment_id)
        if not deployment:
            raise NotFoundException(f"Deployment {deployment_id} not found")

        if deployment.status == DeploymentStatus.DELETED:
            raise BadRequestException(
                "Deployment is already deleted and cannot be extended"
            )

        now = utcnow()
        new_expires_at, new_warning_at = compute_extension(
            now=now,
            current_expires_at=deployment.expires_at,
            runtime_months=runtime_months,
        )

        deployment.expires_at = new_expires_at
        deployment.expiry_warning_at = new_warning_at
        self.db.commit()
        self.db.refresh(deployment)

        # Audit trail — the lifecycle policy is operationally significant.
        self.log_service.log(
            deployment_id=str(deployment.id),
            event_type=DeploymentLogEventType.DEPLOYMENT_LIFETIME_EXTENDED,
            message=f"Deployment lifetime extended by {runtime_months} months",
            level=DeploymentLogLevel.INFO,
            details={
                "runtime_months_added": runtime_months,
                "expires_at": new_expires_at.isoformat(),
                "expiry_warning_at": new_warning_at.isoformat(),
            },
        )

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
            "status": deployment.status.value,
            "openstack_stack_id": deployment.openstack_stack_id,
            "deployment_parameters": deployment.deployment_parameters,
            "created_at": deployment.created_at.isoformat() if deployment.created_at else None,
            "updated_at": deployment.updated_at.isoformat() if deployment.updated_at else None,
            "openstack_data": None
        }
        
        # Only fetch OpenStack data if stack_id exists and deployment is not deleted
        if not deployment.openstack_stack_id or deployment.status == DeploymentStatus.DELETED:
            return deployment_dict
        
        try:
            # Use the deployment's persisted OpenStack project (FK) instead of
            # re-deriving it from teacher.id and grabbing the user's first
            # OpenstackProject row — which silently picked the wrong one
            # whenever a user had more than one.
            openstack_project = deployment.openstack_project
            if not openstack_project:
                return deployment_dict

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
                        stack_data['deployment_status'] = deployment.status.value
                    else:
                        stack_data['deployment_id'] = None
                        stack_data['course_id'] = None
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