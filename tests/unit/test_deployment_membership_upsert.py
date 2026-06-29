"""Tests for the membership-graph upsert that runs synchronously inside
``DeploymentService.create_deployment``.

The wizard payload names students by their Keycloak user-id but the
``/api/v1/student/*`` read path inner-joins through CourseMember →
GroupMember → CourseGroup. Without this upsert students see 0 deployments
(appstore-backend#169). These tests exercise the helper directly against an
in-memory SQLite DB with the real SQLAlchemy models so the integrity
constraints actually fire.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.core.database import Base
from src.models.course import Course
from src.models.course_group import CourseGroup
from src.models.course_member import CourseMember
from src.models.group_member import GroupMember
from src.models.user import User
from src.schemas.deployment import GroupInfo, StackAssignment, StudentInfo
from src.services.deployment_service import DeploymentService


SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture()
def db_session():
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Touch every model so Base.metadata sees them all.
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

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def _student(external_id: str, idx: int) -> StudentInfo:
    return StudentInfo(
        id=external_id,
        username=f"u{idx}",
        email=f"u{idx}@example.com",
        first_name=f"First{idx}",
        last_name=f"Last{idx}",
    )


def _seed_user(db, external_id: str, idx: int) -> User:
    u = User(
        external_id=external_id,
        username=f"u{idx}",
        email=f"u{idx}@example.com",
        display_name=f"First{idx} Last{idx}",
    )
    db.add(u)
    db.flush()
    return u


def _seed_course(db) -> Course:
    c = Course(name="C1", keycloak_course_id="kc-1")
    db.add(c)
    db.flush()
    return c


def test_upsert_creates_full_membership_graph(db_session):
    """First call materializes CourseGroup + CourseMember + GroupMember rows
    for every student and stamps the resolved id back onto the payload."""
    u1 = _seed_user(db_session, "kc-stud-1", 1)
    u2 = _seed_user(db_session, "kc-stud-2", 2)
    course = _seed_course(db_session)

    payload = [
        StackAssignment(
            stack_index=1,
            groups=[
                GroupInfo(
                    group_name="Group A",
                    group_index=1,
                    students=[_student("kc-stud-1", 1), _student("kc-stud-2", 2)],
                    # Frontend left this null — the helper should fill it in.
                    course_group_id=None,
                ),
            ],
        ),
    ]

    out = DeploymentService(db_session)._upsert_course_membership_graph(
        course=course,
        stack_assignments=payload,
    )

    # CourseGroup created and id stamped back on the payload.
    cg = db_session.query(CourseGroup).filter_by(course_id=course.id, name="Group A").one()
    assert out[0]["groups"][0]["course_group_id"] == cg.id

    # Both students have CourseMember rows linked to the course.
    members = {m.user_id for m in db_session.query(CourseMember).filter_by(course_id=course.id)}
    assert members == {u1.id, u2.id}

    # Both students are linked to the group via GroupMember.
    gms = db_session.query(GroupMember).filter_by(group_id=cg.id).all()
    assert {gm.course_member_id for gm in gms} == {
        db_session.query(CourseMember).filter_by(user_id=u1.id).one().id,
        db_session.query(CourseMember).filter_by(user_id=u2.id).one().id,
    }


def test_upsert_is_idempotent_across_repeated_deploys(db_session):
    """Running the same payload twice must not duplicate any row."""
    _seed_user(db_session, "kc-stud-1", 1)
    course = _seed_course(db_session)
    payload = [
        StackAssignment(
            stack_index=1,
            groups=[
                GroupInfo(
                    group_name="Group A",
                    group_index=1,
                    students=[_student("kc-stud-1", 1)],
                    course_group_id=None,
                ),
            ],
        ),
    ]
    svc = DeploymentService(db_session)
    out1 = svc._upsert_course_membership_graph(course=course, stack_assignments=payload)
    out2 = svc._upsert_course_membership_graph(course=course, stack_assignments=payload)

    assert out1[0]["groups"][0]["course_group_id"] == out2[0]["groups"][0]["course_group_id"]
    assert db_session.query(CourseGroup).count() == 1
    assert db_session.query(CourseMember).count() == 1
    assert db_session.query(GroupMember).count() == 1


def test_upsert_skips_unknown_keycloak_user(db_session):
    """A student who has never logged in has no `users` row. The helper
    must skip them silently rather than crashing the deploy."""
    _seed_user(db_session, "kc-known", 1)
    course = _seed_course(db_session)
    payload = [
        StackAssignment(
            stack_index=1,
            groups=[
                GroupInfo(
                    group_name="Group A",
                    group_index=1,
                    students=[_student("kc-known", 1), _student("kc-unknown", 2)],
                    course_group_id=None,
                ),
            ],
        ),
    ]
    out = DeploymentService(db_session)._upsert_course_membership_graph(
        course=course,
        stack_assignments=payload,
    )

    # CourseGroup still created.
    cg = db_session.query(CourseGroup).filter_by(course_id=course.id, name="Group A").one()
    assert out[0]["groups"][0]["course_group_id"] == cg.id

    # Only the known student has membership rows.
    assert db_session.query(CourseMember).count() == 1
    assert db_session.query(GroupMember).count() == 1


def test_upsert_reuses_existing_course_group_by_name(db_session):
    """When the lecturer has manually created a CourseGroup for this name
    already (via the courses UI), the helper must reuse it rather than
    spawning a duplicate."""
    _seed_user(db_session, "kc-stud-1", 1)
    course = _seed_course(db_session)
    existing_cg = CourseGroup(course_id=course.id, name="Group A")
    db_session.add(existing_cg)
    db_session.flush()

    payload = [
        StackAssignment(
            stack_index=1,
            groups=[
                GroupInfo(
                    group_name="Group A",
                    group_index=1,
                    students=[_student("kc-stud-1", 1)],
                    course_group_id=None,
                ),
            ],
        ),
    ]
    out = DeploymentService(db_session)._upsert_course_membership_graph(
        course=course,
        stack_assignments=payload,
    )

    assert out[0]["groups"][0]["course_group_id"] == existing_cg.id
    assert db_session.query(CourseGroup).count() == 1


def test_upsert_trusts_valid_hint_id(db_session):
    """If the frontend already sent a valid course_group_id for this course,
    the helper must trust it (covers in-place rename in the lecturer UI)."""
    _seed_user(db_session, "kc-stud-1", 1)
    course = _seed_course(db_session)
    existing_cg = CourseGroup(course_id=course.id, name="Original Name")
    db_session.add(existing_cg)
    db_session.flush()

    payload = [
        StackAssignment(
            stack_index=1,
            groups=[
                GroupInfo(
                    # Renamed in the UI; backend should still hit the original row.
                    group_name="Renamed Group",
                    group_index=1,
                    students=[_student("kc-stud-1", 1)],
                    course_group_id=existing_cg.id,
                ),
            ],
        ),
    ]
    out = DeploymentService(db_session)._upsert_course_membership_graph(
        course=course,
        stack_assignments=payload,
    )

    assert out[0]["groups"][0]["course_group_id"] == existing_cg.id
    assert db_session.query(CourseGroup).count() == 1


def test_upsert_reactivates_soft_left_course_member(db_session):
    """A CourseMember with ``left_at != None`` (student previously removed)
    must be reactivated, not duplicated. The student-list query filters on
    ``left_at IS NULL``, so without this they'd stay invisible."""
    from datetime import datetime, timezone

    user = _seed_user(db_session, "kc-stud-1", 1)
    course = _seed_course(db_session)
    soft_left = CourseMember(
        user_id=user.id,
        course_id=course.id,
        left_at=datetime.now(timezone.utc),
    )
    db_session.add(soft_left)
    db_session.flush()

    payload = [
        StackAssignment(
            stack_index=1,
            groups=[
                GroupInfo(
                    group_name="Group A",
                    group_index=1,
                    students=[_student("kc-stud-1", 1)],
                    course_group_id=None,
                ),
            ],
        ),
    ]
    DeploymentService(db_session)._upsert_course_membership_graph(
        course=course,
        stack_assignments=payload,
    )

    db_session.refresh(soft_left)
    assert soft_left.left_at is None
    assert db_session.query(CourseMember).count() == 1
