import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from curx.core.config import Settings
from curx.core.database import Base, create_session_factory
from curx.domain.models import AccessKey, AuditLog, BrowserSession
from curx.main import create_app
from curx.services.identity_service import bootstrap_admin, utc_now


@dataclass
class IdentityEnvironment:
    app_client: TestClient
    session_factory: sessionmaker[Session]
    admin_key: str


def test_secure_runtime_defaults_use_the_curx_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CURX_APP_PORT", raising=False)
    monkeypatch.delenv("CURX_SESSION_COOKIE_SECURE", raising=False)
    monkeypatch.delenv("CURX_AUTH_REQUIRED", raising=False)
    settings = Settings(_env_file=None)

    assert settings.app_port == 8020
    assert settings.session_cookie_secure is True
    assert settings.auth_required is True


@pytest.fixture
def identity_environment() -> Iterator[IdentityEnvironment]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        session_cookie_secure=False,
        auth_attempt_limit=3,
        auth_attempt_window_seconds=300,
        _env_file=None,
    )
    with session_factory() as db:
        _, _, _, admin_key = bootstrap_admin(
            db,
            tenant_name="Curx Test",
            tenant_slug="curx-test",
            username="admin",
            display_name="Test Admin",
            expires_in_days=30,
        )

    with TestClient(create_app(settings, session_factory)) as client:
        yield IdentityEnvironment(
            app_client=client,
            session_factory=session_factory,
            admin_key=admin_key,
        )
    engine.dispose()


def bind_admin(environment: IdentityEnvironment) -> dict:
    response = environment.app_client.post(
        "/api/auth/bind",
        json={"username": "admin", "access_key": environment.admin_key},
    )
    assert response.status_code == 200
    return response.json()


def issue_member_key(environment: IdentityEnvironment) -> dict:
    bind_admin(environment)
    workspace = environment.app_client.get("/api/workspace").json()
    response = environment.app_client.post(
        "/api/admin/access-keys",
        json={
            "label": "Alice access",
            "granted_role": "member",
            "expires_at": (utc_now() + timedelta(days=7)).isoformat(),
            "knowledge_space_ids": [workspace["spaces"][0]["id"]],
        },
    )
    assert response.status_code == 201
    return response.json()


def test_admin_binding_sets_http_only_cookie_and_loads_database_workspace(
    identity_environment: IdentityEnvironment,
) -> None:
    payload = bind_admin(identity_environment)

    assert payload["user"]["username"] == "admin"
    assert payload["user"]["role"] == "admin"
    set_cookie = identity_environment.app_client.post(
        "/api/auth/bind",
        json={"username": "admin", "access_key": identity_environment.admin_key},
    ).headers["set-cookie"]
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie

    workspace = identity_environment.app_client.get("/api/workspace")
    assert workspace.status_code == 200
    assert workspace.json()["current_user"]["tenant"]["slug"] == "curx-test"
    assert workspace.json()["spaces"][0]["name"] == "默认知识空间"
    assert workspace.json()["spaces"][0]["can_manage"] is True


