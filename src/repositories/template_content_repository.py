"""Repository for TemplateContent model."""
from typing import Optional
from sqlalchemy.orm import Session

from src.models.template_content import TemplateContent
from src.repositories.base_repository import BaseRepository


class TemplateContentRepository(BaseRepository[TemplateContent]):
    """Repository for TemplateContent CRUD operations."""
    
    def __init__(self, db: Session):
        """Initialize TemplateContentRepository."""
        super().__init__(TemplateContent, db)
    
    def get_by_template_and_version(self, template_id: str, version: str) -> Optional[TemplateContent]:
        """Get template content by template ID and version.
        
        Args:
            template_id: Template ID
            version: Template version string
            
        Returns:
            TemplateContent if found, None otherwise
        """
        return (
            self.db.query(TemplateContent)
            .filter(
                TemplateContent.template_id == template_id,
                TemplateContent.version == version
            )
            .first()
        )
