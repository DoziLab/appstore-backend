"""Test the backfill migration logic that retro-populates DeploymentInstanceAccess.group_id.

The migration walks every deployment's stored ``deployment_parameters`` JSON,
finds the matching ``course_groups`` row by ``(course_id, group_name)``, and
stamps the FK onto access rows whose sanitized username matches the group.

These tests run the SQL UPDATE logic against an in-memory SQLite DB so we
can exercise the same statements the migration runs without needing real
PostgreSQL.
"""
import importlib.util
import json
from pathlib import Path

import pytest
from sqlalchemy import (
    Column,
    ForeignKey,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import declarative_base, Session


# Load the migration module by path so we can call its helpers / upgrade()
# without going through Alembic's full runtime.
MIGRATION_PATH = (
    Path(__file__).parent.parent.parent
    / "alembic" / "versions"
    / "b6d52b9f8ea3_backfill_access_group_id.py"
)
_spec = importlib.util.spec_from_file_location("backfill_migration", MIGRATION_PATH)
backfill = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(backfill)  # type: ignore[union-attr]


def test_sanitize_username_matches_credential_generator():
    """The migration's _sanitize_username must produce the same usernames
    the credential generator did — else backfill matches will silently fail."""
    from src.services.credential_generator_service import _sanitize_username as svc_sanitize

    for name in ["Gruppe 1", "Group_2", "AG.Berlin", "äöü", "  spaced  "]:
        assert backfill._sanitize_username(name) == svc_sanitize(name)


# ---------------------------------------------------------------------------
# Minimal schema mirroring just enough of the real one for the SQL the
# migration runs. We do not import Base from src to keep the test isolated
# from any FK constraints that would force us to set up half the schema.
# ---------------------------------------------------------------------------
Base = declarative_base()


class _Course(Base):
    __tablename__ = "courses"
    id = Column(String(36), primary_key=True)


class _CourseGroup(Base):
    __tablename__ = "course_groups"
    id = Column(String(36), primary_key=True)
    course_id = Column(String(36), ForeignKey("courses.id"))
    name = Column(String(255))


class _Deployment(Base):
    __tablename__ = "deployments"
    id = Column(String(36), primary_key=True)
    course_id = Column(String(36), ForeignKey("courses.id"))
    deployment_parameters = Column(Text, nullable=True)


class _DeploymentInstance(Base):
    __tablename__ = "deployment_instances"
    id = Column(String(36), primary_key=True)
    deployment_id = Column(String(36), ForeignKey("deployments.id"))


class _DeploymentInstanceAccess(Base):
    __tablename__ = "deployment_instance_access"
    id = Column(String(36), primary_key=True)
    deployment_instance_id = Column(String(36), ForeignKey("deployment_instances.id"))
    username = Column(String(255))
    group_id = Column(String(36), nullable=True)


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _seed_deployment_with_group(
    session: Session,
    *,
    deployment_id: str,
    course_id: str,
    group_name: str,
    course_group_id: str,
    sanitized_username: str,
    include_admin: bool = True,
):
    """Seed the minimal rows the backfill needs to find one group + one admin."""
    session.add(_Course(id=course_id))
    session.add(_CourseGroup(id=course_group_id, course_id=course_id, name=group_name))
    payload = {
        "stack_assignments": [
            {"groups": [{"group_name": group_name, "group_index": 1}]}
        ]
    }
    session.add(_Deployment(
        id=deployment_id,
        course_id=course_id,
        deployment_parameters=json.dumps(payload),
    ))
    session.add(_DeploymentInstance(id=f"inst-{deployment_id}", deployment_id=deployment_id))
    session.add(_DeploymentInstanceAccess(
        id=f"access-group-{deployment_id}",
        deployment_instance_id=f"inst-{deployment_id}",
        username=sanitized_username,
        group_id=None,
    ))
    if include_admin:
        session.add(_DeploymentInstanceAccess(
            id=f"access-admin-{deployment_id}",
            deployment_instance_id=f"inst-{deployment_id}",
            username="prof-berg",   # doesn't match any group's sanitized name
            group_id=None,
        ))
    session.commit()


def _run_backfill(session):
    """Run the migration's upgrade() against the test session's connection.

    Alembic's ``op.get_bind()`` is monkey-patched to return our session's bind.
    """
    import unittest.mock as _mock
    with _mock.patch.object(backfill.op, "get_bind", return_value=session.connection()):
        backfill.upgrade()
    session.commit()


def test_backfill_stamps_group_access_row(session):
    """An access row whose username matches the sanitized group name gets
    its group_id set; admin rows (no matching group) stay NULL."""
    _seed_deployment_with_group(
        session,
        deployment_id="d-1",
        course_id="c-1",
        group_name="Gruppe 1",
        course_group_id="cg-1",
        sanitized_username="gruppe_1",
    )

    _run_backfill(session)

    group_access = session.query(_DeploymentInstanceAccess).filter_by(id="access-group-d-1").one()
    admin_access = session.query(_DeploymentInstanceAccess).filter_by(id="access-admin-d-1").one()

    assert group_access.group_id == "cg-1"
    # Admin row stays NULL — no matching group → not stamped → invisible to students.
    assert admin_access.group_id is None


def test_backfill_is_idempotent(session):
    """Running the backfill twice does not change anything on the second run."""
    _seed_deployment_with_group(
        session,
        deployment_id="d-1",
        course_id="c-1",
        group_name="Gruppe 1",
        course_group_id="cg-1",
        sanitized_username="gruppe_1",
    )

    _run_backfill(session)
    after_first = session.query(_DeploymentInstanceAccess).filter_by(id="access-group-d-1").one().group_id
    _run_backfill(session)
    after_second = session.query(_DeploymentInstanceAccess).filter_by(id="access-group-d-1").one().group_id

    assert after_first == after_second == "cg-1"


def test_backfill_skips_when_no_course_group_exists(session):
    """If the lecturer never created a CourseGroup, the access row stays NULL.

    Graceful degradation: lecturer-side credentials still work, students
    just don't see those credentials. No exception, no half-state.
    """
    # No CourseGroup row created — only the deployment + access.
    session.add(_Course(id="c-1"))
    payload = {"stack_assignments": [{"groups": [{"group_name": "Orphan", "group_index": 1}]}]}
    session.add(_Deployment(id="d-1", course_id="c-1", deployment_parameters=json.dumps(payload)))
    session.add(_DeploymentInstance(id="inst-1", deployment_id="d-1"))
    session.add(_DeploymentInstanceAccess(
        id="access-1",
        deployment_instance_id="inst-1",
        username="orphan",
        group_id=None,
    ))
    session.commit()

    _run_backfill(session)

    assert session.query(_DeploymentInstanceAccess).filter_by(id="access-1").one().group_id is None


def test_backfill_skips_malformed_json(session):
    """Deployments with invalid JSON don't crash the migration."""
    session.add(_Course(id="c-1"))
    session.add(_Deployment(id="d-1", course_id="c-1", deployment_parameters="not-json"))
    session.add(_DeploymentInstance(id="inst-1", deployment_id="d-1"))
    session.add(_DeploymentInstanceAccess(
        id="access-1",
        deployment_instance_id="inst-1",
        username="x",
        group_id=None,
    ))
    session.commit()

    # Must not raise.
    _run_backfill(session)
    assert session.query(_DeploymentInstanceAccess).filter_by(id="access-1").one().group_id is None


def test_backfill_uses_explicit_course_group_id_when_present(session):
    """If the payload already carries ``course_group_id`` (newer wizards),
    use it directly without re-looking up by name."""
    session.add(_Course(id="c-1"))
    # NOTE: we deliberately omit a CourseGroup row to prove the lookup path
    # is skipped when the payload supplies the ID directly.
    payload = {
        "stack_assignments": [
            {"groups": [{
                "group_name": "Gruppe 1",
                "group_index": 1,
                "course_group_id": "cg-explicit",
            }]}
        ]
    }
    session.add(_Deployment(id="d-1", course_id="c-1", deployment_parameters=json.dumps(payload)))
    session.add(_DeploymentInstance(id="inst-1", deployment_id="d-1"))
    session.add(_DeploymentInstanceAccess(
        id="access-1",
        deployment_instance_id="inst-1",
        username="gruppe_1",
        group_id=None,
    ))
    session.commit()

    _run_backfill(session)

    assert session.query(_DeploymentInstanceAccess).filter_by(id="access-1").one().group_id == "cg-explicit"
