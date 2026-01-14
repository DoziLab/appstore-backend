"""Template Version File repository for database operations."""
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from src.models.template_version_file import TemplateVersionFile, FileType
from src.repositories.base_repository import BaseRepository


class TemplateVersionFileRepository(BaseRepository[TemplateVersionFile]):
    """Repository for TemplateVersionFile database operations."""

    def __init__(self, db: Session):
        """Initialize TemplateVersionFileRepository with database session.
        
        Args:
            db: SQLAlchemy database session
        """
        super().__init__(TemplateVersionFile, db)

    def get_by_version_id(
        self,
        template_version_id: str | UUID,
        include_content: bool = False
    ) -> list[TemplateVersionFile]:
        """Get all files for a specific template version.
        
        Args:
            template_version_id: Template version ID
            include_content: Whether to include file content (default: False for performance)
            
        Returns:
            List of template version files
        """
        query = self.db.query(self.model).filter(
            self.model.template_version_id == str(template_version_id)
        )
        
        if not include_content:
            # Load all columns except content for performance
            query = query.with_entities(
                self.model.id,
                self.model.template_version_id,
                self.model.file_name,
                self.model.file_type,
                self.model.file_path,
                self.model.file_size,
                self.model.description,
                self.model.is_primary,
                self.model.order,
                self.model.created_at,
                self.model.updated_at
            )
        
        return query.order_by(self.model.order, self.model.file_name).all()

    def get_primary_file(
        self,
        template_version_id: str | UUID
    ) -> Optional[TemplateVersionFile]:
        """Get the primary deployment file for a template version.
        
        Args:
            template_version_id: Template version ID
            
        Returns:
            Primary file or None if not found
        """
        return self.db.query(self.model).filter(
            self.model.template_version_id == str(template_version_id),
            self.model.is_primary
        ).first()

    def get_by_file_type(
        self,
        template_version_id: str | UUID,
        file_type: FileType | str
    ) -> list[TemplateVersionFile]:
        """Get all files of a specific type for a template version.
        
        Args:
            template_version_id: Template version ID
            file_type: File type to filter by
            
        Returns:
            List of matching files
        """
        if isinstance(file_type, str):
            file_type = FileType(file_type)
            
        return self.db.query(self.model).filter(
            self.model.template_version_id == str(template_version_id),
            self.model.file_type == file_type
        ).order_by(self.model.order, self.model.file_name).all()

    def get_file_content(
        self,
        file_id: str | UUID
    ) -> Optional[str]:
        """Get only the content of a specific file.
        
        Args:
            file_id: File ID
            
        Returns:
            File content or None
        """
        result = self.db.query(self.model.content).filter(
            self.model.id == str(file_id)
        ).first()
        
        return result[0] if result else None

    def update_file_content(
        self,
        file_id: str | UUID,
        content: str,
        file_size: Optional[int] = None
    ) -> Optional[TemplateVersionFile]:
        """Update only the content and size of a file.
        
        Args:
            file_id: File ID
            content: New file content
            file_size: Optional file size in bytes
            
        Returns:
            Updated file or None if not found
        """
        file = self.get_by_id(file_id)
        if not file:
            return None
            
        file.content = content
        if file_size is not None:
            file.file_size = file_size
            
        self.db.commit()
        self.db.refresh(file)
        return file

    def delete_by_version_id(
        self,
        template_version_id: str | UUID
    ) -> int:
        """Delete all files for a specific template version.
        
        Args:
            template_version_id: Template version ID
            
        Returns:
            Number of deleted files
        """
        deleted_count = self.db.query(self.model).filter(
            self.model.template_version_id == str(template_version_id)
        ).delete()
        
        self.db.commit()
        return deleted_count
