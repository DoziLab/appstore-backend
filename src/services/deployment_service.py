"""Deployment service for business logic."""
import re
from uuid import UUID
from typing import Optional
from sqlalchemy.orm import Session

from src.repositories.deployment_repository import DeploymentRepository
from src.schemas.deployment import DeploymentCreate
from src.models.deployment import Deployment, DeploymentStatus


class DeploymentService:
    """Service for deployment business logic."""
    
    def __init__(self, db: Session):
        """Initialize DeploymentService with database session.
        
        Args:
            db: SQLAlchemy database session
        """
        self.db = db
        self.deployment_repo = DeploymentRepository(db)
    
    def create_deployment(self, deployment_data: DeploymentCreate) -> Deployment:
        """Create a new deployment and trigger async deployment task.
        
        Args:
            deployment_data: Deployment creation data
            
        Returns:
            Created deployment model
            
        Raises:
            ValueError: If template_ref is invalid
        """
        # Validate template_ref format (basic validation)
        if not self._is_valid_template_ref(deployment_data.template_ref):
            raise ValueError("Invalid template_ref format. Expected Git URL or repository identifier.")
        
        # Generate default name if not provided
        deployment_name = deployment_data.name or self._generate_deployment_name(deployment_data.template_ref)
        
        # Create deployment record
        deployment_dict = {
            "name": deployment_name,
            "template_ref": deployment_data.template_ref,
            "course_id": deployment_data.course_id,
            "status": DeploymentStatus.PENDING,
        }
        
        deployment = self.deployment_repo.create(deployment_dict)
        
        # TODO: Trigger Celery task for async deployment
        # from src.tasks.deploy_tasks import start_deployment
        # start_deployment.delay(str(deployment.id))
        
        return deployment
    
    def get_deployment(self, deployment_id: UUID) -> Optional[Deployment]:
        """Get deployment by ID.
        
        Args:
            deployment_id: Deployment UUID
            
        Returns:
            Deployment if found, None otherwise
        """
        return self.deployment_repo.get_by_id(deployment_id)
    
    def list_deployments(self, course_id: Optional[UUID] = None, status: Optional[DeploymentStatus] = None, skip: int = 0, limit: int = 100):
        """List deployments with optional filters.
        
        Args:
            course_id: Optional course ID filter
            status: Optional status filter
            skip: Number of records to skip
            limit: Maximum number of records to return
            
        Returns:
            Tuple of (deployments list, total count)
        """
        if course_id:
            return self.deployment_repo.get_by_course_id(course_id, skip, limit)
        elif status:
            return self.deployment_repo.get_by_status(status, skip, limit)
        else:
            return self.deployment_repo.get_all(skip, limit)
    
    @staticmethod
    def _is_valid_template_ref(template_ref: str) -> bool:
        """Validate template reference format.
        
        Args:
            template_ref: Template reference string
            
        Returns:
            True if valid format, False otherwise
        """
        # Accept Git URLs or simple repo identifiers
        git_url_pattern = r"^(https?://|git@)[\w\-\.]+(/[\w\-\.]+)+\.git$"
        repo_identifier_pattern = r"^[\w\-]+/[\w\-]+$"
        
        return (
            bool(re.match(git_url_pattern, template_ref)) or
            bool(re.match(repo_identifier_pattern, template_ref)) or
            template_ref.startswith("https://") or
            template_ref.startswith("git@")
        )
    
    @staticmethod
    def _generate_deployment_name(template_ref: str) -> str:
        """Generate a default deployment name from template reference.
        
        Args:
            template_ref: Template reference string
            
        Returns:
            Generated deployment name
        """
        # Extract repository name from URL or identifier
        if "/" in template_ref:
            parts = template_ref.rstrip("/").rstrip(".git").split("/")
            repo_name = parts[-1]
        else:
            repo_name = template_ref
        
        # Sanitize and create name
        sanitized = re.sub(r"[^a-zA-Z0-9\-]", "-", repo_name).lower()
        return f"{sanitized}-deployment"