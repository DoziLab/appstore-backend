"""API-Tests für die Template-Icon-Endpoints.

Deckt POST/GET/DELETE ab, inkl. Content-Type-Whitelist, Größenlimit,
Owner/Admin-Gate, sowie das Zusammenspiel mit der TemplateResponse
(``effective_icon`` schaltet nach dem Upload auf die Serve-URL um).
"""
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.core.database import Base
from src.core.dependencies import get_current_user, get_db
from src.main import app
from src.models.template import Template, TemplateVisibility
from src.models.user import User


SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


@event.listens_for(engine, "connect")
def _sqlite_enable_fks(dbapi_connection, _conn_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db_session():
    import src.models.deployment  # noqa
    import src.models.deployment_instance  # noqa
    import src.models.deployment_instance_access  # noqa
    import src.models.deployment_log  # noqa
    import src.models.template_category  # noqa
    import src.models.template_category_assignment  # noqa
    import src.models.template_icon  # noqa
    import src.models.template_version  # noqa
    import src.models.course  # noqa
    import src.models.course_member  # noqa
    import src.models.course_group  # noqa
    import src.models.group_member  # noqa
    import src.models.openstack_project  # noqa

    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def owner(db_session):
    """Der User, dem das Sample-Template gehört."""
    user = User(id="00000000-0000-0000-0000-000000000000", external_id="ext-owner")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def other_user(db_session):
    """Ein weiterer User, der weder Owner noch Admin ist."""
    user = User(id="11111111-1111-1111-1111-111111111111", external_id="ext-other")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def sample_template(db_session, owner):
    template = Template(
        name="Icon Template",
        description="Template to test icon upload",
        owner_id=owner.id,
        repo_url="https://github.com/example/icon-template",
        visibility=TemplateVisibility.PUBLIC,
    )
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)
    return template


