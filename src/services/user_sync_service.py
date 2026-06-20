"""User synchronization service for Keycloak integration.

Handles automatic creation/update of local User records from Keycloak tokens.
"""
import logging
from typing import Optional

from sqlalchemy.orm import Session

from src.models.user import User
from src.repositories.base_repository import BaseRepository

logger = logging.getLogger(__name__)


class UserRepository(BaseRepository[User]):
    """Repository for User CRUD operations."""
    
    def __init__(self, db: Session):
        """Initialize UserRepository."""
        super().__init__(User, db)
    
    def get_by_external_id(self, external_id: str) -> Optional[User]:
        """Get user by Keycloak external ID (sub claim).
        
        Args:
            external_id: Keycloak user UUID (sub claim from token)
            
        Returns:
            User if found, None otherwise
        """
        return self.db.query(User).filter(User.external_id == external_id).first()


class UserSyncService:
    """Service for synchronizing users from Keycloak to local database.
    
    Implements "sync on first use" pattern:
      - User logs in → Token validated → User synced
      - Creates user if not exists
      - Updates user attributes if changed
    """
    
    def __init__(self, db: Session):
        """Initialize UserSyncService.
        
        Args:
            db: Database session
        """
        self.db = db
        self.user_repo = UserRepository(db)
    
    def sync_user_from_token(self, token_payload: dict) -> User:
        """Sync user from Keycloak token payload.

        Creates user on first login, updates last_login_at on subsequent
        logins, and refreshes the cached display fields (display_name, email,
        username) whenever the token claims differ from what's stored. Roles
        are NEVER stored — they remain on the token.

        Args:
            token_payload: Decoded JWT token from Keycloak with claims:
                - sub: Keycloak user UUID (required)
                - name: Full display name (optional)
                - email: User email (optional)
                - preferred_username: Username (optional)

        Returns:
            User record (created or updated with fresh last_login_at and
            display fields).

        Example token_payload:
            {
                "sub": "abc-123-def",
                "email": "lecturer@example.com",
                "name": "Test Lecturer",
                "preferred_username": "tlecturer",
                "realm_access": {"roles": ["lecturer"]}
            }
        """
        external_id = token_payload.get("sub")
        if not external_id:
            raise ValueError("Token payload missing 'sub' claim (Keycloak user ID)")

        # Cached display fields from the token (None if claim is absent).
        display_name = token_payload.get("name")
        email = token_payload.get("email")
        username = token_payload.get("preferred_username")

        # Check if user exists
        existing_user = self.user_repo.get_by_external_id(external_id)

        if existing_user:
            # Update last login timestamp; refresh display fields if they
            # changed in Keycloak since the previous login.
            from datetime import datetime, timezone
            existing_user.last_login_at = datetime.now(timezone.utc)
            if existing_user.display_name != display_name:
                existing_user.display_name = display_name
            if existing_user.email != email:
                existing_user.email = email
            if existing_user.username != username:
                existing_user.username = username
            self.db.commit()
            self.db.refresh(existing_user)

            logger.debug(f"User {external_id} login recorded")
            return existing_user

        else:
            # Create new user record (ID mapping + cached display fields).
            new_user = self.user_repo.create(
                external_id=external_id,
                display_name=display_name,
                email=email,
                username=username,
            )

            logger.info(
                f"New user registered from Keycloak: {external_id}",
                extra={
                    "user_id": new_user.id,
                    "external_id": external_id,
                    "event": "user_created"
                }
            )

            return new_user
    
    def deactivate_user(self, external_id: str) -> None:
        """Remove user reference (not needed - just document deletion).
        
        When user is deleted in Keycloak, their token becomes invalid.
        No need to soft-delete in our DB since we don't store user state.
        Historical records (courses, templates) remain with user.id foreign key.
        
        Args:
            external_id: Keycloak user UUID
        """
        logger.info(
            f"User {external_id} deleted in Keycloak - token will be rejected on next request",
            extra={"external_id": external_id, "event": "user_deleted"}
        )
