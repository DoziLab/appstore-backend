"""GitHub App authentication helper.

Owns:
- App-level RS256 JWT minting (used to call ``/app/*`` endpoints).
- Installation access-token minting + in-process cache. Tokens are short-lived
  (~1h from GitHub) and refreshed when they have <5 minutes remaining.

The actual GitHub App private key, app id, and slug come from settings. This
service is the single point that knows how to authenticate to GitHub on behalf
of an installation.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import httpx
from jose import jwt as jose_jwt

from src.core.config import get_settings
from src.core.exceptions import BadRequestException

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
GITHUB_API_VERSION = "2026-03-10"

# How early to refresh a cached installation token before its real expiry.
TOKEN_REFRESH_LEEWAY_SECONDS = 5 * 60


@dataclass(frozen=True)
class _CachedToken:
    token: str
    expires_at: datetime  # tz-aware UTC


class GithubAppService:
    """Mint app JWTs and installation access tokens for our GitHub App."""

    # Class-level cache so multiple service instantiations share installation tokens.
    _cache: dict[int, _CachedToken] = {}
    _cache_lock = threading.Lock()

    def __init__(
        self,
        app_id: Optional[int] = None,
        private_key_pem: Optional[str] = None,
    ) -> None:
        settings = get_settings()
        self._app_id = app_id if app_id is not None else settings.github_app_id
        self._private_key = (
            private_key_pem if private_key_pem is not None else settings.github_app_private_key
        )

    def _require_configured(self) -> None:
        if not self._app_id or not self._private_key:
            raise BadRequestException(
                "GitHub App is not configured. Set GITHUB_APP_ID and "
                "GITHUB_APP_PRIVATE_KEY in the environment."
            )

    def mint_app_jwt(self) -> str:
        """RS256 JWT signed with the App private key. 9-minute TTL.

        Used as ``Authorization: Bearer <jwt>`` on ``/app/*`` endpoints.
        """
        self._require_configured()
        assert self._private_key is not None
        now = int(time.time())
        payload = {
            "iat": now - 60,  # tolerate small clock skew
            "exp": now + 9 * 60,
            "iss": self._app_id,
        }
        return jose_jwt.encode(payload, self._private_key, algorithm="RS256")

    def get_installation_token(self, installation_id: int) -> str:
        """Return a cached installation token, refreshing if near expiry."""
        self._require_configured()

        with self._cache_lock:
            cached = self._cache.get(installation_id)
            now = datetime.now(timezone.utc)
            if cached and (cached.expires_at - now).total_seconds() > TOKEN_REFRESH_LEEWAY_SECONDS:
                return cached.token

        token, expires_at = self._mint_installation_token(installation_id)
        with self._cache_lock:
            self._cache[installation_id] = _CachedToken(token=token, expires_at=expires_at)
        return token

    def _mint_installation_token(self, installation_id: int) -> tuple[str, datetime]:
        url = f"{GITHUB_API_BASE}/app/installations/{installation_id}/access_tokens"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.mint_app_jwt()}",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        }
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(url, headers=headers)

        if resp.status_code == 404:
            raise BadRequestException(
                f"GitHub installation {installation_id} not found. "
                "The user may have uninstalled the app on GitHub."
            )
        if resp.status_code >= 400:
            logger.warning(
                "Failed to mint GitHub installation token (status=%s, body=%s)",
                resp.status_code,
                resp.text[:200],
            )
            raise BadRequestException(
                f"Could not authenticate to GitHub for installation {installation_id}."
            )

        payload = resp.json()
        token = payload.get("token")
        expires_at_raw = payload.get("expires_at")
        if not token or not expires_at_raw:
            raise BadRequestException("GitHub returned an unexpected installation-token response.")
        expires_at = datetime.fromisoformat(expires_at_raw.replace("Z", "+00:00"))
        return token, expires_at

    def auth_headers_for_installation(self, installation_id: int) -> dict[str, str]:
        """Headers for repo-level calls authenticated as the installation."""
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.get_installation_token(installation_id)}",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        }

    def list_installation_repos(self, installation_id: int) -> list[dict]:
        """Return repos covered by the installation. Used by `/installation-status`."""
        repos: list[dict] = []
        page = 1
        with httpx.Client(timeout=10.0) as client:
            while True:
                resp = client.get(
                    f"{GITHUB_API_BASE}/installation/repositories",
                    headers=self.auth_headers_for_installation(installation_id),
                    params={"per_page": 100, "page": page},
                )
                if resp.status_code >= 400:
                    logger.warning(
                        "list_installation_repos failed (status=%s, installation=%s)",
                        resp.status_code,
                        installation_id,
                    )
                    return repos
                body = resp.json()
                page_repos = body.get("repositories", [])
                repos.extend(page_repos)
                if len(page_repos) < 100:
                    return repos
                page += 1

    def revoke_installation(self, installation_id: int) -> bool:
        """Best-effort: ask GitHub to suspend / uninstall this installation.

        Returns True on success. Failures are logged and swallowed because the
        local mapping has typically already been removed by the caller.
        """
        try:
            self._require_configured()
        except BadRequestException:
            return False

        url = f"{GITHUB_API_BASE}/app/installations/{installation_id}"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.mint_app_jwt()}",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        }
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.delete(url, headers=headers)
        except httpx.HTTPError as exc:
            logger.warning("revoke_installation HTTP error: %s", exc)
            return False

        if resp.status_code in (204, 404):
            with self._cache_lock:
                self._cache.pop(installation_id, None)
            return True
        logger.warning(
            "revoke_installation failed (status=%s, installation=%s)",
            resp.status_code,
            installation_id,
        )
        return False
