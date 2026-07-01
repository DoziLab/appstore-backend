"""Tests for LecturerService.

Uses an in-memory SQLite database + real models. Deployment ownership
is embedded in ``deployment_parameters`` JSON — the service uses the
SQLite fallback path (per-row Python parse), so these tests exercise it
end-to-end.
"""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.core.database import Base
from src.core.exceptions import BadRequestException, NotFoundException
from src.models.course import Course
from src.models.deployment import Deployment, DeploymentStatus
from src.models.openstack_project import OpenstackProject
from src.models.template import Template, TemplateVisibility
from src.models.template_version import TemplateVersion
from src.models.user import User
from src.services.lecturer_service import LecturerService


@pytest.fixture
def db_session():
    """Fresh in-memory SQLite with the full schema."""
    # Register every model that Base metadata references.
    import src.models.deployment_instance  # noqa: F401
    import src.models.deployment_instance_access  # noqa: F401
    import src.models.deployment_log  # noqa: F401
    import src.models.template_version_file  # noqa: F401
    import src.models.template_category  # noqa: F401
    import src.models.template_category_assignment  # noqa: F401
    import src.models.course_member  # noqa: F401
    import src.models.course_group  # noqa: F401
    import src.models.group_member  # noqa: F401

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


def _lecturer(db, external_id, email, display_name):
    u = User(external_id=external_id, email=email, display_name=display_name)
    db.add(u)
    db.flush()
    return u


def _template(db, owner, name="t"):
    t = Template(
        name=name,
        owner_id=owner.id,
        repo_url="https://example.com/repo",
        visibility=TemplateVisibility.PRIVATE,
    )
    db.add(t)
    db.flush()
    return t


def _version(db, template, version="1.0.0"):
    v = TemplateVersion(
        template_id=template.id, version=version, git_commit_sha="abc"
    )
    db.add(v)
    db.flush()
    return v


def _osp(db, owner, name="osp"):
    op = OpenstackProject(
        owner_user_id=owner.id,
        openstack_project_id="ks-1",
        openstack_project_name=name,
        auth_url="https://example.com",
        username="u",
        password="p",
        region_name="r",
    )
    db.add(op)
    db.flush()
    return op


def _course(db, name="C"):
    c = Course(name=name, keycloak_course_id="kc-course-1")
    db.add(c)
    db.flush()
    return c


def _deployment_for(db, lecturer, template_version, osp, course, name="d"):
    """Wire up a Deployment whose deployment_parameters.teacher.id matches
    the lecturer's external_id — that's how the service maps ownership."""
    d = Deployment(
        name=name,
        template_version_id=template_version.id,
        course_id=course.id,
        openstack_project_id=osp.id,
        status=DeploymentStatus.RUNNING,
        deployment_parameters=json.dumps({
            "teacher": {"id": lecturer.external_id, "email": lecturer.email},
        }),
    )
    db.add(d)
    db.flush()
    return d


# ---------------------------------------------------------------------------
# list_lecturers
# ---------------------------------------------------------------------------

def test_list_lecturers_returns_owners_only_excludes_pure_students(db_session):
    """A user without templates AND without OSPs must not appear."""
    lecturer = _lecturer(db_session, "kc-1", "l@x.de", "Lecturer 1")
    _template(db_session, lecturer)

    # A student-like user with nothing owned
    _lecturer(db_session, "kc-2", "s@x.de", "Just Student")

    svc = LecturerService(db_session)
    rows, total = svc.list_lecturers()

    assert total == 1
    assert rows[0]["external_id"] == "kc-1"
    assert rows[0]["template_count"] == 1


def test_list_lecturers_counts_template_and_deployment(db_session):
    lecturer = _lecturer(db_session, "kc-1", "l@x.de", "L1")
    template = _template(db_session, lecturer)
    version = _version(db_session, template)
    osp = _osp(db_session, lecturer)
    course = _course(db_session)
    _deployment_for(db_session, lecturer, version, osp, course, name="d-1")
    _deployment_for(db_session, lecturer, version, osp, course, name="d-2")

    svc = LecturerService(db_session)
    rows, _ = svc.list_lecturers()

    only = rows[0]
    assert only["template_count"] == 1
    assert only["deployment_count"] == 2
    assert only["openstack_project_count"] == 1


