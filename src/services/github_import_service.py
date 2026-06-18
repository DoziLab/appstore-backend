"""Convenience service that imports a Template / TemplateVersion from a GitHub URL.

Workflow:
    1. Resolve the URL into (owner, repo, ref, app_yaml_path).
    2. Pick the auth headers we'll use for GitHub:
       - If the user has linked our GitHub App installation that covers the
         repo, mint an installation access token (Contents: Read-only).
       - Otherwise, fall back to unauthenticated public-API calls (60/h limit).
       - If the repo is private and we have no covering installation, error out.
    3. Resolve `ref` -> commit SHA + tree SHA via the GitHub API.
    4. Fetch app.yaml so we can validate its shape and extract the version string.
    5. List the full repo tree (recursive) and keep every file under the
       directory that contains app.yaml.
    6. Download each of those files and persist them as TemplateVersionFile rows
       inside one new TemplateVersion (atomic).

We deliberately download the entire folder rather than only the files
referenced under `artifacts:` in app.yaml: sub-yaml files often link to
further assets, and users will keep adding new file types over time. Saving
the whole folder is the simplest way to stay future-proof.
"""
from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Tuple
from urllib.parse import unquote, urlparse
from uuid import uuid4

import httpx
import yaml
from sqlalchemy.orm import Session

from src.core.exceptions import BadRequestException, NotFoundException, ForbiddenException
from src.models.template import Template, TemplateVisibility
from src.models.template_version import TemplateVersion, TemplateVersionApprovalStatus
from src.models.template_version_file import TemplateVersionFile, FileType
from src.models.user import UserRole
from src.repositories.template_repository import TemplateRepository
from src.repositories.template_version_repository import TemplateVersionRepository
from src.repositories.template_version_file_repository import TemplateVersionFileRepository
from src.services.github_app_service import GITHUB_API_VERSION, GithubAppService
from src.services.github_installation_service import GithubInstallationService
from src.utils.app_manifest_parser import AppManifestParser

logger = logging.getLogger(__name__)


GITHUB_API_BASE = "https://api.github.com"
DEFAULT_APP_YAML_PATH = "app.yaml"
GITHUB_API_TIMEOUT = 30.0

# Sanity limits on the folder we mirror into the DB
MAX_FILES_PER_VERSION = 50
MAX_FILE_SIZE_BYTES = 1_000_000  # GitHub Contents API caps at 1MB anyway


@dataclass
class ParsedGithubUrl:
    """Components extracted from a GitHub URL."""
    owner: str
    repo: str
    ref: Optional[str]
    path_from_url: Optional[str]  # populated when URL is .../blob/<ref>/<path>


