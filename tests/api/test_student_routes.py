"""Integration tests for the student self-service endpoints.

Uses a real in-memory SQLite DB with the production SQLAlchemy models so
the multi-join authorization query is exercised end-to-end, not mocked.

Verifies the security boundaries:
- A student sees ONLY credentials for groups they belong to
- A student NEVER sees teacher-admin credentials (group_id IS NULL)
- A student NEVER sees other groups' credentials
- A student NEVER sees deployments they have no group on
- Lecturers / unauthenticated callers cannot use the /student/* routes
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.main import app
from src.core.database import Base
from src.core.dependencies import get_current_user, get_db
from src.models.course import Course
from src.models.course_group import CourseGroup
from src.models.course_member import CourseMember
from src.models.deployment import Deployment, DeploymentStatus
from src.models.deployment_instance import DeploymentInstance, DeploymentInstanceStatus
from src.models.deployment_instance_access import AccessType, DeploymentInstanceAccess
from src.models.group_member import GroupMember
from src.models.openstack_project import OpenstackProject
from src.models.template import Template
from src.models.template_version import TemplateVersion
from src.models.user import User, UserRole


SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db_session():
    """Fresh DB per test. Imports every model so the metadata sees them all."""
    # Force registration of every model so Base.metadata.create_all() builds the full schema.
    import src.models.deployment  # noqa
    import src.models.deployment_instance  # noqa
    import src.models.deployment_instance_access  # noqa
    import src.models.deployment_log  # noqa
    import src.models.template  # noqa
    import src.models.template_version  # noqa
    import src.models.template_category  # noqa
    import src.models.template_category_assignment  # noqa
    import src.models.template_version_file  # noqa
    import src.models.course  # noqa
    import src.models.course_member  # noqa
    import src.models.course_group  # noqa
    import src.models.group_member  # noqa
    import src.models.openstack_project  # noqa
    import src.models.user  # noqa

    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


# ---------------------------------------------------------------------------
# Auth helpers — keep these in sync with the lecturer test files
# ---------------------------------------------------------------------------


def _student_user(user_id: str = "student-local-id"):
    return {
        "sub": "kc-student-1",
        "email": "alice@uni.de",
        "preferred_username": "alice",
        "roles": [UserRole.STUDENT.value],
        "user_id": user_id,
    }


def _lecturer_user():
    return {
        "sub": "kc-lecturer-1",
        "email": "prof@uni.de",
        "preferred_username": "prof",
        "roles": [UserRole.LECTURER.value],
        "user_id": "lecturer-local-id",
    }


# ---------------------------------------------------------------------------
# Test fixtures: seed a deployment with two groups, the student in one of them
# ---------------------------------------------------------------------------


SAMPLE_PEM = (
    "-----BEGIN OPENSSH PRIVATE KEY-----\n"
    "STUDENT-KEY-PLACEHOLDER\n"
    "-----END OPENSSH PRIVATE KEY-----\n"
)


@pytest.fixture()
def seeded(db_session):
    """Seed a course with two groups; student is a member of group A only.

    The deployment has access rows for:
    - Group A (the student's group) — should be visible
    - Group B (other group) — should NOT be visible
    - Teacher admin (group_id IS NULL) — should NEVER be visible
    """
    # Users
    student = User(id="student-local-id", external_id="kc-student-1", username="alice")
    lecturer = User(id="lecturer-local-id", external_id="kc-lecturer-1", username="prof")
    db_session.add_all([student, lecturer])

    # Course + groups
    course = Course(id="course-1", name="DB Lab", keycloak_course_id="kc-course-1")
    group_a = CourseGroup(id="cg-a", course_id="course-1", name="Gruppe A")
    group_b = CourseGroup(id="cg-b", course_id="course-1", name="Gruppe B")
    db_session.add_all([course, group_a, group_b])

    # Student is in group A (via CourseMember + GroupMember)
    cm_student = CourseMember(id="cm-student", user_id="student-local-id", course_id="course-1")
    db_session.add(cm_student)
    gm_student = GroupMember(id="gm-student", group_id="cg-a", course_member_id="cm-student")
    db_session.add(gm_student)

    # Template + deployment
    template = Template(
        id="tmpl-1",
        name="Ubuntu Lab",
        owner_id="lecturer-local-id",
        repo_url="https://example.test/repo",
        visibility="public",
    )
    version = TemplateVersion(
        id="ver-1",
        template_id="tmpl-1",
        version="1.0.0",
        git_commit_sha="abc123",
        approval_status="approved",
    )
    db_session.add_all([template, version])

    # OpenstackProject is a NOT-NULL FK on Deployment, so we need one even
    # though student endpoints never read it.
    osp = OpenstackProject(
        id="osp-1",
        owner_user_id="lecturer-local-id",
        openstack_project_id="kc-osp-1",
        openstack_project_name="test-osp",
        auth_url="https://example.test/keystone/v3",
        username="kc-user",
        password="kc-pass",
        region_name="r1",
    )
    db_session.add(osp)

    deployment = Deployment(
        id="dep-1",
        name="DB Lab Run",
        template_version_id="ver-1",
        course_id="course-1",
        openstack_project_id="osp-1",
        status=DeploymentStatus.RUNNING,
        deployment_parameters='{"teacher": {"id": "kc-lecturer-1"}}',
    )
    db_session.add(deployment)

    inst = DeploymentInstance(
        id="inst-1",
        deployment_id="dep-1",
        vm_name="dep-1-s1",
        openstack_server_id="stack-uuid",
        ip_address="1.2.3.4",
        status=DeploymentInstanceStatus.RUNNING,
    )
    db_session.add(inst)

    # Access rows: group A, group B, admin (no group)
    db_session.add_all([
        DeploymentInstanceAccess(
            id="acc-a-ssh",
            deployment_instance_id="inst-1",
            access_type=AccessType.SSH,
            username="gruppe-a",
            password="GroupAPw-123",
            ssh_private_key=SAMPLE_PEM,
            group_id="cg-a",
            connection_url="ssh gruppe-a@1.2.3.4",
            port=22,
        ),
        DeploymentInstanceAccess(
            id="acc-a-db",
            deployment_instance_id="inst-1",
            access_type=AccessType.DATABASE,
            username="grpa_db",
            password="GroupADbPw",
            group_id="cg-a",
            port=5432,
        ),
        DeploymentInstanceAccess(
            id="acc-b-ssh",
            deployment_instance_id="inst-1",
            access_type=AccessType.SSH,
            username="gruppe-b",
            password="GroupBPw-456",
            ssh_private_key="-----BEGIN OPENSSH PRIVATE KEY-----\nGROUP-B-KEY\n-----END OPENSSH PRIVATE KEY-----\n",
            group_id="cg-b",
            connection_url="ssh gruppe-b@1.2.3.4",
            port=22,
        ),
        DeploymentInstanceAccess(
            id="acc-admin",
            deployment_instance_id="inst-1",
            access_type=AccessType.SSH,
            username="prof",
            password="AdminPw",
            ssh_private_key="-----BEGIN OPENSSH PRIVATE KEY-----\nADMIN-KEY\n-----END OPENSSH PRIVATE KEY-----\n",
            group_id=None,  # ← admin credentials must NEVER be returned to students
            connection_url="ssh prof@1.2.3.4",
            port=22,
        ),
    ])

    db_session.commit()


@pytest.fixture()
def client(db_session):
    """TestClient with the in-memory DB wired in."""
    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Auth tests — router-level guards
# ---------------------------------------------------------------------------


def test_student_routes_require_authentication(client, seeded):
    """No auth header → 401, not 403."""
    response = client.get("/api/v1/student/deployments")
    assert response.status_code == 401


def test_student_routes_reject_lecturer_token(client, seeded):
    """Lecturer hits a /student/* route → 403."""
    app.dependency_overrides[get_current_user] = _lecturer_user
    try:
        response = client.get("/api/v1/student/deployments")
        assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)


# ---------------------------------------------------------------------------
# GET /student/deployments
# ---------------------------------------------------------------------------


def test_student_sees_only_deployments_with_their_group(client, seeded):
    app.dependency_overrides[get_current_user] = _student_user
    try:
        response = client.get("/api/v1/student/deployments")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["success"] is True
        items = body["data"]
        assert len(items) == 1
        d = items[0]
        assert d["id"] == "dep-1"
        assert d["name"] == "DB Lab Run"
        assert d["template"]["name"] == "Ubuntu Lab"
        # No leak of lecturer / parameters fields
        assert "deployment_parameters" not in d
        assert "teacher" not in d
        # Instance metadata is trimmed
        assert d["instances"][0]["vm_name"] == "dep-1-s1"
        assert d["instances"][0]["ip_address"] == "1.2.3.4"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_student_with_no_group_memberships_sees_empty_list(client, db_session, seeded):
    """A student who is registered but in zero groups sees no deployments."""
    # Add another student without any group membership.
    lonely = User(id="lonely-id", external_id="kc-lonely", username="lonely")
    db_session.add(lonely)
    db_session.commit()

    def _lonely_user():
        return {**_student_user(), "user_id": "lonely-id", "sub": "kc-lonely"}

    app.dependency_overrides[get_current_user] = _lonely_user
    try:
        response = client.get("/api/v1/student/deployments")
        assert response.status_code == 200
        assert response.json()["data"] == []
    finally:
        app.dependency_overrides.pop(get_current_user, None)


# ---------------------------------------------------------------------------
# GET /student/deployments/{id}/credentials
# ---------------------------------------------------------------------------


def test_student_credentials_returns_only_own_group_rows(client, seeded):
    """Crown jewel: student sees own group's access rows, never group B's, never admin."""
    app.dependency_overrides[get_current_user] = _student_user
    try:
        response = client.get("/api/v1/student/deployments/dep-1/credentials")
        assert response.status_code == 200, response.text

        payload = response.json()["data"]
        assert len(payload["instances"]) == 1
        accesses = payload["instances"][0]["accesses"]

        ids = sorted(a["id"] for a in accesses)
        # Exactly group A's two rows; nothing from group B; nothing from admin.
        assert ids == ["acc-a-db", "acc-a-ssh"]

        # Spot-check that group A's secrets are decrypted and visible
        ssh_entry = next(a for a in accesses if a["id"] == "acc-a-ssh")
        assert ssh_entry["password"] == "GroupAPw-123"
        assert ssh_entry["ssh_private_key"] == SAMPLE_PEM

        # And explicitly that nothing else leaks
        for a in accesses:
            assert a["username"] != "gruppe-b"
            assert a["username"] != "prof"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_student_credentials_403_when_not_in_any_group_of_deployment(client, db_session, seeded):
    """Even a registered student without group membership on this deployment gets 403."""
    db_session.add(User(id="lonely-id", external_id="kc-lonely", username="lonely"))
    db_session.commit()

    def _lonely_user():
        return {**_student_user(), "user_id": "lonely-id", "sub": "kc-lonely"}

    app.dependency_overrides[get_current_user] = _lonely_user
    try:
        response = client.get("/api/v1/student/deployments/dep-1/credentials")
        assert response.status_code == 403
        assert "BEGIN OPENSSH" not in response.text
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_student_credentials_404_for_unknown_deployment(client, seeded):
    app.dependency_overrides[get_current_user] = _student_user
    try:
        response = client.get("/api/v1/student/deployments/does-not-exist/credentials")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user, None)


# ---------------------------------------------------------------------------
# GET /student/deployments/{id}/credentials/access/{access_id}/ssh-key
# ---------------------------------------------------------------------------


def test_student_can_download_own_ssh_key(client, seeded):
    app.dependency_overrides[get_current_user] = _student_user
    try:
        response = client.get(
            "/api/v1/student/deployments/dep-1/credentials/access/acc-a-ssh/ssh-key"
        )
        assert response.status_code == 200
        assert response.text == SAMPLE_PEM
        assert response.headers["content-type"].startswith("application/x-pem-file")
        assert 'filename="id_ed25519_gruppe-a"' in response.headers["content-disposition"]
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_student_cannot_download_other_groups_ssh_key(client, seeded):
    """Adversarial: student knows group B's access_id. Must still get 403, no PEM."""
    app.dependency_overrides[get_current_user] = _student_user
    try:
        response = client.get(
            "/api/v1/student/deployments/dep-1/credentials/access/acc-b-ssh/ssh-key"
        )
        assert response.status_code == 403
        assert "GROUP-B-KEY" not in response.text
        # No download header → never tricked the browser into saving the file
        assert "content-disposition" not in {k.lower() for k in response.headers}
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_student_cannot_download_admin_ssh_key(client, seeded):
    """Even more critical: admin (group_id IS NULL) must be unreachable."""
    app.dependency_overrides[get_current_user] = _student_user
    try:
        response = client.get(
            "/api/v1/student/deployments/dep-1/credentials/access/acc-admin/ssh-key"
        )
        assert response.status_code == 403
        assert "ADMIN-KEY" not in response.text
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_student_ssh_key_404_when_access_has_no_key(client, db_session, seeded):
    """Own-group access row without a key → 404, not 200 with empty body."""
    # Strip the key from the student's row.
    db_session.query(DeploymentInstanceAccess).filter_by(id="acc-a-ssh").update(
        {"ssh_private_key": None}
    )
    db_session.commit()

    app.dependency_overrides[get_current_user] = _student_user
    try:
        response = client.get(
            "/api/v1/student/deployments/dep-1/credentials/access/acc-a-ssh/ssh-key"
        )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_student_ssh_key_404_for_unknown_access(client, seeded):
    app.dependency_overrides[get_current_user] = _student_user
    try:
        response = client.get(
            "/api/v1/student/deployments/dep-1/credentials/access/no-such-id/ssh-key"
        )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user, None)
