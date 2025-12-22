"""Base repository providing common CRUD operations.

This module implements the Repository pattern for database access,
providing a generic base class that can be extended for specific models.
"""
from typing import Generic, TypeVar, Type, List, Optional, Dict, Any
from uuid import UUID
import logging

from sqlalchemy.orm import Session, base
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError


logger = logging.getLogger(__name__)

# Generic type variable constrained to SQLAlchemy Base models
ModelType = TypeVar("ModelType", bound=base)


class BaseRepository(Generic[ModelType]):
    """Generic repository for common database operations.
    
    This class provides standard CRUD (Create, Read, Update, Delete) operations
    for any SQLAlchemy model. Extend this class for model-specific repositories.
    
    Example:
        class UserRepository(BaseRepository[User]):
            def __init__(self, db: Session):
                super().__init__(User, db)
            
            def get_by_email(self, email: str) -> Optional[User]:
                return self.db.query(self.model).filter(
                    self.model.email == email
                ).first()
    """
    
    def __init__(self, model: Type[ModelType], db: Session):
        """Initialize repository with model class and database session.
        
        Args:
            model: SQLAlchemy model class (e.g., User, Course)
            db: SQLAlchemy database session
        """
        self.model = model
        self.db = db
    
    def create(self, **kwargs) -> ModelType:
        """Create a new database record.
        
        Args:
            **kwargs: Field values for the new instance
            
        Returns:
            Created model instance with generated ID
            
        Raises:
            SQLAlchemyError: If database operation fails
        """
        try:
            instance = self.model(**kwargs)
            self.db.add(instance)
            self.db.commit()
            self.db.refresh(instance)
            
            logger.info(
                f"Created {self.model.__name__} instance",
                extra={"model": self.model.__name__, "id": str(instance.id)}
            )
            
            return instance
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.error(
                f"Error creating {self.model.__name__}: {e}",
                exc_info=True
            )
            raise
    
    def get_by_id(self, id: UUID | str) -> Optional[ModelType]:
        """Retrieve a record by its UUID or string ID.
        
        Args:
            id: UUID or string ID of the record
            
        Returns:
            Model instance if found, None otherwise
        """
        return self.db.query(self.model).filter(self.model.id == str(id)).first()
    
    def get_all(self, skip: int = 0, limit: int = 100) -> List[ModelType]:
        """Retrieve all records with pagination.
        
        Args:
            skip: Number of records to skip (offset)
            limit: Maximum number of records to return
            
        Returns:
            List of model instances
        """
        return self.db.query(self.model).offset(skip).limit(limit).all()
    
    def get_multi(
        self, 
        skip: int = 0, 
        limit: int = 100, 
        filters: Optional[Dict[str, Any]] = None
    ) -> List[ModelType]:
        """Retrieve records with optional filtering and pagination.
        
        Args:
            skip: Number of records to skip (offset)
            limit: Maximum number of records to return
            filters: Dictionary of field-value pairs to filter by
                    (e.g., {"role": "ADMIN", "is_active": True})
            
        Returns:
            List of model instances matching filters
        """
        query = self.db.query(self.model)
        
        if filters:
            for key, value in filters.items():
                if hasattr(self.model, key):
                    query = query.filter(getattr(self.model, key) == value)
        
        return query.offset(skip).limit(limit).all()
    
    def count(self, filters: Optional[Dict[str, Any]] = None) -> int:
        """Count total number of records.
        
        Args:
            filters: Optional dictionary of field-value pairs to filter by
            
        Returns:
            Total count of records matching filters
        """
        query = self.db.query(func.count(self.model.id))
        
        if filters:
            for key, value in filters.items():
                if hasattr(self.model, key):
                    query = query.filter(getattr(self.model, key) == value)
        
        return query.scalar()
    
    def update(self, id: UUID, **kwargs) -> Optional[ModelType]:
        """Update a record by ID.
        
        Args:
            id: UUID of the record to update
            **kwargs: Field-value pairs to update
            
        Returns:
            Updated model instance if found, None otherwise
            
        Raises:
            SQLAlchemyError: If database operation fails
        """
        try:
            instance = self.get_by_id(id)
            if instance:
                for key, value in kwargs.items():
                    if hasattr(instance, key):
                        setattr(instance, key, value)
                
                self.db.commit()
                self.db.refresh(instance)
                
                logger.info(
                    f"Updated {self.model.__name__} instance",
                    extra={"model": self.model.__name__, "id": str(id)}
                )
            
            return instance
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.error(
                f"Error updating {self.model.__name__} {id}: {e}",
                exc_info=True
            )
            raise
    
    def delete(self, id: UUID) -> bool:
        """Delete a record by ID.
        
        Args:
            id: UUID of the record to delete
            
        Returns:
            True if deleted successfully, False if not found
            
        Raises:
            SQLAlchemyError: If database operation fails
        """
        try:
            instance = self.get_by_id(id)
            if instance:
                self.db.delete(instance)
                self.db.commit()
                
                logger.info(
                    f"Deleted {self.model.__name__} instance",
                    extra={"model": self.model.__name__, "id": str(id)}
                )
                
                return True
            return False
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.error(
                f"Error deleting {self.model.__name__} {id}: {e}",
                exc_info=True
            )
            raise
