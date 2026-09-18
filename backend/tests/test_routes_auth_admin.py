"""Route-level tests for login/session auth and the admin-only routes.

Like the rest of this test suite (see test_api_auth.py's original
version), these run against the app's real local SQLite DB via
TestClient rather than an isolated test DB -- there's no test-DB
fixture in this project yet. To stay collision-safe across repeated
runs against that shared DB, every test creates its own user(s) with a
randomized unique email rather than relying on fixed seed data."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.api.auth import hash_password
from app.db.models import UserORM
from app.db.session import SessionLocal, init_db
from app.main import app


def _make_user(role: str = "employee", is_active: bool = True) -> tuple[str, str]:
    """Creates a user directly in the DB and returns (email, password).
    Calls init_db() first (idempotent) so this works even as the very
    first DB access in the test session, before any TestClient's startup
    event would otherwise have created the tables."""
    init_db()
    email = f"{uuid.uuid4()}@example.com"
    password = "test-password-123"
    db = SessionLocal()
    try:
        db.add(
            UserORM(
                email=email,
                password_hash=hash_password(password),
                full_name="Test User",
                role=role,
                is_active=is_active,
            )
        )
        db.commit()
    finally:
        db.close()
    return email, password


def _login(client: TestClient, email: str, password: str) -> str:
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def test_login_with_correct_credentials_returns_a_token_and_user_info():
    email, password = _make_user(role="employee")
    with TestClient(app) as client:
        r = client.post("/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200
        body = r.json()
        assert body["user"]["email"] == email
        assert body["user"]["role"] == "employee"
        assert len(body["token"]) > 20


def test_login_with_wrong_password_is_rejected():
    email, _ = _make_user()
    with TestClient(app) as client:
        r = client.post("/auth/login", json={"email": email, "password": "wrong"})
        assert r.status_code == 401


def test_login_for_unknown_email_is_rejected_not_a_500():
    with TestClient(app) as client:
        r = client.post("/auth/login", json={"email": "nobody@example.com", "password": "x"})
        assert r.status_code == 401


def test_login_for_deactivated_user_is_rejected():
    email, password = _make_user(is_active=False)
    with TestClient(app) as client:
        r = client.post("/auth/login", json={"email": email, "password": password})
        assert r.status_code == 401


def test_protected_route_requires_a_bearer_token():
    with TestClient(app) as client:
        r = client.get("/clients")
        assert r.status_code == 401


def test_protected_route_rejects_a_garbage_token():
    with TestClient(app) as client:
        r = client.get("/clients", headers={"Authorization": "Bearer not-a-real-token"})
        assert r.status_code == 401


def test_protected_route_succeeds_with_a_valid_token():
    email, password = _make_user()
    with TestClient(app) as client:
        token = _login(client, email, password)
        r = client.get("/clients", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200


def test_auth_me_returns_the_logged_in_user():
    email, password = _make_user(role="admin")
    with TestClient(app) as client:
        token = _login(client, email, password)
        r = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json()["email"] == email
        assert r.json()["role"] == "admin"


def test_logout_invalidates_the_token():
    email, password = _make_user()
    with TestClient(app) as client:
        token = _login(client, email, password)
        r = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        r2 = client.get("/clients", headers={"Authorization": f"Bearer {token}"})
        assert r2.status_code == 401


def test_health_check_does_not_require_auth():
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200


def test_admin_routes_reject_a_regular_employee():
    email, password = _make_user(role="employee")
    with TestClient(app) as client:
        token = _login(client, email, password)
        r = client.get("/admin/users", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403


def test_admin_can_list_and_create_users():
    admin_email, admin_password = _make_user(role="admin")
    new_email = f"{uuid.uuid4()}@example.com"
    with TestClient(app) as client:
        token = _login(client, admin_email, admin_password)
        headers = {"Authorization": f"Bearer {token}"}

        r = client.get("/admin/users", headers=headers)
        assert r.status_code == 200
        assert any(u["email"] == admin_email for u in r.json())

        r2 = client.post(
            "/admin/users",
            headers=headers,
            json={"full_name": "New Employee", "email": new_email, "password": "abc12345", "role": "employee"},
        )
        assert r2.status_code == 200, r2.text
        assert r2.json()["email"] == new_email
        assert r2.json()["role"] == "employee"


def test_admin_creating_a_duplicate_email_is_rejected():
    admin_email, admin_password = _make_user(role="admin")
    existing_email, _ = _make_user()
    with TestClient(app) as client:
        token = _login(client, admin_email, admin_password)
        r = client.post(
            "/admin/users",
            headers={"Authorization": f"Bearer {token}"},
            json={"full_name": "Dup", "email": existing_email, "password": "abc12345"},
        )
        assert r.status_code == 409


def test_admin_can_deactivate_a_user_and_they_can_no_longer_log_in():
    admin_email, admin_password = _make_user(role="admin")
    target_email, target_password = _make_user(role="employee")
    with TestClient(app) as client:
        admin_token = _login(client, admin_email, admin_password)
        target_token = _login(client, target_email, target_password)

        db = SessionLocal()
        try:
            target_user = db.query(UserORM).filter(UserORM.email == target_email).first()
            target_id = target_user.id
        finally:
            db.close()

        r = client.patch(
            f"/admin/users/{target_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"is_active": False},
        )
        assert r.status_code == 200
        assert r.json()["is_active"] is False

        # the already-issued session should stop working once deactivated
        r2 = client.get("/clients", headers={"Authorization": f"Bearer {target_token}"})
        assert r2.status_code == 401

        r3 = client.post("/auth/login", json={"email": target_email, "password": target_password})
        assert r3.status_code == 401


def test_admin_can_reset_a_users_password():
    admin_email, admin_password = _make_user(role="admin")
    target_email, old_password = _make_user()
    with TestClient(app) as client:
        admin_token = _login(client, admin_email, admin_password)
        db = SessionLocal()
        try:
            target_id = db.query(UserORM).filter(UserORM.email == target_email).first().id
        finally:
            db.close()

        r = client.post(
            f"/admin/users/{target_id}/reset-password",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"new_password": "brand-new-pass"},
        )
        assert r.status_code == 200

        assert client.post("/auth/login", json={"email": target_email, "password": old_password}).status_code == 401
        assert (
            client.post("/auth/login", json={"email": target_email, "password": "brand-new-pass"}).status_code == 200
        )


def test_activity_log_records_login_and_client_creation():
    admin_email, admin_password = _make_user(role="admin")
    with TestClient(app) as client:
        token = _login(client, admin_email, admin_password)
        headers = {"Authorization": f"Bearer {token}"}

        client.post("/clients", headers=headers, json={"full_name": f"Activity Test {uuid.uuid4()}"})

        r = client.get("/admin/activity?limit=50", headers=headers)
        assert r.status_code == 200
        actions = {row["action"] for row in r.json()}
        assert "login" in actions
        assert "client.create" in actions


def test_activity_log_route_is_admin_only():
    email, password = _make_user(role="employee")
    with TestClient(app) as client:
        token = _login(client, email, password)
        r = client.get("/admin/activity", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403