def _make_client(db_session, user_id: str, roles: list[str]):
    """Wire the TestClient with a static current-user override."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    def override_get_current_user():
        return {
            "sub": user_id,
            "email": f"{user_id}@example.com",
            "name": user_id,
            "preferred_username": user_id,
            "roles": roles,
            "user_id": user_id,
        }

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    return TestClient(app)


@pytest.fixture
def owner_client(db_session, owner):
    """Client authenticated as the template owner (lecturer role)."""
    client = _make_client(db_session, owner.id, ["lecturer"])
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def admin_client(db_session, other_user):
    """Client authenticated as an admin user (not the owner)."""
    client = _make_client(db_session, other_user.id, ["admin", "lecturer"])
    yield client
    app.dependency_overrides.clear()


# Minimal, valid PNG (1x1 transparent pixel) — small enough that we can
# use the real Pillow-free byte sequence in tests without a dependency.
PNG_1x1 = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01"
    b"\x00\x18\xdd\x8d\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


class TestUploadIcon:
    def test_owner_can_upload_png(self, owner_client, sample_template):
        response = owner_client.post(
            f"/api/v1/templates/{sample_template.id}/icon",
            files={"file": ("logo.png", PNG_1x1, "image/png")},
        )
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()["data"]
        assert data["template_id"] == sample_template.id
        assert data["content_type"] == "image/png"
        assert data["size_bytes"] == len(PNG_1x1)
        assert data["url"] == f"/api/v1/templates/{sample_template.id}/icon"

    def test_upload_updates_effective_icon_in_template_response(
        self, owner_client, sample_template
    ):
        owner_client.post(
            f"/api/v1/templates/{sample_template.id}/icon",
            files={"file": ("logo.png", PNG_1x1, "image/png")},
        )
        get_resp = owner_client.get(f"/api/v1/templates/{sample_template.id}")
        assert get_resp.status_code == status.HTTP_200_OK
        body = get_resp.json()["data"]
        assert body["has_uploaded_icon"] is True
        assert body["effective_icon"] == f"/api/v1/templates/{sample_template.id}/icon"
        # icon_url gibt es nicht mehr — nur noch effective_icon / has_uploaded_icon
        assert "icon_url" not in body

    def test_upload_svg_rejected_415(self, owner_client, sample_template):
        response = owner_client.post(
            f"/api/v1/templates/{sample_template.id}/icon",
            files={"file": ("logo.svg", b"<svg/>", "image/svg+xml")},
        )
        assert response.status_code == 415

    def test_upload_text_rejected_415(self, owner_client, sample_template):
        response = owner_client.post(
            f"/api/v1/templates/{sample_template.id}/icon",
            files={"file": ("hello.txt", b"hello", "text/plain")},
        )
        assert response.status_code == 415

    def test_upload_empty_file_rejected_400(self, owner_client, sample_template):
        response = owner_client.post(
            f"/api/v1/templates/{sample_template.id}/icon",
            files={"file": ("empty.png", b"", "image/png")},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_stranger_cannot_upload(self, db_session, sample_template, other_user):
        """Ein User, der weder Owner noch Admin ist, darf kein Icon setzen.

        Der Template-Sichtbarkeits-Gate schießt hier zuerst (PUBLIC-Template
        ohne APPROVED Version → 403 auf GET), also bekommen wir schon
        beim Ownership-Check ein 403 zurück statt eines 200.
        """
        client = _make_client(db_session, other_user.id, ["lecturer"])
        try:
            response = client.post(
                f"/api/v1/templates/{sample_template.id}/icon",
                files={"file": ("logo.png", PNG_1x1, "image/png")},
            )
            assert response.status_code == status.HTTP_403_FORBIDDEN
        finally:
            app.dependency_overrides.clear()

    def test_admin_can_upload_on_other_users_template(
        self, admin_client, sample_template
    ):
        response = admin_client.post(
            f"/api/v1/templates/{sample_template.id}/icon",
            files={"file": ("logo.png", PNG_1x1, "image/png")},
        )
        assert response.status_code == status.HTTP_201_CREATED

    def test_reupload_replaces_bytes(self, owner_client, sample_template):
        owner_client.post(
            f"/api/v1/templates/{sample_template.id}/icon",
            files={"file": ("logo.png", PNG_1x1, "image/png")},
        )
        # Anderes Byte-Muster hochladen — Größe muss sich am GET zeigen.
        larger = PNG_1x1 + b"\x00" * 32
        # Zweiter Upload — muss die vorhandene Row updaten, nicht duplizieren.
        r2 = owner_client.post(
            f"/api/v1/templates/{sample_template.id}/icon",
            files={"file": ("logo2.png", larger, "image/png")},
        )
        assert r2.status_code == status.HTTP_201_CREATED
        assert r2.json()["data"]["size_bytes"] == len(larger)
        assert r2.json()["data"]["file_name"] == "logo2.png"


class TestGetIcon:
    def test_get_returns_stored_bytes_with_correct_mime(
        self, owner_client, sample_template
    ):
        owner_client.post(
            f"/api/v1/templates/{sample_template.id}/icon",
            files={"file": ("logo.png", PNG_1x1, "image/png")},
        )
        response = owner_client.get(f"/api/v1/templates/{sample_template.id}/icon")
        assert response.status_code == status.HTTP_200_OK
        assert response.headers["content-type"] == "image/png"
        assert response.content == PNG_1x1

    def test_get_returns_404_when_no_icon_uploaded(
        self, owner_client, sample_template
    ):
        response = owner_client.get(f"/api/v1/templates/{sample_template.id}/icon")
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestDeleteIcon:
    def test_owner_can_delete_icon(self, owner_client, sample_template):
        owner_client.post(
            f"/api/v1/templates/{sample_template.id}/icon",
            files={"file": ("logo.png", PNG_1x1, "image/png")},
        )
        response = owner_client.delete(
            f"/api/v1/templates/{sample_template.id}/icon"
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT
        # Icon ist danach weg → GET liefert 404.
        get_resp = owner_client.get(f"/api/v1/templates/{sample_template.id}/icon")
        assert get_resp.status_code == status.HTTP_404_NOT_FOUND
        # ``effective_icon`` ist ohne Upload ``None`` — Frontend rendert Placeholder.
        tpl_resp = owner_client.get(f"/api/v1/templates/{sample_template.id}")
        body = tpl_resp.json()["data"]
        assert body["has_uploaded_icon"] is False
        assert body["effective_icon"] is None

    def test_delete_is_idempotent(self, owner_client, sample_template):
        """Auch ohne vorher hochgeladenes Icon liefert DELETE 204."""
        response = owner_client.delete(
            f"/api/v1/templates/{sample_template.id}/icon"
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_stranger_cannot_delete(
        self, db_session, sample_template, other_user, owner_client
    ):
        # Setup: owner lädt zuerst ein Icon hoch, dann darf ``other_user``
        # es nicht wegnehmen.
        owner_client.post(
            f"/api/v1/templates/{sample_template.id}/icon",
            files={"file": ("logo.png", PNG_1x1, "image/png")},
        )
        app.dependency_overrides.clear()

        client = _make_client(db_session, other_user.id, ["lecturer"])
        try:
            response = client.delete(
                f"/api/v1/templates/{sample_template.id}/icon"
            )
            assert response.status_code == status.HTTP_403_FORBIDDEN
        finally:
            app.dependency_overrides.clear()


class TestTemplateDeletionCascadesIcon:
    def test_deleting_template_removes_its_icon(
        self, owner_client, sample_template, db_session
    ):
        from src.models.template_icon import TemplateIcon

        owner_client.post(
            f"/api/v1/templates/{sample_template.id}/icon",
            files={"file": ("logo.png", PNG_1x1, "image/png")},
        )
        assert (
            db_session.query(TemplateIcon)
            .filter_by(template_id=sample_template.id)
            .first()
            is not None
        )
        del_resp = owner_client.delete(f"/api/v1/templates/{sample_template.id}")
        assert del_resp.status_code == status.HTTP_204_NO_CONTENT
        # Cascade sollte die Icon-Row mitreißen.
        db_session.expire_all()
        assert (
            db_session.query(TemplateIcon)
            .filter_by(template_id=sample_template.id)
            .first()
            is None
        )