class GithubImportService:
    """Imports template content from GitHub into TemplateVersion + files."""

    def __init__(
        self,
        db: Session,
        github_app_service: Optional[GithubAppService] = None,
    ):
        self.db = db
        self.template_repo = TemplateRepository(db)
        self.version_repo = TemplateVersionRepository(db)
        self.file_repo = TemplateVersionFileRepository(db)
        self.installation_service = GithubInstallationService(db)
        self.github_app = github_app_service or GithubAppService()

    # ---------------------------------------------------------------------
    # URL parsing
    # ---------------------------------------------------------------------

    @staticmethod
    def parse_github_url(url: str) -> ParsedGithubUrl:
        """Parse a GitHub web URL into its components.

        Accepts:
          https://github.com/{owner}/{repo}
          https://github.com/{owner}/{repo}/tree/{ref}[/{path}]
          https://github.com/{owner}/{repo}/blob/{ref}/{path}
          (with or without trailing .git)
        """
        if not url or not isinstance(url, str):
            raise BadRequestException("github_url is required")

        parsed = urlparse(url.strip())
        if parsed.netloc not in ("github.com", "www.github.com"):
            raise BadRequestException(
                f"Only github.com URLs are supported (got '{parsed.netloc or url}')"
            )

        segments = [s for s in parsed.path.split("/") if s]
        if len(segments) < 2:
            raise BadRequestException(
                "GitHub URL must contain at least owner and repo: https://github.com/<owner>/<repo>"
            )

        owner = segments[0]
        repo = segments[1].removesuffix(".git")
        ref: Optional[str] = None
        path_from_url: Optional[str] = None

        if len(segments) >= 4 and segments[2] in ("tree", "blob"):
            ref = unquote(segments[3])
            if len(segments) > 4:
                path_from_url = "/".join(unquote(s) for s in segments[4:])
        elif len(segments) > 2:
            # Non-standard suffix - safer to reject than to misinterpret
            raise BadRequestException(
                "Unsupported GitHub URL shape. Use repo root, .../tree/<ref>, or .../blob/<ref>/<path>."
            )

        return ParsedGithubUrl(owner=owner, repo=repo, ref=ref, path_from_url=path_from_url)

    @staticmethod
    def _split_dir_and_filename(path: str) -> Tuple[str, str]:
        """Split 'foo/bar/app.yaml' into ('foo/bar', 'app.yaml')."""
        path = path.strip("/")
        if "/" not in path:
            return "", path
        directory, _, filename = path.rpartition("/")
        return directory, filename

    # ---------------------------------------------------------------------
    # GitHub API
    # ---------------------------------------------------------------------

    @staticmethod
    def _public_headers() -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
            "User-Agent": "appstore-backend",
        }

    def _installation_headers(self, installation_id: int) -> dict[str, str]:
        return {
            **self._public_headers(),
            "Authorization": f"Bearer {self.github_app.get_installation_token(installation_id)}",
        }

    def _resolve_repo_auth(
        self, user_id: str, owner: str, repo: str
    ) -> Tuple[dict[str, str], dict]:
        """Pick auth headers and load repo metadata in one pass.

        - If the user has linked an installation that covers the repo, returns
          installation-token headers + the ``GET /repos/{o}/{r}`` body.
        - Otherwise tries unauthenticated; falls back to that on 404 from the
          installation lookup (repo is public and not in the installation).
        - Raises if even the public lookup 404s and the user has no install
          (meaning the repo is private or doesn't exist) — message hints at
          installing the GitHub App.
        """
        installation_id = self.installation_service.get_installation_id(user_id)
        repo_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}"

        with httpx.Client(timeout=GITHUB_API_TIMEOUT) as client:
            if installation_id is not None:
                inst_headers = self._installation_headers(installation_id)
                resp = client.get(repo_url, headers=inst_headers)
                if resp.status_code == 200:
                    return inst_headers, resp.json()
                if resp.status_code in (401, 403):
                    raise BadRequestException(
                        "Your GitHub App installation was rejected by GitHub. "
                        "Reconnect via POST /auth/github/install."
                    )
                # 404: installation doesn't cover this repo. Fall through to
                # public fallback - the repo might still be public.

            pub_headers = self._public_headers()
            resp = client.get(repo_url, headers=pub_headers)
            if resp.status_code == 200:
                return pub_headers, resp.json()
            if resp.status_code == 404:
                if installation_id is None:
                    raise BadRequestException(
                        f"Repository '{owner}/{repo}' is not accessible. If it is private, "
                        "install our GitHub App on the repo first via POST /auth/github/install."
                    )
                raise BadRequestException(
                    f"Repository '{owner}/{repo}' is not covered by your GitHub App installation. "
                    "Add the repo to the installation in GitHub settings, or re-run "
                    "POST /auth/github/install to expand access."
                )
            raise BadRequestException(
                f"GitHub returned HTTP {resp.status_code} for repo '{owner}/{repo}': "
                f"{resp.text[:200]}"
            )

    def _get(
        self,
        client: httpx.Client,
        path: str,
        *,
        params: Optional[dict] = None,
    ) -> httpx.Response:
        url = f"{GITHUB_API_BASE}{path}"
        try:
            response = client.get(url, params=params)
        except httpx.HTTPError as e:
            logger.error("GitHub network error", extra={"url": url, "error": str(e)})
            raise BadRequestException(f"GitHub request failed: {e}") from e

        if response.status_code in (401, 403):
            raise BadRequestException(
                "GitHub rejected the request (auth invalid, expired, or insufficient scopes). "
                "Reconnect your GitHub App via POST /auth/github/install and retry."
            )
        if response.status_code == 404:
            raise NotFoundException(f"GitHub resource not found: {path}")
        if response.status_code >= 400:
            raise BadRequestException(
                f"GitHub returned HTTP {response.status_code}: {response.text[:200]}"
            )
        return response

    def _resolve_commit(
        self, client: httpx.Client, owner: str, repo: str, ref: str
    ) -> Tuple[str, str]:
        """Return (commit_sha, tree_sha) for the given ref."""
        response = self._get(client, f"/repos/{owner}/{repo}/commits/{ref}")
        data = response.json()
        commit_sha = data.get("sha")
        tree_sha = (data.get("commit") or {}).get("tree", {}).get("sha")
        if not commit_sha or not tree_sha:
            raise BadRequestException(f"Could not resolve commit/tree SHA for ref '{ref}'")
        return commit_sha, tree_sha

    def _list_tree_recursive(
        self, client: httpx.Client, owner: str, repo: str, tree_sha: str
    ) -> list[dict]:
        """Return the full recursive tree as a list of `{path, type, size, sha}` entries."""
        response = self._get(
            client,
            f"/repos/{owner}/{repo}/git/trees/{tree_sha}",
            params={"recursive": "1"},
        )
        data = response.json()
        if data.get("truncated"):
            logger.warning(
                "GitHub tree listing was truncated - some files may be missing",
                extra={"owner": owner, "repo": repo, "tree_sha": tree_sha},
            )
        return data.get("tree") or []

    def _fetch_file_content(
        self,
        client: httpx.Client,
        owner: str,
        repo: str,
        path: str,
        ref: str,
    ) -> str:
        """Fetch a file via the Contents API and return its decoded text.

        Strict variant: raises if the file is missing, is a directory, or is
        not valid UTF-8 text. Used for app.yaml where any of those situations
        is a real error worth surfacing.
        """
        response = self._get(
            client, f"/repos/{owner}/{repo}/contents/{path}", params={"ref": ref}
        )
        data = response.json()
        if isinstance(data, list):
            raise BadRequestException(
                f"Expected file at '{path}' but got a directory listing"
            )
        encoding = data.get("encoding")
        content = data.get("content")
        if encoding != "base64" or content is None:
            raise BadRequestException(
                f"Unsupported content encoding for '{path}': {encoding!r}"
            )
        try:
            return base64.b64decode(content).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as e:
            raise BadRequestException(f"Failed to decode '{path}' as UTF-8: {e}") from e

    def _try_fetch_text_file(
        self,
        client: httpx.Client,
        owner: str,
        repo: str,
        path: str,
        ref: str,
    ) -> Optional[str]:
        """Tolerant variant of _fetch_file_content for the bulk-folder pass.

        Returns None when the blob is binary / not UTF-8 / not base64-encoded.
        HTTP errors still propagate (those are real failures we want to see).
        """
        response = self._get(
            client, f"/repos/{owner}/{repo}/contents/{path}", params={"ref": ref}
        )
        data = response.json()
        if isinstance(data, list):
            return None
        encoding = data.get("encoding")
        content = data.get("content")
        if encoding != "base64" or content is None:
            return None
        try:
            return base64.b64decode(content).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None

    # ---------------------------------------------------------------------
    # Public entry points
    # ---------------------------------------------------------------------

    def import_to_new_template(
        self,
        *,
        github_url: str,
        app_yaml_path: Optional[str],
        name: str,
        description: Optional[str],
        icon_url: Optional[str],
        owner_user_id: str,
        owner_user_roles: list[str],
    ) -> Template:
        """Create a brand-new Template + first TemplateVersion populated from GitHub.

        New templates are always created PRIVATE (matching `TemplateService.create_template`);
        admins promote to public later via PATCH. The first version follows the standard
        per-version approval rules (PENDING unless admin + public).
        """
        template = Template(
            id=str(uuid4()),
            name=name,
            description=description,
            owner_id=owner_user_id,
            repo_url=github_url,
            icon_url=icon_url,
            visibility=TemplateVisibility.PRIVATE,
        )
        self.db.add(template)
        self.db.flush()

        try:
            self._import_version_for_template(
                template=template,
                github_url=github_url,
                app_yaml_path=app_yaml_path,
                user_id=owner_user_id,
                user_roles=owner_user_roles,
                is_active=True,
            )
        except Exception:
            self.db.rollback()
            raise

        self.db.commit()
        self.db.refresh(template)
        return template

    def import_to_existing_template(
        self,
        *,
        template_id: str,
        github_url: str,
        app_yaml_path: Optional[str],
        is_active: bool,
        user_id: str,
        user_roles: list[str],
    ) -> TemplateVersion:
        """Append a new TemplateVersion (with files) to an existing Template."""
        template = self.template_repo.get_by_id(template_id)
        if not template:
            raise NotFoundException(f"Template with ID {template_id} not found")

        is_admin = UserRole.ADMIN.value in user_roles
        if not is_admin and template.owner_id != user_id:
            raise ForbiddenException(
                "You do not have permission to import a new version for this template"
            )

        version = self._import_version_for_template(
            template=template,
            github_url=github_url,
            app_yaml_path=app_yaml_path,
            user_id=user_id,
            user_roles=user_roles,
            is_active=is_active,
        )
        self.db.commit()
        self.db.refresh(version)
        return version

    # ---------------------------------------------------------------------
    # Internal core
    # ---------------------------------------------------------------------

    def _import_version_for_template(
        self,
        *,
        template: Template,
        github_url: str,
        app_yaml_path: Optional[str],
        user_id: str,
        user_roles: list[str],
        is_active: bool,
    ) -> TemplateVersion:
        parsed_url = self.parse_github_url(github_url)

        # Resolve effective app.yaml path: explicit body parameter > URL blob path > default root.
        # Validate up front before any network calls so user input errors fail fast.
        effective_app_yaml_path = (
            app_yaml_path or parsed_url.path_from_url or DEFAULT_APP_YAML_PATH
        ).strip("/")
        if not effective_app_yaml_path.endswith(".yaml") and not effective_app_yaml_path.endswith(".yml"):
            raise BadRequestException(
                f"app.yaml path must end in .yaml or .yml (got '{effective_app_yaml_path}')"
            )
        base_dir, app_yaml_filename = self._split_dir_and_filename(effective_app_yaml_path)
        path_prefix = f"{base_dir}/" if base_dir else ""

        # Pick auth (installation token vs unauthenticated public) and verify
        # the repo is reachable before doing more work.
        headers, _repo_meta = self._resolve_repo_auth(
            user_id, parsed_url.owner, parsed_url.repo
        )

        with httpx.Client(timeout=GITHUB_API_TIMEOUT, headers=headers) as client:
            ref = parsed_url.ref or _repo_meta.get("default_branch")
            if not ref:
                raise BadRequestException(
                    f"Could not determine default branch for {parsed_url.owner}/{parsed_url.repo}"
                )
            commit_sha, tree_sha = self._resolve_commit(
                client, parsed_url.owner, parsed_url.repo, ref
            )

            # 1) Fetch app.yaml strictly so we can validate it and extract version + hints
            app_yaml_content = self._fetch_file_content(
                client, parsed_url.owner, parsed_url.repo, effective_app_yaml_path, commit_sha
            )

            try:
                parsed_manifest = AppManifestParser.parse(app_yaml_content)
            except (ValueError, yaml.YAMLError) as e:
                raise BadRequestException(f"Invalid app.yaml: {e}") from e

            # Hints from `artifacts:` are used to set file_type / is_primary on
            # files that the manifest explicitly declares. Everything else in
            # the folder still gets imported, just typed as OTHER.
            linked_files = AppManifestParser.get_linked_files(parsed_manifest)
            hints_by_relative_path = {entry["relative_path"]: entry for entry in linked_files}

            # 2) List the whole repo tree at this commit, keep only blobs under base_dir
            tree_entries = self._list_tree_recursive(
                client, parsed_url.owner, parsed_url.repo, tree_sha
            )
            folder_blobs = [
                e for e in tree_entries
                if e.get("type") == "blob"
                and e.get("path")
                and (not path_prefix or e["path"].startswith(path_prefix))
                and e["path"] != effective_app_yaml_path
            ]

            if len(folder_blobs) > MAX_FILES_PER_VERSION:
                raise BadRequestException(
                    f"Folder contains {len(folder_blobs)} files which exceeds the "
                    f"limit of {MAX_FILES_PER_VERSION}. Move the template into its own subfolder."
                )

            # 3) Download each file's text content; skip binaries and oversize blobs
            fetched_files: list[dict] = []
            for entry in folder_blobs:
                full_path = entry["path"]
                if entry.get("size") and entry["size"] > MAX_FILE_SIZE_BYTES:
                    logger.info(
                        "Skipping oversize file during GitHub import",
                        extra={"path": full_path, "size": entry["size"]},
                    )
                    continue

                content = self._try_fetch_text_file(
                    client, parsed_url.owner, parsed_url.repo, full_path, commit_sha
                )
                if content is None:
                    logger.info(
                        "Skipping non-text file during GitHub import",
                        extra={"path": full_path},
                    )
                    continue

                relative_path = full_path[len(path_prefix):] if path_prefix else full_path
                hint = hints_by_relative_path.get(relative_path)
                fetched_files.append({
                    "file_name": full_path.rsplit("/", 1)[-1],
                    "file_path": relative_path,
                    "file_type": hint["file_type"] if hint else FileType.OTHER.value,
                    "is_primary": hint["is_primary"] if hint else False,
                    "_artifact_order": hint["order"] if hint else None,
                    "content": content,
                    "size": len(content.encode("utf-8")),
                })

        # Determine version string
        manifest_version = ((parsed_manifest.get("app") or {}).get("version") or "").strip()
        version_string = manifest_version or self._derive_fallback_version(template.id)

        # Refuse duplicate (template_id, git_commit_sha) - existing constraint
        existing = self.version_repo.get_by_commit_sha(template.id, commit_sha)
        if existing:
            raise BadRequestException(
                f"This template already has a version for commit {commit_sha[:8]}"
            )

        approval_status = self._initial_approval(template, user_roles)

        version = TemplateVersion(
            id=str(uuid4()),
            template_id=template.id,
            version=version_string,
            git_commit_sha=commit_sha,
            is_active=is_active,
            approval_status=approval_status,
            approved_by_id=user_id if approval_status == TemplateVersionApprovalStatus.APPROVED else None,
            approved_at=datetime.now(timezone.utc) if approval_status == TemplateVersionApprovalStatus.APPROVED else None,
        )
        self.db.add(version)
        self.db.flush()

        # Persist app.yaml itself as APP_MANIFEST file at order=0
        self.db.add(TemplateVersionFile(
            id=str(uuid4()),
            template_version_id=version.id,
            file_name=app_yaml_filename,
            file_type=FileType.APP_MANIFEST,
            file_path=app_yaml_filename,
            content=app_yaml_content,
            file_size=len(app_yaml_content.encode("utf-8")),
            is_primary=False,
            order=0,
        ))

        # Order: artifact-listed files first (in their declared order), then everything else
        # alphabetically. Keeps the deployment engine's "run artifacts in order" semantics
        # for declared files; undeclared files just exist in the row set.
        artifact_files = sorted(
            [f for f in fetched_files if f["_artifact_order"] is not None],
            key=lambda f: f["_artifact_order"],
        )
        other_files = sorted(
            [f for f in fetched_files if f["_artifact_order"] is None],
            key=lambda f: f["file_path"],
        )

        for idx, entry in enumerate(artifact_files + other_files, start=1):
            try:
                file_type_enum = FileType(entry["file_type"])
            except ValueError:
                file_type_enum = FileType.OTHER

            self.db.add(TemplateVersionFile(
                id=str(uuid4()),
                template_version_id=version.id,
                file_name=entry["file_name"],
                file_type=file_type_enum,
                file_path=entry["file_path"],
                content=entry["content"],
                file_size=entry["size"],
                is_primary=entry["is_primary"],
                order=idx,
            ))

        if is_active:
            # Same semantics as TemplateVersionRepository.deactivate_other_versions
            # but inside the same transaction. Avoid commit/refresh so the caller
            # can wrap everything in one txn.
            self.db.query(TemplateVersion).filter(
                TemplateVersion.template_id == template.id,
                TemplateVersion.id != version.id,
                TemplateVersion.is_active.is_(True),
            ).update({TemplateVersion.is_active: False}, synchronize_session=False)

        return version

    @staticmethod
    def _initial_approval(
        template: Template, user_roles: list[str]
    ) -> TemplateVersionApprovalStatus:
        is_admin = UserRole.ADMIN.value in user_roles
        if is_admin and template.visibility == TemplateVisibility.PUBLIC:
            return TemplateVersionApprovalStatus.APPROVED
        return TemplateVersionApprovalStatus.PENDING

    @staticmethod
    def _derive_fallback_version(template_id: str) -> str:
        """Fallback if app.yaml has no `app.version` field."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        return f"0.0.0+{timestamp}"
