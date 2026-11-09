"""Tests for auth endpoints and JWT middleware."""

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """TestClient with test env vars and in-memory DB."""
    with patch.dict(os.environ, {
        "APP_PASSWORD": "testpass123",
        "JWT_SECRET": "test-secret-key",
        "DATABASE_URL": "sqlite://",
    }):
        from backend.main import create_app
        app = create_app()
        yield TestClient(app)


# --- Auth ---


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_login_success(client):
    resp = client.post("/auth/login", json={"username": "alice", "password": "testpass123"})
    assert resp.status_code == 200
    assert "session" in resp.cookies
    assert resp.json()["username"] == "alice"


def test_login_wrong_password(client):
    resp = client.post("/auth/login", json={"username": "alice", "password": "wrong"})
    assert resp.status_code == 401


def test_auth_me(client):
    client.post("/auth/login", json={"username": "alice", "password": "testpass123"})
    resp = client.get("/auth/me")
    assert resp.status_code == 200
    assert resp.json()["name"] == "alice"
    assert "id" in resp.json()


def test_auth_me_unauthenticated(client):
    resp = client.get("/auth/me")
    assert resp.status_code == 401


def test_logout(client):
    client.post("/auth/login", json={"username": "alice", "password": "testpass123"})
    resp = client.get("/auth/logout")
    assert resp.status_code == 200


def test_protected_route_without_auth(client):
    resp = client.get("/topics")
    assert resp.status_code == 401


def test_protected_route_with_auth(client):
    client.post("/auth/login", json={"username": "alice", "password": "testpass123"})
    resp = client.get("/topics")
    assert resp.status_code == 200


def test_login_creates_user(client):
    """First login should auto-create the user."""
    resp = client.post("/auth/login", json={"username": "newuser", "password": "testpass123"})
    assert resp.status_code == 200
    assert resp.json()["user_id"] >= 1


def test_login_finds_existing_user(client):
    """Second login with same username should find the existing user."""
    resp1 = client.post("/auth/login", json={"username": "bob", "password": "testpass123"})
    resp2 = client.post("/auth/login", json={"username": "bob", "password": "testpass123"})
    assert resp1.json()["user_id"] == resp2.json()["user_id"]
