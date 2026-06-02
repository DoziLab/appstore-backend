"""Template Version service for business logic."""
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4
import logging

from sqlalchemy.orm import Session

from src.models.template_version import TemplateVersion, TemplateVersionApprovalStatus
from src.models.template_version_file import FileType, TemplateVersionFile
from src.models.template import Template, TemplateVisibility
from src.models.user import UserRole
from src.repositories.template_version_repository import TemplateVersionRepository, QueueSort
from src.repositories.template_repository import TemplateRepository
from src.repositories.template_version_file_repository import TemplateVersionFileRepository
from src.schemas.template_version import (
    TemplateVersionCreate,
    TemplateVersionUpdate,
    TemplateVersionWithFilesCreate,
)
from src.core.exceptions import NotFoundException, BadRequestException, ForbiddenException
from src.utils.app_manifest_parser import AppManifestParser

logger = logging.getLogger(__name__)


class TemplateVersionService:
    """Service for template version business logic."""

    def __init__(self, db: Session):
        """Initialize TemplateVersionService with database session.

        Args:
            db: SQLAlchemy database session
        """
        self.db = db
        self.version_repo = TemplateVersionRepository(db)
        self.template_repo = TemplateRepository(db)
        self.file_repo = TemplateVersionFileRepository(db)

    def _can_access_template(
        self,
        template: Template,
        user_id: Optional[str] = None,
        is_admin: bool = False
    ) -> bool:
        """Template-level access (without per-version approval check).

        Non-owners can only see public templates that have at least one
        APPROVED version - this matches TemplateService._can_access_template.
        """
        if is_admin:
            return True
        if not user_id:
            return False
        if template.owner_id == user_id:
            return True
        if template.visibility != TemplateVisibility.PUBLIC:
            return False
        return self.template_repo.has_approved_version(template.id)

    def _can_access_version(
        self,
        version: TemplateVersion,
        template: Template,
        user_id: Optional[str] = None,
        is_admin: bool = False,
    ) -> bool:
        """Per-version access:
        - admins -> always
        - owners -> always
        - others -> only when template is public AND version is approved
        """
        if is_admin:
            return True
        if not user_id:
            return False
        if template.owner_id == user_id:
            return True
        return (
            template.visibility == TemplateVisibility.PUBLIC
            and version.approval_status == TemplateVersionApprovalStatus.APPROVED
        )

    def _check_template_access(
        self,
        template_id: str | UUID,
        user_id: Optional[str] = None,
        is_admin: bool = False
    ) -> Template:
        """Check if user can access parent template and return it."""
        template = self.template_repo.get_by_id(template_id)
        if not template:
            raise NotFoundException(f"Template with ID {template_id} not found")
        if not self._can_access_template(template, user_id, is_admin):
            raise ForbiddenException("You do not have permission to access this template")
        return template

    def _check_version_access(
        self,
        version: TemplateVersion,
        user_id: Optional[str] = None,
        is_admin: bool = False,
    ) -> Template:
        template = self.template_repo.get_by_id(version.template_id)
        if not template:
            raise NotFoundException(f"Template with ID {version.template_id} not found")
        if not self._can_access_version(version, template, user_id, is_admin):
            raise ForbiddenException("You do not have permission to access this template version")
        return template

    @staticmethod
    def _initial_approval(
        template: Template, user_roles: list[str]
    ) -> TemplateVersionApprovalStatus:
        """Auto-approve admin-created versions on public templates; otherwise PENDING."""
        is_admin = UserRole.ADMIN.value in (user_roles or [])
        if is_admin and template.visibility == TemplateVisibility.PUBLIC:
            return TemplateVersionApprovalStatus.APPROVED
        return TemplateVersionApprovalStatus.PENDING

    def create_version(
        self,
        version_data: TemplateVersionCreate,
        user_id: str,
        is_admin: bool = False,
        user_roles: Optional[list[str]] = None,
    ) -> TemplateVersion:
        """Create a new template version (manifest-only, no files yet).

        Approval status is decided by `_initial_approval`. If `user_roles` is
        not provided, falls back to is_admin to keep older callers compatible.
        """
        template = self.template_repo.get_by_id(version_data.template_id)
        if not template:
            raise NotFoundException(f"Template with ID {version_data.template_id} not found")

        if not is_admin and template.owner_id != user_id:
            raise ForbiddenException("You do not have permission to create versions for this template")

        existing_version = self.version_repo.get_by_commit_sha(
            version_data.template_id,
            version_data.git_commit_sha,
        )
        if existing_version:
            raise BadRequestException(
                f"Version with commit SHA {version_data.git_commit_sha} already exists for this template"
            )

        roles = user_roles if user_roles is not None else ([UserRole.ADMIN.value] if is_admin else [])
        approval_status = self._initial_approval(template, roles)

        version = self.version_repo.create(
            template_id=version_data.template_id,
            version=version_data.version,
            git_commit_sha=version_data.git_commit_sha,
            is_active=version_data.is_active,
            approval_status=approval_status,
            approved_by_id=user_id if approval_status == TemplateVersionApprovalStatus.APPROVED else None,
            approved_at=datetime.now(timezone.utc) if approval_status == TemplateVersionApprovalStatus.APPROVED else None,
        )

        if version_data.is_active:
            self.version_repo.deactivate_other_versions(
                version_data.template_id,
                version.id,
            )

        return version

    def create_version_with_files(
        self,
        payload: TemplateVersionWithFilesCreate,
        user_id: str,
        user_roles: list[str],
    ) -> TemplateVersion:
        """Atomically create a new version + all its files.

        Used when the user edits a template in the UI: frontend submits the
        complete (potentially edited) file set; optionally `base_version_id` is
        provided so files of an existing version are copied first and then
        overlaid by inline files (matched on `file_path`).
        """
        is_admin = UserRole.ADMIN.value in user_roles

        template = self.template_repo.get_by_id(payload.template_id)
        if not template:
            raise NotFoundException(f"Template with ID {payload.template_id} not found")

        if not is_admin and template.owner_id != user_id:
            raise ForbiddenException("You do not have permission to create versions for this template")

        if self.version_repo.get_by_commit_sha(payload.template_id, payload.git_commit_sha):
            raise BadRequestException(
                f"Version with commit SHA {payload.git_commit_sha} already exists for this template"
            )

        # Build merged file set: base_version's files first, payload.files overlay by file_path
        merged: dict[str, dict] = {}
        if payload.base_version_id:
            base_version = self.version_repo.get_by_id(payload.base_version_id)
            if not base_version or base_version.template_id != payload.template_id:
                raise BadRequestException(
                    f"base_version_id {payload.base_version_id} is not a version of template {payload.template_id}"
                )
            base_files = self.file_repo.get_by_version_id(payload.base_version_id, include_content=True)
            for f in base_files:
                merged[f.file_path] = {
                    "file_name": f.file_name,
                    "file_type": f.file_type.value if hasattr(f.file_type, "value") else f.file_type,
                    "file_path": f.file_path,
                    "content": f.content or "",
                    "description": f.description,
                    "is_primary": f.is_primary,
                    "order": f.order,
                }

        for inline in payload.files:
            merged[inline.file_path] = {
                "file_name": inline.file_name,
                "file_type": inline.file_type,
                "file_path": inline.file_path,
                "content": inline.content,
                "description": inline.description,
                "is_primary": inline.is_primary,
                "order": inline.order,
            }

        if not merged:
            raise BadRequestException(
                "Cannot create a version with zero files. Provide `files` or a `base_version_id`."
            )

        has_app_manifest = any(
            f.get("file_type") == FileType.APP_MANIFEST.value
            or f.get("file_name", "").lower() in ("app.yaml", "app.yml")
            for f in merged.values()
        )
        if not has_app_manifest:
            raise BadRequestException(
                "Cannot create a version without an APP_MANIFEST (app.yaml/app.yml)."
            )

        # Sanity check: at most one primary
        primary_count = sum(1 for f in merged.values() if f["is_primary"])
        if primary_count > 1:
            raise BadRequestException("Only one file can be marked is_primary=true")

        approval_status = self._initial_approval(template, user_roles)

        try:
            version = TemplateVersion(
                id=str(uuid4()),
                template_id=payload.template_id,
                version=payload.version,
                git_commit_sha=payload.git_commit_sha,
                is_active=payload.is_active,
                approval_status=approval_status,
                approved_by_id=user_id if approval_status == TemplateVersionApprovalStatus.APPROVED else None,
                approved_at=datetime.now(timezone.utc) if approval_status == TemplateVersionApprovalStatus.APPROVED else None,
            )
            self.db.add(version)
            self.db.flush()

            for entry in sorted(merged.values(), key=lambda e: e["order"]):
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
                    file_size=len(entry["content"].encode("utf-8")) if entry["content"] else None,
                    description=entry.get("description"),
                    is_primary=entry["is_primary"],
                    order=entry["order"],
                ))

            if payload.is_active:
                self.db.query(TemplateVersion).filter(
                    TemplateVersion.template_id == payload.template_id,
                    TemplateVersion.id != version.id,
                    TemplateVersion.is_active.is_(True),
                ).update({TemplateVersion.is_active: False}, synchronize_session=False)

            self.db.commit()
            self.db.refresh(version)
            return version
        except Exception:
            self.db.rollback()
            raise

    def approve_version(
        self,
        version_id: str | UUID,
        admin_user_id: str,
    ) -> TemplateVersion:
        """Admin-only: mark a pending version as approved."""
        version = self.version_repo.get_by_id(version_id)
        if not version:
            raise NotFoundException(f"Template version with ID {version_id} not found")

        version.approval_status = TemplateVersionApprovalStatus.APPROVED
        version.approved_by_id = admin_user_id
        version.approved_at = datetime.now(timezone.utc)
        version.rejection_reason = None
        self.db.commit()
        self.db.refresh(version)

        logger.info(
            "Template version approved",
            extra={
                "version_id": str(version.id),
                "template_id": version.template_id,
                "approved_by": admin_user_id,
            },
        )
        return version

    def reject_version(
        self,
        version_id: str | UUID,
        admin_user_id: str,
        reason: Optional[str] = None,
    ) -> TemplateVersion:
        """Admin-only: mark a pending version as rejected.

        `reason` is optional free-text persisted on the version.
        """
        version = self.version_repo.get_by_id(version_id)
        if not version:
            raise NotFoundException(f"Template version with ID {version_id} not found")

        version.approval_status = TemplateVersionApprovalStatus.REJECTED
        version.approved_by_id = admin_user_id
        version.approved_at = datetime.now(timezone.utc)
        version.rejection_reason = reason
        self.db.commit()
        self.db.refresh(version)

        logger.info(
            "Template version rejected",
            extra={
                "version_id": str(version.id),
                "template_id": version.template_id,
                "rejected_by": admin_user_id,
                "has_reason": reason is not None,
            },
        )
        return version

    def get_version(
        self,
        version_id: str | UUID,
        with_file_count: bool = False,
        user_id: Optional[str] = None,
        is_admin: bool = False
    ) -> TemplateVersion | dict:
        """Get a template version by ID. Per-version access rules apply."""
        if with_file_count:
            result = self.version_repo.get_with_file_count(version_id)
            if not result:
                raise NotFoundException(f"Template version with ID {version_id} not found")
            version = result["version"]
            self._check_version_access(version, user_id, is_admin)
            return result

        version = self.version_repo.get_by_id(version_id)
        if not version:
            raise NotFoundException(f"Template version with ID {version_id} not found")
        self._check_version_access(version, user_id, is_admin)
        return version

    def list_template_versions(
        self,
        template_id: str | UUID,
        active_only: bool = False,
        user_id: Optional[str] = None,
        is_admin: bool = False
    ) -> list[TemplateVersion]:
        """List versions of a template. Non-owners only see APPROVED versions."""
        template = self._check_template_access(template_id, user_id, is_admin)
        versions = self.version_repo.get_by_template_id(template_id, active_only)

        is_owner = user_id and template.owner_id == user_id
        if is_admin or is_owner:
            return versions

        return [
            v for v in versions
            if v.approval_status == TemplateVersionApprovalStatus.APPROVED
        ]

    def get_active_version(
        self,
        template_id: str | UUID,
        user_id: Optional[str] = None,
        is_admin: bool = False
    ) -> Optional[TemplateVersion]:
        """Get the active version. Non-owners only see it if APPROVED."""
        template = self._check_template_access(template_id, user_id, is_admin)
        version = self.version_repo.get_active_version(template_id)
        if not version:
            return None

        is_owner = user_id and template.owner_id == user_id
        if is_admin or is_owner:
            return version
        if version.approval_status == TemplateVersionApprovalStatus.APPROVED:
            return version
        return None

    def update_version(
        self,
        version_id: str | UUID,
        version_data: TemplateVersionUpdate,
        user_id: str,
        is_admin: bool = False
    ) -> TemplateVersion:
        """Update a template version. Owner-or-admin."""
        version = self.version_repo.get_by_id(version_id)
        if not version:
            raise NotFoundException(f"Template version with ID {version_id} not found")

        template = self.template_repo.get_by_id(version.template_id)
        if not template:
            raise NotFoundException(f"Template with ID {version.template_id} not found")

        if not is_admin and template.owner_id != user_id:
            raise ForbiddenException("You do not have permission to update this template version")

        update_data = version_data.model_dump(exclude_unset=True)

        if update_data.get("is_active") is True:
            self.version_repo.deactivate_other_versions(
                version.template_id,
                version_id,
            )

        uuid_id = version_id if isinstance(version_id, UUID) else UUID(str(version_id))
        updated_version = self.version_repo.update(uuid_id, **update_data)

        if not updated_version:
            raise NotFoundException(f"Template version with ID {version_id} not found after update")

        return updated_version

    def delete_version(
        self,
        version_id: str | UUID,
        user_id: str,
        is_admin: bool = False
    ) -> None:
        """Delete a version (owner-or-admin)."""
        version = self.version_repo.get_by_id(version_id)
        if not version:
            raise NotFoundException(f"Template version with ID {version_id} not found")

        template = self.template_repo.get_by_id(version.template_id)
        if not template:
            raise NotFoundException(f"Template with ID {version.template_id} not found")

        if not is_admin and template.owner_id != user_id:
            raise ForbiddenException("You do not have permission to delete this template version")

        if version.is_active:
            active_versions = self.version_repo.get_by_template_id(version.template_id, active_only=True)
            if len(active_versions) == 1:
                raise BadRequestException(
                    "Cannot delete the only active version. Activate another version first or deactivate this one."
                )

        uuid_id = version_id if isinstance(version_id, UUID) else UUID(str(version_id))
        self.version_repo.delete(uuid_id)

    def activate_version(
        self,
        version_id: str | UUID,
        user_id: str,
        is_admin: bool = False
    ) -> TemplateVersion:
        """Activate a version (owner-or-admin)."""
        version = self.version_repo.get_by_id(version_id)
        if not version:
            raise NotFoundException(f"Template version with ID {version_id} not found")

        template = self.template_repo.get_by_id(version.template_id)
        if not template:
            raise NotFoundException(f"Template with ID {version.template_id} not found")

        if not is_admin and template.owner_id != user_id:
            raise ForbiddenException("You do not have permission to activate this template version")

        self.version_repo.deactivate_other_versions(version.template_id, version_id)

        uuid_id = version_id if isinstance(version_id, UUID) else UUID(str(version_id))
        updated_version = self.version_repo.update(uuid_id, is_active=True)

        if not updated_version:
            raise NotFoundException(f"Template version with ID {version_id} not found after activation")

        return updated_version

    def list_versions_by_approval_status(
        self,
        approval_status: TemplateVersionApprovalStatus,
        skip: int = 0,
        limit: int = 100,
        template_id: Optional[str | UUID] = None,
        visibility: Optional[TemplateVisibility] = None,
        sort: QueueSort = "created_at_desc",
    ) -> tuple[list[tuple[TemplateVersion, Template]], int]:
        """Admin approval queue: list versions filtered by approval status.

        Bypasses the per-template/per-version access checks - callers must enforce
        admin-only authorization before invoking this.

        Returns `(rows, total)` where each row is `(version, template)`.
        """
        return self.version_repo.list_by_approval_status(
            approval_status=approval_status,
            skip=skip,
            limit=limit,
            template_id=template_id,
            visibility=visibility,
            sort=sort,
        )

    def get_version_parameters(self, version_id: str | UUID) -> list[dict]:
        """Parse app.yaml of a version and return its parameter list.

        No access check - admin-only callers (e.g. the approval queue).
        Returns `[]` if no manifest is present or parsing fails.
        """
        try:
            files = self.file_repo.get_by_version_id(version_id, include_content=True)
            manifest = next(
                (
                    f for f in files
                    if f.file_type == FileType.APP_MANIFEST or f.file_name.lower() == "app.yaml"
                ),
                None,
            )
            if manifest and manifest.content:
                parsed = AppManifestParser.parse(manifest.content)
                return parsed.get("parameters", [])
        except Exception as e:
            logger.warning(f"Failed to parse manifest for version {version_id}: {e}")
        return []

    def get_version_with_parameters(
        self,
        version_id: str | UUID,
        with_file_count: bool = False,
        user_id: Optional[str] = None,
        is_admin: bool = False
    ) -> dict:
        """Get a version + extracted parameters from app.yaml."""
        if with_file_count:
            result = self.get_version(version_id, with_file_count=True, user_id=user_id, is_admin=is_admin)
            if not isinstance(result, dict):
                raise ValueError("Expected dict result when with_file_count=True")
            version = result["version"]
            file_count = result["file_count"]
        else:
            version = self.get_version(version_id, with_file_count=False, user_id=user_id, is_admin=is_admin)
            if isinstance(version, dict):
                raise ValueError("Expected TemplateVersion when with_file_count=False")
            file_count = None

        parameters = []
        try:
            files = self.file_repo.get_by_version_id(version_id, include_content=True)
            app_manifest_file = next(
                (f for f in files if f.file_type == FileType.APP_MANIFEST or f.file_name.lower() == "app.yaml"),
                None,
            )
            if app_manifest_file and app_manifest_file.content:
                parsed_manifest = AppManifestParser.parse(app_manifest_file.content)
                parameters = parsed_manifest.get("parameters", [])
                logger.info(f"Loaded {len(parameters)} parameters for version {version_id}")
        except Exception as e:
            logger.warning(f"Failed to parse app manifest for version {version_id}: {e}")

        result_dict: dict = {
            "version": version,
            "parameters": parameters,
        }
        if file_count is not None:
            result_dict["file_count"] = file_count
        return result_dict
