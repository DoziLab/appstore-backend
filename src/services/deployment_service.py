import json
from sqlalchemy.orm import Session

from src.repositories.deployment_repository import DeploymentRepository
from src.schemas.deployment import DeploymentCreate
from src.models.deployment import Deployment, DeploymentStatus, DeploymentMode
from src.tasks.deploy_tasks import deploy_stack


class DeploymentService:
    """Service for deployment business logic."""
    
    def __init__(self, db: Session):
        """Initialize DeploymentService with database session."""
        self.db = db
        self.deployment_repo = DeploymentRepository(db)
    
    def create_deployment(self, deployment_data: DeploymentCreate) -> Deployment:
        """Create a new deployment and trigger async deployment task.
        
        Args:
            deployment_data: Validated deployment creation data
            
        Returns:
            Created Deployment with status set to QUEUED
        """
        # Convert access_types list to JSON string
        access_types_json = json.dumps(deployment_data.access_types or ["ssh"])
        
        # Parse deployment_mode string to enum
        deployment_mode = DeploymentMode(deployment_data.deployment_mode)
        
        # Create deployment record with initial status QUEUED
        deployment = self.deployment_repo.create(
            template_version_id=deployment_data.template_version_id,
            course_id=deployment_data.course_id,
            deployment_mode=deployment_mode,
            status=DeploymentStatus.QUEUED,
            config_json=deployment_data.config_json,
            access_types_json=access_types_json,
        )
        
        # Trigger async Celery task for Heat stack orchestration
        deploy_stack.delay(str(deployment.id))
        
        return deployment