import json
from sqlalchemy.orm import Session

from src.repositories.deployment_repository import DeploymentRepository
from src.services.deployment_log_service import DeploymentLogService
from src.schemas.deployment import DeploymentCreate
from src.models.deployment import Deployment, DeploymentStatus, DeploymentMode
from src.models.deployment_log import DeploymentLogEventType, DeploymentLogLevel
from src.models.template_version import TemplateVersion
from src.models.course import Course
from src.core.exceptions import NotFoundException
from src.tasks.deploy_tasks import deploy_stack


class DeploymentService:
    """Service for deployment business logic."""
    
    def __init__(self, db: Session):
        """Initialize DeploymentService with database session."""
        self.db = db
        self.deployment_repo = DeploymentRepository(db)
        self.log_service = DeploymentLogService(db)
    
    def create_deployment(self, deployment_data: DeploymentCreate, request_id: str | None = None) -> Deployment:
        """Create a new deployment and trigger async deployment task.
        
        Args:
            deployment_data: Validated deployment creation data
            request_id: Request ID for tracing
            
        Returns:
            Created Deployment with status set to QUEUED
            
        Raises:
            NotFoundException: If template_version_id or course_id does not exist
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
        
        # Parse deployment_mode string to enum (case-insensitive)
        deployment_mode = DeploymentMode(deployment_data.deployment_mode.lower())
        
        # Create deployment record with initial status QUEUED
        deployment = self.deployment_repo.create(
            template_version_id=deployment_data.template_version_id,
            course_id=deployment_data.course_id,
            deployment_mode=deployment_mode,
            status=DeploymentStatus.QUEUED,
            config_json=deployment_data.config_json,
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
                "access_types": deployment_data.access_types
            },
            request_id=request_id
        )
        
        # Trigger async Celery task for Heat stack orchestration
        deploy_stack.delay(str(deployment.id))
        
        return deployment