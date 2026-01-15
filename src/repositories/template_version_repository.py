"""Template Version repository for database operations."""
from typing import Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.models.template_version import TemplateVersion
from src.models.template_version_file import TemplateVersionFile
from src.repositories.base_repository import BaseRepository


class TemplateVersionRepository(BaseRepository[TemplateVersion]):
    """Repository for TemplateVersion database operations."""

    def __init__(self, db: Session):
        """Initialize TemplateVersionRepository with database session.
        
        Args:
            db: SQLAlchemy database session
        """
        super().__init__(TemplateVersion, db)

    def get_by_template_id(
        self,
        template_id: str | UUID,
        active_only: bool = False
    ) -> list[TemplateVersion]:
        """Get all versions for a specific template.
        
        Args:
            template_id: Template ID
            active_only: Whether to return only active versions
            
        Returns:
            List of template versions
        """
        query = self.db.query(self.model).filter(
            self.model.template_id == str(template_id)
        )
        
        if active_only:
            query = query.filter(self.model.is_active)
        
        return query.order_by(self.model.created_at.desc()).all()

    def get_active_version(
        self,
        template_id: str | UUID
    ) -> Optional[TemplateVersion]:
        """Get the active version for a template.
        
        Args:
            template_id: Template ID
            
        Returns:
            Active version or None if no active version exists
        """
        return self.db.query(self.model).filter(
            self.model.template_id == str(template_id),
            self.model.is_active
        ).order_by(self.model.created_at.desc()).first()

    def get_by_commit_sha(
        self,
        template_id: str | UUID,
        git_commit_sha: str
    ) -> Optional[TemplateVersion]:
        """Get a version by its git commit SHA.
        
        Args:
            template_id: Template ID
            git_commit_sha: Git commit SHA
            
        Returns:
            Template version or None if not found
        """
        return self.db.query(self.model).filter(
            self.model.template_id == str(template_id),
            self.model.git_commit_sha == git_commit_sha
        ).first()

    def get_with_file_count(
        self,
        version_id: str | UUID
    ) -> Optional[dict]:
        """Get a version with file count.
        
        Args:
            version_id: Version ID
            
        Returns:
            Dictionary with version data and file_count, or None if not found
        """
        result = self.db.query(
            self.model,
            func.count(TemplateVersionFile.id).label('file_count')
        ).outerjoin(
            TemplateVersionFile,
            self.model.id == TemplateVersionFile.template_version_id
        ).filter(
            self.model.id == str(version_id)
        ).group_by(self.model.id).first()
        
        if not result:
            return None
        
        version, file_count = result
        return {
            "version": version,
            "file_count": file_count
        }

    def deactivate_other_versions(
        self,
        template_id: str | UUID,
        except_version_id: str | UUID
    ) -> int:
        """Deactivate all versions of a template except the specified one.
        
        Args:
            template_id: Template ID
            except_version_id: Version ID to keep active
            
        Returns:
            Number of deactivated versions
        """
        updated_count = self.db.query(self.model).filter(
            self.model.template_id == str(template_id),
            self.model.id != str(except_version_id),
            self.model.is_active
        ).update({self.model.is_active: False})
        
        self.db.commit()
        return updated_count

    def delete_by_template_id(
        self,
        template_id: str | UUID
    ) -> int:
        """Delete all versions for a specific template.
        
        Args:
            template_id: Template ID
            
        Returns:
            Number of deleted versions
        """
        deleted_count = self.db.query(self.model).filter(
            self.model.template_id == str(template_id)
        ).delete()
        
        self.db.commit()
        return deleted_count
