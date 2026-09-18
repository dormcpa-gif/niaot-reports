"""Unit tests for password hashing and admin bootstrap, against an
isolated in-memory SQLite DB (not the shared local dev DB the
TestClient-based route tests use) so bootstrap's "table is still empty"
check is actually meaningful here."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.auth import bootstrap_admin_if_needed, hash_password, verify_password
from app.db.models import Base, UserORM


def _fresh_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_hash_password_does_not_store_the_plaintext():
    h = hash_password("correct horse battery staple")
    assert h != "correct horse battery staple"
    assert h.startswith("$2b$")


def test_verify_password_accepts_the_right_password_and_rejects_others():
    h = hash_password("s3cret!")
    assert verify_password("s3cret!", h) is True
    assert verify_password("wrong", h) is False


def test_verify_password_returns_false_on_malformed_hash_instead_of_raising():
    assert verify_password("anything", "not-a-real-bcrypt-hash") is False


def test_bootstrap_creates_the_first_admin_from_env_vars(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", "boss@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "initial-pass")
    db = _fresh_session()

    bootstrap_admin_if_needed(db)

    users = db.query(UserORM).all()
    assert len(users) == 1
    assert users[0].email == "boss@example.com"
    assert users[0].role == "admin"
    assert verify_password("initial-pass", users[0].password_hash)


def test_bootstrap_does_nothing_without_env_vars(monkeypatch):
    monkeypatch.delenv("ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    db = _fresh_session()

    bootstrap_admin_if_needed(db)

    assert db.query(UserORM).count() == 0


def test_bootstrap_does_nothing_if_a_user_already_exists(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", "new-admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "whatever")
    db = _fresh_session()
    db.add(UserORM(email="existing@example.com", password_hash=hash_password("x"), full_name="Existing", role="employee"))
    db.commit()

    bootstrap_admin_if_needed(db)

    emails = {u.email for u in db.query(UserORM).all()}
    assert emails == {"existing@example.com"}
