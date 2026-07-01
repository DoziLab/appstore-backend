"""TemplateIcon repository for database operations."""
from typing import Optional

from sqlalchemy.orm import Session

from src.models.template_icon import TemplateIcon
from src.repositories.base_repository import BaseRepository


class TemplateIconRepository(BaseRepository[TemplateIcon]):
    """Repository for TemplateIcon database operations."""

    def __init__(self, db: Session):
        """Initialize TemplateIconRepository with database session."""
        super().__init__(TemplateIcon, db)

    def get_by_template_id(self, template_id: str) -> Optional[TemplateIcon]:
        """Fetch the icon row for a given template, if any."""
        return (
            self.db.query(self.model)
            .filter(self.model.template_id == str(template_id))
            .first()
        )

    def delete_by_template_id(self, template_id: str) -> bool:
        """Remove the icon row for a given template.

        Returns True if a row was deleted, False if nothing existed.
        """
        icon = self.get_by_template_id(template_id)
        if not icon:
            return False
        self.db.delete(icon)
        self.db.commit()
        return True
