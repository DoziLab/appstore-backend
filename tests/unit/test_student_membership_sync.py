"""Tests for DeploymentService._sync_student_memberships.

The student self-service endpoint joins users → course_members →
group_members → course_groups to decide which deployments a logged-in
student can see. Without those membership rows the INNER JOIN returns
empty even when credentials with the right group_id exist.

This test exercises the helper that fills those tables in:

1. Creates a new User when the student has never logged in.
2. Re-uses an existing User on external_id match — no duplicate.
3. Idempotent across re-deploys: second call adds nothing.
4. Different groups produce separate GroupMember rows for the same student
   while sharing one CourseMember.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from types import SimpleNamespace

from src.core.database import Base
from src.models.course import Course
from src.models.course_group import CourseGroup
from src.models.course_member import CourseMember
from src.models.group_member import GroupMember
from src.models.user import User
from src.services.deployment_service import DeploymentService


@pytest.fixture
def db_session():
    """Fresh in-memory SQLite per test with all relevant tables present."""
    # Eager-import models so their tables register on Base.metadata before
    # create_all runs. The set mirrors the model graph touched by the
    # student-membership sync.
    import src.models.deployment  # noqa: F401
    import src.models.deployment_instance  # noqa: F401
    import src.models.deployment_instance_access  # noqa: F401
    import src.models.deployment_log  # noqa: F401
    import src.models.template  # noqa: F401
    import src.models.template_version  # noqa: F401
    import src.models.template_version_file  # noqa: F401
    import src.models.template_category  # noqa: F401
    import src.models.template_category_assignment  # noqa: F401
    import src.models.openstack_project  # noqa: F401

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


def _student(idx):
    """Build a StudentInfo-shaped object the sync method expects."""
    return SimpleNamespace(
        id=f"kc-student-{idx}",  # external_id (Keycloak sub)
        username=f"student{idx}",
        email=f"student{idx}@example.com",
        first_name=f"First{idx}",
        last_name=f"Last{idx}",
    )


def _stack_assignment(group_name, students):
    return SimpleNamespace(
        groups=[SimpleNamespace(group_name=group_name, students=students)]
    )


def _service(db):
    """DeploymentService instance without the heavy __init__ side-effects."""
    svc = DeploymentService.__new__(DeploymentService)
    svc.db = db
    return svc


def _make_course_and_group(db, group_name="Group A"):
    course = Course(name="C", keycloak_course_id="kc-1")
    db.add(course)
    db.flush()
    group = CourseGroup(course_id=course.id, name=group_name)
    db.add(group)
    db.flush()
    return course, group


def test_creates_user_course_member_and_group_member_for_new_student(db_session):
    course, group = _make_course_and_group(db_session)
    svc = _service(db_session)
    stack_assignments = [_stack_assignment("Group A", [_student(1)])]

    svc._sync_student_memberships(
        course_id=course.id,
        stack_assignments=stack_assignments,
        group_name_to_id={"Group A": group.id},
    )

    user = db_session.query(User).filter_by(external_id="kc-student-1").one()
    assert user.username == "student1"
    assert user.email == "student1@example.com"

    cm = db_session.query(CourseMember).filter_by(
        user_id=user.id, course_id=course.id
    ).one()
    assert cm.left_at is None

    gm = db_session.query(GroupMember).filter_by(
        group_id=group.id, course_member_id=cm.id
    ).one()
    assert gm is not None


def test_reuses_existing_user_by_external_id(db_session):
    """If the student already logged in once, the existing User row is
    re-used — no duplicate, display fields aren't overwritten by the
    wizard payload."""
    existing = User(
        external_id="kc-student-1",
        display_name="Original Display",
        email="original@example.com",
        username="orig",
    )
    db_session.add(existing)
    db_session.flush()

    course, group = _make_course_and_group(db_session)
    svc = _service(db_session)
    svc._sync_student_memberships(
        course_id=course.id,
        stack_assignments=[_stack_assignment("Group A", [_student(1)])],
        group_name_to_id={"Group A": group.id},
    )

    users = db_session.query(User).filter_by(external_id="kc-student-1").all()
    assert len(users) == 1
    # Display fields preserved — sync doesn't overwrite, it only creates.
    assert users[0].display_name == "Original Display"


def test_idempotent_on_redeploy(db_session):
    """A second sync call with the same students adds nothing."""
    course, group = _make_course_and_group(db_session)
    svc = _service(db_session)
    args = dict(
        course_id=course.id,
        stack_assignments=[_stack_assignment("Group A", [_student(1)])],
        group_name_to_id={"Group A": group.id},
    )

    svc._sync_student_memberships(**args)
    svc._sync_student_memberships(**args)

    assert db_session.query(User).count() == 1
    assert db_session.query(CourseMember).count() == 1
    assert db_session.query(GroupMember).count() == 1


def test_student_in_two_groups_gets_one_course_member_two_group_members(db_session):
    course, group_a = _make_course_and_group(db_session, "Group A")
    group_b = CourseGroup(course_id=course.id, name="Group B")
    db_session.add(group_b)
    db_session.flush()

    svc = _service(db_session)
    svc._sync_student_memberships(
        course_id=course.id,
        stack_assignments=[
            _stack_assignment("Group A", [_student(1)]),
            _stack_assignment("Group B", [_student(1)]),
        ],
        group_name_to_id={"Group A": group_a.id, "Group B": group_b.id},
    )

    # One user, one course member, two group memberships
    assert db_session.query(User).filter_by(external_id="kc-student-1").count() == 1
    course_members = db_session.query(CourseMember).filter_by(
        course_id=course.id
    ).all()
    assert len(course_members) == 1
    group_members = db_session.query(GroupMember).filter_by(
        course_member_id=course_members[0].id
    ).all()
    assert {gm.group_id for gm in group_members} == {group_a.id, group_b.id}
