"""GitHub App install/disconnect/status endpoints.

Frontend never handles GitHub tokens. The flow is:

1. ``POST /auth/github/install`` — authenticated user gets back a signed
   ``install_url``. Frontend redirects the browser to it.
2. ``GET /auth/github/install-callback`` — GitHub redirects the user here
   after install. We verify the signed state, persist
   ``users.github_installation_id``, then redirect the browser to the
   frontend's confirmation page.
3. ``DELETE /auth/github/installation`` — user disconnects: clear our
   mapping and best-effort revoke the install on GitHub.
4. ``GET /auth/github/installation-status`` — what is currently linked,
   plus the repos the install covers.
"""
from __future__ import annotations

import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import RedirectResponse

from src.core.config import get_settings
from src.core.dependencies import CurrentUser, DBSession, RequestID, require_roles
from src.core.exceptions import BadRequestException
from src.core.response_builder import ResponseBuilder
from src.models.user import UserRole
from src.schemas.github_installation import (
    GithubInstallationStatus,
    GithubInstalledRepo,
    GithubInstallUrlResponse,
)
from src.services.github_app_service import GithubAppService
from src.services.github_installation_service import GithubInstallationService
from src.utils.oauth_state import sign_state, verify_state

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/auth/github", tags=["github-app"])


def _frontend_redirect(status_value: str, **extra: str) -> RedirectResponse:
    """Build a redirect to the frontend's post-install landing page."""
    settings = get_settings()
    base = settings.frontend_base_url.rstrip("/")
    params = {"status": status_value, **extra}
    return RedirectResponse(
        url=f"{base}/github/connected?{urlencode(params)}",
        status_code=status.HTTP_302_FOUND,
    )


@router.post(
    "/install",
    response_model=None,
    dependencies=[Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER))],
)
async def start_github_install(
    request_id: RequestID,
    current_user: CurrentUser,
):
    """Return a signed GitHub-App install URL for the calling user."""
    settings = get_settings()
    if not settings.github_app_slug:
        raise BadRequestException(
            "GitHub App is not configured. Set GITHUB_APP_SLUG in the environment."
        )

    state = sign_state(user_id=current_user["user_id"])
    install_url = (
        f"https://github.com/apps/{settings.github_app_slug}/installations/new"
        f"?state={state}"
    )
    response = GithubInstallUrlResponse(install_url=install_url)
    return ResponseBuilder.success(
        data=response.model_dump(mode="json"),
        message="GitHub install URL created",
        request_id=request_id,
    )


@router.get("/install-callback", response_class=RedirectResponse)
async def github_install_callback(
    db: DBSession,
    state: str = Query(..., description="HMAC-signed state from /install"),
    installation_id: int | None = Query(default=None),
    setup_action: str | None = Query(default=None),
):
    """GitHub redirects here after the user (de)installs the App.

    The signed ``state`` carries the initiating user's id; no Keycloak token
    is required (the browser-side redirect can't carry one).
    """
    try:
        user_id = verify_state(state)
    except BadRequestException as exc:
        logger.warning("github install-callback: invalid state (%s)", exc.detail)
        return _frontend_redirect("error", reason="invalid_state")

    if setup_action == "request":
        return _frontend_redirect("error", reason="request_pending")

    if installation_id is None:
        logger.warning("github install-callback: no installation_id (action=%s)", setup_action)
        return _frontend_redirect("error", reason="missing_installation_id")

    try:
        GithubInstallationService(db).set_installation(user_id, installation_id)
    except Exception:
        logger.exception("github install-callback: failed to persist installation_id")
        return _frontend_redirect("error", reason="persist_failed")

    return _frontend_redirect("ok")


@router.delete(
    "/installation",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER))],
)
async def disconnect_github_installation(
    db: DBSession,
    current_user: CurrentUser,
):
    """Clear the user's installation link and best-effort revoke on GitHub."""
    service = GithubInstallationService(db)
    installation_id = service.get_installation_id(current_user["user_id"])
    service.clear_installation(current_user["user_id"])

    if installation_id is not None:
        try:
            GithubAppService().revoke_installation(installation_id)
        except Exception:  # noqa: BLE001 - best-effort, never block the disconnect
            logger.warning("revoke_installation raised; ignoring", exc_info=True)
    return None


@router.get(
    "/installation-status",
    response_model=None,
    dependencies=[Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER))],
)
async def get_github_installation_status(
    db: DBSession,
    request_id: RequestID,
    current_user: CurrentUser,
):
    """Return the user's installation linkage and the repos it covers."""
    installation_id = GithubInstallationService(db).get_installation_id(
        current_user["user_id"]
    )
    if installation_id is None:
        response = GithubInstallationStatus(connected=False, installation_id=None, repos=[])
        return ResponseBuilder.success(
            data=response.model_dump(mode="json"),
            message="GitHub installation status retrieved",
            request_id=request_id,
        )

    repos: list[GithubInstalledRepo] = []
    try:
        for repo in GithubAppService().list_installation_repos(installation_id):
            owner_login = (repo.get("owner") or {}).get("login") or ""
            name = repo.get("name") or ""
            repos.append(
                GithubInstalledRepo(
                    owner=owner_login,
                    name=name,
                    full_name=repo.get("full_name") or f"{owner_login}/{name}",
                    private=bool(repo.get("private")),
                )
            )
    except BadRequestException:
        # App not configured or token mint failed - report connected but empty repos.
        logger.warning(
            "list_installation_repos failed for installation %s", installation_id
        )

    response = GithubInstallationStatus(
        connected=True,
        installation_id=installation_id,
        repos=repos,
    )
    return ResponseBuilder.success(
        data=response.model_dump(mode="json"),
        message="GitHub installation status retrieved",
        request_id=request_id,
    )
