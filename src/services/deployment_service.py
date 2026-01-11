from src.repositories.deployment_repository import DeploymentRepository
from src.schemas.deployment import DeploymentCreate
from src.models.deployment import Deployment
from src.tasks.deploy_tasks import deploy_stack
from sqlalchemy.orm import Session

class DeploymentService:
    """Service for deployment business logic."""
    
    def __init__(self, db: Session):
        """Initialize DeploymentService with database session."""
        self.db = db
        self.deployment_repo = DeploymentRepository(db)
    
    def create_deployment(self, deployment_data: DeploymentCreate) -> Deployment:
        """Create a new deployment."""
        deployment = self.deployment_repo.create(
            name=deployment_data.name,
            template_id=deployment_data.template_id
        )
        
        deploy_stack.delay(str(deployment.id))
        
        return deployment