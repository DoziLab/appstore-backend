"""User repository for database operations."""
from typing import Optional
from sqlalchemy.orm import Session
from src.models.user import User
from src.repositories.base_repository import BaseRepository


class UserRepository(BaseRepository[User]):
    """Repository for User model database operations."""
    
    def __init__(self, db: Session):
        super().__init__(User, db)
    
    def get_by_email(self, email: str) -> Optional[User]:
        """Get user by email address.
        
        Args:
            email: User's email address
            
        Returns:
            User if found, None otherwise
        """
        return self.db.query(User).filter(User.email == email).first()
    
    def get_by_external_id(self, external_id: str) -> Optional[User]:
        """Get user by external ID (e.g., from SSO provider).
        
        Args:
            external_id: External identifier for the user
            
        Returns:
            User if found, None otherwise
        """
        return self.db.query(User).filter(User.external_id == external_id).first()
