import json
from sqlalchemy.orm import Session

from src.repositories.deployment_repository import DeploymentRepository
from src.repositories.template_content_repository import TemplateContentRepository
from src.schemas.deployment import DeploymentCreate
from src.models.deployment import Deployment, DeploymentStatus, DeploymentMode
from src.core.exceptions import ResourceNotFoundError
from src.tasks.deploy_tasks import deploy_stack


class DeploymentService:
    """Service for deployment business logic."""
    
    def __init__(self, db: Session):
        """Initialize DeploymentService with database session."""
        self.db = db
        self.deployment_repo = DeploymentRepository(db)
        self.template_content_repo = TemplateContentRepository(db)
    
    def create_deployment(self, deployment_data: DeploymentCreate) -> Deployment:
        """Create a new deployment and trigger async deployment task.
        
        Args:
            deployment_data: Validated deployment creation data
            
        Returns:
            Created Deployment with status set to QUEUED
            
        Raises:
            ResourceNotFoundError: If template content not found for given template_id and version
        """
        # Verify template content exists
        template_content = self.template_content_repo.get_by_template_and_version(
            deployment_data.template_id,
            deployment_data.version
        )
        if not template_content:
            raise ResourceNotFoundError(
                f"Template content not found for template_id={deployment_data.template_id} "
                f"and version={deployment_data.version}"
            )
        
        # Convert access_types list to JSON string
        access_types_json = json.dumps(deployment_data.access_types or ["ssh"])
        
        # Parse deployment_mode string to enum
        deployment_mode = DeploymentMode(deployment_data.deployment_mode)
        
        # Store template_id and version in config_json for later retrieval
        config = {}
        if deployment_data.config_json:
            config = json.loads(deployment_data.config_json)
        config["_template_id"] = deployment_data.template_id
        config["_template_version"] = deployment_data.version
        
        # Create deployment record with initial status QUEUED
        deployment = self.deployment_repo.create(
            template_version_id=template_content.id,  # Use template_content ID as reference
            course_id=deployment_data.course_id,
            deployment_mode=deployment_mode,
            status=DeploymentStatus.QUEUED,
            config_json=json.dumps(config),
            access_types_json=access_types_json,
        )
        
        # Trigger async Celery task for Heat stack orchestration
        deploy_stack.delay(str(deployment.id))
        
        return deployment