def test_chat_requires_an_active_authenticated_session(
    identity_environment: IdentityEnvironment,
) -> None:
    response = identity_environment.app_client.post(
        "/api/chat/answer",
        json={"messages": [{"role": "user", "content": "匿名请求"}]},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "authentication_required"


def test_session_status_reports_authentication_without_triggering_401(
    identity_environment: IdentityEnvironment,
) -> None:
    anonymous = identity_environment.app_client.get("/api/auth/session")
    assert anonymous.status_code == 200
    assert anonymous.json() == {"authenticated": False}

    bind_admin(identity_environment)
    authenticated = identity_environment.app_client.get("/api/auth/session")
    assert authenticated.status_code == 200
    assert authenticated.json() == {"authenticated": True}


def test_admin_can_issue_key_once_and_member_cannot_use_admin_api(
    identity_environment: IdentityEnvironment,
) -> None:
    created = issue_member_key(identity_environment)
    assert created["access_key"].startswith(f"curx_{created['prefix']}_")

    listed = identity_environment.app_client.get("/api/admin/access-keys")
    assert listed.status_code == 200
    assert all("access_key" not in item for item in listed.json())

    with TestClient(identity_environment.app_client.app) as member_client:
        bound = member_client.post(
            "/api/auth/bind",
            json={
                "username": "alice",
                "display_name": "Alice",
                "access_key": created["access_key"],
            },
        )
        assert bound.status_code == 200
        assert bound.json()["user"]["role"] == "member"
        assert member_client.get("/api/workspace").json()["spaces"][0]["can_write"] is False
        denied = member_client.get("/api/admin/access-keys")
        assert denied.status_code == 403
        assert denied.json()["detail"]["code"] == "admin_required"


def test_key_binding_cannot_assume_an_existing_higher_privilege_username(
    identity_environment: IdentityEnvironment,
) -> None:
    created = issue_member_key(identity_environment)

    with TestClient(identity_environment.app_client.app) as client:
        response = client.post(
            "/api/auth/bind",
            json={"username": "admin", "access_key": created["access_key"]},
        )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_credentials"


def test_revoking_key_invalidates_existing_browser_session_immediately(
    identity_environment: IdentityEnvironment,
) -> None:
    created = issue_member_key(identity_environment)

    with TestClient(identity_environment.app_client.app) as member_client:
        assert (
            member_client.post(
                "/api/auth/bind",
                json={"username": "alice", "access_key": created["access_key"]},
            ).status_code
            == 200
        )
        assert member_client.get("/api/auth/me").status_code == 200

        revoked = identity_environment.app_client.delete(
            f"/api/admin/access-keys/{created['id']}"
        )
        assert revoked.status_code == 200
        assert revoked.json()["status"] == "revoked"

        invalidated = member_client.get("/api/auth/me")
        assert invalidated.status_code == 401
        assert invalidated.json()["detail"]["code"] == "expired_session"
        denied_chat = member_client.post(
            "/api/chat/answer",
            json={"messages": [{"role": "user", "content": "撤销后请求"}]},
        )
        assert denied_chat.status_code == 401


def test_expired_key_cannot_create_a_browser_session(
    identity_environment: IdentityEnvironment,
) -> None:
    created = issue_member_key(identity_environment)
    with identity_environment.session_factory() as db:
        stored_key = db.get(AccessKey, UUID(created["id"]))
        assert stored_key is not None
        stored_key.expires_at = utc_now() - timedelta(seconds=1)
        db.commit()

    with TestClient(identity_environment.app_client.app) as client:
        response = client.post(
            "/api/auth/bind",
            json={"username": "alice", "access_key": created["access_key"]},
        )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_credentials"


def test_failed_binding_is_rate_limited_and_audited(
    identity_environment: IdentityEnvironment,
) -> None:
    invalid_key = "curx_deadbeef_not-a-real-secret-value"
    for _ in range(3):
        response = identity_environment.app_client.post(
            "/api/auth/bind",
            json={"username": "blocked-user", "access_key": invalid_key},
        )
        assert response.status_code == 401

    limited = identity_environment.app_client.post(
        "/api/auth/bind",
        json={"username": "blocked-user", "access_key": invalid_key},
    )
    assert limited.status_code == 429
    assert limited.json()["detail"]["code"] == "too_many_attempts"

    with identity_environment.session_factory() as db:
        logs = list(
            db.scalars(
                select(AuditLog)
                .where(AuditLog.subject == "blocked-user")
                .order_by(AuditLog.created_at)
            )
        )
    assert [log.outcome for log in logs] == [
        "failure",
        "failure",
        "failure",
        "rate_limited",
    ]


def test_plaintext_keys_and_session_tokens_are_never_persisted(
    identity_environment: IdentityEnvironment,
) -> None:
    created = issue_member_key(identity_environment)
    raw_key = created["access_key"]

    with TestClient(identity_environment.app_client.app) as member_client:
        bound = member_client.post(
            "/api/auth/bind",
            json={"username": "alice", "access_key": raw_key},
        )
        assert bound.status_code == 200
        raw_session = member_client.cookies.get("curx_session")
        assert raw_session

        with identity_environment.session_factory() as db:
            stored_key = db.scalar(
                select(AccessKey).where(AccessKey.prefix == created["prefix"])
            )
            stored_session = db.scalar(
                select(BrowserSession).where(BrowserSession.user_id == stored_key.binding.user_id)
            )
            audits = list(db.scalars(select(AuditLog)))

    assert stored_key is not None
    assert raw_key not in stored_key.key_hash
    assert stored_session is not None
    assert raw_session != stored_session.token_hash
    assert raw_key not in json.dumps(
        [audit.details for audit in audits],
        ensure_ascii=False,
    )
