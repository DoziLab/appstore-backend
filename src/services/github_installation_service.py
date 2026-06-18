"""Service for the GitHub App installation linkage on a user.

Stores only ``users.github_installation_id`` (a 64-bit integer pointing at a
specific install of our GitHub App). Short-lived installation access tokens are
minted on demand by ``GithubAppService`` and never persisted.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from src.core.exceptions import NotFoundException
from src.models.user import User

logger = logging.getLogger(__name__)


class GithubInstallationService:
    """Persist and read the user ↔ GitHub-App-installation mapping."""

    def __init__(self, db: Session):
        self.db = db

    def _get_user(self, user_id: str) -> User:
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            raise NotFoundException(f"User with ID {user_id} not found")
        return user

    def set_installation(self, user_id: str, installation_id: int) -> User:
        """Link the user to a GitHub App installation. Replaces any existing link."""
        user = self._get_user(user_id)
        user.github_installation_id = installation_id
        self.db.commit()
        self.db.refresh(user)
        logger.info(
            "GitHub App installation linked to user",
            extra={"user_id": user_id, "installation_id": installation_id},
        )
        return user

    def clear_installation(self, user_id: str) -> User:
        """Remove the installation link (idempotent)."""
        user = self._get_user(user_id)
        user.github_installation_id = None
        self.db.commit()
        self.db.refresh(user)
        logger.info("GitHub App installation cleared", extra={"user_id": user_id})
        return user

    def get_installation_id(self, user_id: str) -> Optional[int]:
        """Return the user's installation ID, or None if not connected."""
        user = self._get_user(user_id)
        return user.github_installation_id
