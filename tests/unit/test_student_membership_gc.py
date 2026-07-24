"""Tests for _gc_orphan_student_memberships in src.tasks.deploy_tasks.

The GC runs at the tail end of delete_deployment, AFTER the deployment
row, its instances, and its access rows are gone. It walks every user
id that was tied to the deleted deployment and drops:

  - GroupMember rows whose course_group no longer has any live
    DeploymentInstanceAccess
  - CourseMember rows whose last GroupMember just vanished
  - User rows whose last CourseMember just vanished, provided the user
    owns no templates / openstack projects (= guaranteed pure student)

These tests exercise the helper against an in-memory SQLite DB with the
real schema, so the query joins are vetted as part of the test.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.core.database import Base
from src.models.course import Course
from src.models.course_group import CourseGroup
from src.models.course_member import CourseMember
from src.models.deployment import Deployment, DeploymentStatus
from src.models.deployment_instance import DeploymentInstance
from src.models.deployment_instance_access import (
    AccessType,
    DeploymentInstanceAccess,
)
from src.models.group_member import GroupMember
from src.models.openstack_project import OpenstackProject
from src.models.template import Template, TemplateVisibility
from src.models.template_version import TemplateVersion
from src.models.user import User
from src.tasks.deploy_tasks import _gc_orphan_student_memberships


@pytest.fixture
def db_session():
    """Fresh in-memory SQLite per test with all relevant tables present."""
    # Make sure every model the GC touches is registered on Base.metadata
    # before create_all runs.
    import src.models.deployment_log  # noqa: F401
    import src.models.template_version_file  # noqa: F401
    import src.models.template_category  # noqa: F401
    import src.models.template_category_assignment  # noqa: F401

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def _scaffold(db, group_name="Group A"):
    """Build the smallest set of rows the GC needs: user → course_member →
    group_member → course_group. Returns the row references."""
    user = User(external_id="kc-1", username="s1")
    db.add(user)
    db.flush()
    course = Course(name="C", keycloak_course_id="kc-c1")
    db.add(course)
    db.flush()
    group = CourseGroup(course_id=course.id, name=group_name)
    db.add(group)
    db.flush()
    cm = CourseMember(user_id=user.id, course_id=course.id)
    db.add(cm)
    db.flush()
    gm = GroupMember(group_id=group.id, course_member_id=cm.id)
    db.add(gm)
    db.flush()
    return user, course, group, cm, gm


def test_gc_drops_user_when_no_access_rows_remain(db_session):
    """The end-state of delete_deployment: instances + access rows have
    already been deleted. The user is now orphaned and must go."""
    user, *_ = _scaffold(db_session)

    _gc_orphan_student_memberships(db_session, {user.id})

    # User + course_member + group_member all gone
    assert db_session.query(User).filter_by(id=user.id).first() is None
    assert db_session.query(CourseMember).count() == 0
    assert db_session.query(GroupMember).count() == 0


def test_gc_keeps_user_when_still_referenced_by_another_deployment(db_session):
    """If the student still has a live access row on a different
    deployment, the GC leaves all their membership rows alone."""
    user, course, group, cm, gm = _scaffold(db_session)

    # Build a second, surviving deployment chain that the student is on:
    # openstack_project → template → template_version → deployment →
    # deployment_instance → deployment_instance_access linked to `group`.
    op = OpenstackProject(
        owner_user_id=user.id,  # owner doesn't have to be the student here
        openstack_project_id="ks-1",
        openstack_project_name="osp",
        auth_url="x",
        username="u",
        password="p",
        region_name="r",
    )
    tpl = Template(
        name="t", owner_id=user.id, repo_url="r", visibility=TemplateVisibility.PRIVATE
    )
    db_session.add_all([op, tpl])
    db_session.flush()
    tv = TemplateVersion(template_id=tpl.id, version="1.0.0", git_commit_sha="abc")
    db_session.add(tv)
    db_session.flush()
    surviving = Deployment(
        name="alive",
        template_version_id=tv.id,
        course_id=course.id,
        openstack_project_id=op.id,
        status=DeploymentStatus.RUNNING,
    )
    db_session.add(surviving)
    db_session.flush()
    inst = DeploymentInstance(deployment_id=surviving.id, vm_name="i1")
    db_session.add(inst)
    db_session.flush()
    access = DeploymentInstanceAccess(
        deployment_instance_id=inst.id,
        access_type=AccessType.SSH,
        group_id=group.id,
    )
    db_session.add(access)
    db_session.commit()

    # ...but because owns_templates is true for this user, the GC bails out
    # via the owner-guard. Rerun with a "pure student" id to verify the
    # access-survives logic itself: use a second user with no owner rows.
    pure_user = User(external_id="kc-2", username="s2")
    db_session.add(pure_user)
    db_session.flush()
    pure_cm = CourseMember(user_id=pure_user.id, course_id=course.id)
    db_session.add(pure_cm)
    db_session.flush()
    db_session.add(GroupMember(group_id=group.id, course_member_id=pure_cm.id))
    db_session.commit()

    _gc_orphan_student_memberships(db_session, {pure_user.id})

    # pure_user's membership remains because group.id still has a live
    # DeploymentInstanceAccess (via the surviving deployment).
    assert db_session.query(User).filter_by(id=pure_user.id).first() is not None
    assert (
        db_session.query(CourseMember).filter_by(user_id=pure_user.id).count() == 1
    )


def test_gc_skips_users_who_own_templates(db_session):
    """Safety net: a user who owns a template is NOT a pure student. GC
    must leave them alone even if they have a stale CourseMember row."""
    user, course, group, cm, gm = _scaffold(db_session)
    db_session.add(
        Template(
            name="t",
            owner_id=user.id,
            repo_url="r",
            visibility=TemplateVisibility.PRIVATE,
        )
    )
    db_session.commit()

    _gc_orphan_student_memberships(db_session, {user.id})

    assert db_session.query(User).filter_by(id=user.id).first() is not None
    assert db_session.query(CourseMember).count() == 1
    assert db_session.query(GroupMember).count() == 1


def test_gc_skips_users_who_own_openstack_projects(db_session):
    """Same safety net for openstack project owners."""
    user, course, *_ = _scaffold(db_session)
    db_session.add(
        OpenstackProject(
            owner_user_id=user.id,
            openstack_project_id="ks-1",
            openstack_project_name="osp",
            auth_url="x",
            username="u",
            password="p",
            region_name="r",
        )
    )
    db_session.commit()

    _gc_orphan_student_memberships(db_session, {user.id})

    assert db_session.query(User).filter_by(id=user.id).first() is not None


def test_gc_with_empty_user_set_is_a_noop(db_session):
    """Defensive: the caller passes an empty set when its snapshot query
    failed. The GC must do nothing."""
    user, *_ = _scaffold(db_session)

    _gc_orphan_student_memberships(db_session, set())

    assert db_session.query(User).filter_by(id=user.id).first() is not None
