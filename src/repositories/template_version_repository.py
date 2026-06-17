"""Template Version repository for database operations."""
from typing import Literal, Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.models.template import Template, TemplateVisibility
from src.models.template_version import TemplateVersion, TemplateVersionApprovalStatus
from src.models.template_version_file import TemplateVersionFile
from src.repositories.base_repository import BaseRepository


QueueSort = Literal[
    "created_at_desc",
    "created_at_asc",
    "template_name_asc",
    "template_name_desc",
]


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

    def list_by_approval_status(
        self,
        approval_status: TemplateVersionApprovalStatus,
        skip: int = 0,
        limit: int = 100,
        template_id: Optional[str | UUID] = None,
        visibility: Optional[TemplateVisibility] = None,
        sort: QueueSort = "created_at_desc",
    ) -> tuple[list[tuple[TemplateVersion, Template]], int]:
        """List versions filtered by approval status, joined with their template.

        Used by the admin approval queue. Returns `(rows, total)` where each row is
        a `(version, template)` tuple so the API can inline template metadata
        without a second query per row.

        Optional filters narrow the queue: `template_id` to a single template,
        `visibility` to public/private templates only. `sort` selects ordering;
        default is newest-first by `created_at`.
        """
        query = (
            self.db.query(self.model, Template)
            .join(Template, Template.id == self.model.template_id)
            .filter(self.model.approval_status == approval_status)
        )

        if template_id is not None:
            query = query.filter(self.model.template_id == str(template_id))

        if visibility is not None:
            query = query.filter(Template.visibility == visibility)

        total = query.with_entities(func.count(self.model.id)).scalar() or 0

        order_clauses = {
            "created_at_desc": (self.model.created_at.desc(),),
            "created_at_asc": (self.model.created_at.asc(),),
            "template_name_asc": (Template.name.asc(), self.model.created_at.desc()),
            "template_name_desc": (Template.name.desc(), self.model.created_at.desc()),
        }[sort]

        rows = (
            query.order_by(*order_clauses)
            .offset(skip)
            .limit(limit)
            .all()
        )

        return [(version, template) for version, template in rows], total

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