def test_list_lecturers_search_filters_case_insensitively(db_session):
    a = _lecturer(db_session, "kc-a", "alice@x.de", "Alice Prof")
    _template(db_session, a)
    b = _lecturer(db_session, "kc-b", "bob@x.de", "Bob Prof")
    _template(db_session, b)

    svc = LecturerService(db_session)
    rows, total = svc.list_lecturers(search="alice")

    assert total == 1
    assert rows[0]["external_id"] == "kc-a"


def test_list_lecturers_pagination(db_session):
    for i in range(5):
        u = _lecturer(db_session, f"kc-{i}", f"u{i}@x.de", f"User {i}")
        _template(db_session, u, name=f"t-{i}")

    svc = LecturerService(db_session)
    _, total = svc.list_lecturers(skip=0, limit=2)
    rows_page2, _ = svc.list_lecturers(skip=2, limit=2)
    rows_page3, _ = svc.list_lecturers(skip=4, limit=2)

    assert total == 5
    assert len(rows_page2) == 2
    assert len(rows_page3) == 1


# ---------------------------------------------------------------------------
# get_lecturer
# ---------------------------------------------------------------------------

def test_get_lecturer_returns_full_detail(db_session):
    lecturer = _lecturer(db_session, "kc-1", "l@x.de", "L")
    template = _template(db_session, lecturer, name="mytpl")
    _version(db_session, template)
    _version(db_session, template, version="1.1.0")
    osp = _osp(db_session, lecturer, name="myosp")
    course = _course(db_session)
    _deployment_for(db_session, lecturer, template.versions[0], osp, course, name="d1")

    svc = LecturerService(db_session)
    detail = svc.get_lecturer(lecturer.id)

    assert detail["template_count"] == 1
    assert detail["deployment_count"] == 1
    assert detail["openstack_project_count"] == 1
    assert detail["templates"][0]["name"] == "mytpl"
    assert detail["templates"][0]["version_count"] == 2
    assert detail["deployments"][0]["name"] == "d1"
    assert detail["openstack_projects"][0]["openstack_project_name"] == "myosp"


def test_get_lecturer_404_for_non_lecturer(db_session):
    """A user with no owned resources isn't reachable through /lecturers/."""
    u = _lecturer(db_session, "kc-1", "s@x.de", "Just Student")
    svc = LecturerService(db_session)
    with pytest.raises(NotFoundException):
        svc.get_lecturer(u.id)


def test_get_lecturer_404_for_unknown_id(db_session):
    svc = LecturerService(db_session)
    with pytest.raises(NotFoundException):
        svc.get_lecturer("00000000-0000-0000-0000-000000000000")


# ---------------------------------------------------------------------------
# preflight_delete
# ---------------------------------------------------------------------------

def test_preflight_delete_returns_counts(db_session):
    lecturer = _lecturer(db_session, "kc-1", "l@x.de", "L")
    template = _template(db_session, lecturer)
    version = _version(db_session, template)
    osp = _osp(db_session, lecturer)
    course = _course(db_session)
    _deployment_for(db_session, lecturer, version, osp, course)

    svc = LecturerService(db_session)
    summary = svc.preflight_delete(user_id=lecturer.id, requesting_user_id="admin-1")

    assert summary["deployment_count"] == 1
    assert summary["template_count"] == 1


def test_preflight_delete_rejects_self_delete(db_session):
    lecturer = _lecturer(db_session, "kc-1", "l@x.de", "L")
    _template(db_session, lecturer)

    svc = LecturerService(db_session)
    with pytest.raises(BadRequestException):
        svc.preflight_delete(user_id=lecturer.id, requesting_user_id=lecturer.id)
