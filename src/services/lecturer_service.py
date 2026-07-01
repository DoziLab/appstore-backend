"""Lecturer administration — admin-only listing, detail view, and cascade delete.

Rationale: the codebase intentionally does not store user roles (Keycloak is
source-of-truth), so "who is a lecturer" is defined structurally as "a user
who owns templates or OpenStack projects." Students never satisfy this —
they cannot create either — which lets the /lecturers endpoints exclude
them without a role field.

Deployment ownership is embedded in ``deployments.deployment_parameters``
(JSON) rather than a FK column, so the counts here go through that JSON
via a Postgres JSONB path expression in production and a per-row Python
fallback in tests (SQLite has no JSONB).
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session

from src.core.exceptions import BadRequestException, NotFoundException
from src.models.deployment import Deployment
from src.models.openstack_project import OpenstackProject
from src.models.template import Template
from src.models.template_version import TemplateVersion
from src.models.user import User

logger = logging.getLogger(__name__)


def _is_postgres(db: Session) -> bool:
    """Detect the DB dialect. We use Postgres-only JSONB queries where it
    matters for performance, and fall back to a per-row Python scan on
    SQLite so the unit tests don't need a real Postgres."""
    return db.bind is not None and db.bind.dialect.name == "postgresql"


def _deployments_for_external_id(db: Session, external_id: str) -> list[Deployment]:
    """Every Deployment whose stored `teacher.id` == external_id.

    On Postgres we JSONB-index into ``deployment_parameters``. On SQLite we
    load and JSON-parse in Python — fine for tests, unacceptable for prod
    scale, hence the dialect split."""
    if _is_postgres(db):
        return (
            db.query(Deployment)
            .filter(
                text("deployment_parameters::jsonb -> 'teacher' ->> 'id' = :ext_id")
            )
            .params(ext_id=external_id)
            .all()
        )
    # SQLite fallback for tests: fetch all and filter in Python.
    out: list[Deployment] = []
    for d in db.query(Deployment).all():
        if not d.deployment_parameters:
            continue
        try:
            params = json.loads(d.deployment_parameters)
        except (json.JSONDecodeError, TypeError):
            continue
        if params.get("teacher", {}).get("id") == external_id:
            out.append(d)
    return out


class LecturerService:
    """Service for the admin-only lecturer management endpoints."""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------

    def list_lecturers(
        self,
        skip: int = 0,
        limit: int = 50,
        search: Optional[str] = None,
    ) -> tuple[list[dict], int]:
        """List users who own templates or OpenStack projects.

        Args:
            skip: Pagination offset.
            limit: Pagination page size.
            search: Optional case-insensitive substring match against
                display_name, email, or username.

        Returns:
            Tuple of (rows, total). Each row is a dict that maps directly
            onto ``LecturerListItem``.
        """
        # Aggregate counts in one pass: LEFT JOIN both ownership tables,
        # then filter to rows that have at least one on either side. We
        # deliberately compute the deployment_count in a second step because
        # its dialect-specific query would explode the group-by.
        template_count = func.count(func.distinct(Template.id)).label("template_count")
        osp_count = func.count(
            func.distinct(OpenstackProject.id)
        ).label("openstack_project_count")

        base = (
            self.db.query(
                User.id,
                User.external_id,
                User.display_name,
                User.email,
                User.username,
                User.last_login_at,
                template_count,
                osp_count,
            )
            .outerjoin(Template, Template.owner_id == User.id)
            .outerjoin(OpenstackProject, OpenstackProject.owner_user_id == User.id)
            .group_by(User.id)
            .having(or_(template_count > 0, osp_count > 0))
        )

        if search:
            like = f"%{search}%"
            base = base.filter(
                or_(
                    User.display_name.ilike(like),
                    User.email.ilike(like),
                    User.username.ilike(like),
                )
            )

        # Total BEFORE pagination — subquery counts the filtered lecturer set.
        total = base.count()
        rows = base.order_by(User.display_name.asc().nulls_last() if _is_postgres(self.db) else User.display_name.asc()) \
            .offset(skip) \
            .limit(limit) \
            .all()

        results: list[dict] = []
        for r in rows:
            deployment_count = len(_deployments_for_external_id(self.db, r.external_id))
            results.append({
                "id": r.id,
                "external_id": r.external_id,
                "display_name": r.display_name,
                "email": r.email,
                "username": r.username,
                "last_login_at": r.last_login_at,
                "template_count": r.template_count,
                "deployment_count": deployment_count,
                "openstack_project_count": r.openstack_project_count,
            })
        return results, total

    # ------------------------------------------------------------------
    # Detail
    # ------------------------------------------------------------------

    def get_lecturer(self, user_id: str) -> dict:
        """Detail view with the full owned/deployed resource lists.

        Raises NotFoundException if the user is not a lecturer (owns no
        templates and no OSPs) — same visibility rule as list_lecturers so
        the URL space is consistent.
        """
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            raise NotFoundException(f"User {user_id} not found")

        templates = (
            self.db.query(Template).filter(Template.owner_id == user_id).all()
        )
        osps = (
            self.db.query(OpenstackProject)
            .filter(OpenstackProject.owner_user_id == user_id)
            .all()
        )
        if not templates and not osps:
            raise NotFoundException(f"User {user_id} is not a lecturer")

        deployments = _deployments_for_external_id(self.db, user.external_id)

        # For each template, count active versions once per template so the
        # detail view doesn't lie about "empty" templates.
        version_counts = dict(
            self.db.query(
                TemplateVersion.template_id,
                func.count(TemplateVersion.id),
            )
            .filter(TemplateVersion.template_id.in_([t.id for t in templates] or [""]))
            .group_by(TemplateVersion.template_id)
            .all()
        )

        return {
            "id": user.id,
            "external_id": user.external_id,
            "display_name": user.display_name,
            "email": user.email,
            "username": user.username,
            "last_login_at": user.last_login_at,
            "template_count": len(templates),
            "deployment_count": len(deployments),
            "openstack_project_count": len(osps),
            "templates": [
                {
                    "id": t.id,
                    "name": t.name,
                    "visibility": t.visibility.value if hasattr(t.visibility, "value") else str(t.visibility),
                    "version_count": version_counts.get(t.id, 0),
                }
                for t in templates
            ],
            "deployments": [
                {
                    "id": d.id,
                    "name": d.name,
                    "status": d.status.value if hasattr(d.status, "value") else str(d.status),
                    "course_id": d.course_id,
                    "expires_at": d.expires_at,
                    "created_at": d.created_at,
                }
                for d in deployments
            ],
            "openstack_projects": [
                {
                    "id": op.id,
                    "openstack_project_name": op.openstack_project_name,
                    "region_name": op.region_name,
                }
                for op in osps
            ],
        }

    # ------------------------------------------------------------------
    # Delete (returns the counts; the actual work is enqueued by the API)
    # ------------------------------------------------------------------

    def preflight_delete(self, user_id: str, requesting_user_id: str) -> dict:
        """Validate that the delete is legal and return the summary that
        the API endpoint attaches to the 202 response.

        Raises:
            NotFoundException: user does not exist or is not a lecturer.
            BadRequestException: admin tries to delete themselves.
        """
        if user_id == requesting_user_id:
            raise BadRequestException("Admins cannot delete their own account")

        detail = self.get_lecturer(user_id)  # raises NotFound if missing / not-lecturer
        return {
            "user_id": user_id,
            "deployment_count": detail["deployment_count"],
            "template_count": detail["template_count"],
        }
