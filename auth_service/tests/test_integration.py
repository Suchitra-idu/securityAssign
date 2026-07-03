from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from shared_security.tokens import generate_signing_keypair, verify_token

from auth_service.application.deps import AuthDeps
from auth_service.infrastructure.app import create_app
from auth_service.infrastructure.config import Config

from conftest import FakeAudit, FakeClock, FakeRefreshStore, FakeUserRepo


@pytest.fixture
def config():
    priv, pub = generate_signing_keypair()
    return Config(
        database_url="postgresql://unused",
        signing_private_key_pem=priv,
        signing_public_key_pem=pub,
    )


@pytest.fixture
def state():
    return {
        "users": FakeUserRepo(),
        "refresh_tokens": FakeRefreshStore(),
        "audit": FakeAudit(),
        "clock": FakeClock(),
    }


@pytest.fixture
def client(config, state):
    def deps_factory() -> Iterator[AuthDeps]:
        yield AuthDeps(
            users=state["users"],
            refresh_tokens=state["refresh_tokens"],
            audit=state["audit"],
            clock=state["clock"],
            settings=config.tokens(),
        )

    app = create_app(config, deps_factory=deps_factory)
    return TestClient(app)


def _register(client, username="alice", password="c0rrect-horse-battery"):
    return client.post("/register", json={"username": username, "password": password})


def _login(client, username="alice", password="c0rrect-horse-battery"):
    return client.post("/login", json={"username": username, "password": password})


def test_register_returns_201_with_customer_role(client):
    r = _register(client)
    assert r.status_code == 201
    body = r.json()
    assert body["username"] == "alice"
    assert body["role"] == "customer"
    assert body["user_id"]


def test_register_duplicate_returns_409(client):
    _register(client)
    r = _register(client)
    assert r.status_code == 409


def test_register_rejects_short_password(client):
    r = client.post("/register", json={"username": "alice", "password": "short"})
    assert r.status_code == 422


def test_register_rejects_bad_username(client):
    r = client.post(
        "/register", json={"username": "alice; drop table users;--", "password": "c0rrect-horse-battery"}
    )
    assert r.status_code == 422


def test_register_forbids_role_field_from_request(client):
    r = client.post(
        "/register",
        json={"username": "alice", "password": "c0rrect-horse-battery", "role": "admin"},
    )
    assert r.status_code == 422


def test_login_returns_tokens(client, config):
    _register(client)
    r = _login(client)
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "Bearer"
    claims = verify_token(body["access_token"], config.signing_public_key_pem)
    assert claims["role"] == "customer"


def test_login_wrong_password_returns_401(client):
    _register(client)
    r = client.post("/login", json={"username": "alice", "password": "wrong-wrong-wrong"})
    assert r.status_code == 401


def test_refresh_rotates_tokens(client, state):
    _register(client)
    tokens = _login(client).json()
    state["clock"].advance(1)
    r = client.post("/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200
    new_tokens = r.json()
    assert new_tokens["access_token"] != tokens["access_token"]
    assert new_tokens["refresh_token"] != tokens["refresh_token"]


def test_refresh_old_token_after_rotation_returns_401(client, state):
    _register(client)
    tokens = _login(client).json()
    state["clock"].advance(1)
    client.post("/refresh", json={"refresh_token": tokens["refresh_token"]})
    r = client.post("/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 401


def test_public_key_endpoint_returns_pem(client, config):
    r = client.get("/public-key")
    assert r.status_code == 200
    body = r.json()
    assert body["public_key"] == config.signing_public_key_pem
    assert body["algorithm"] == "EdDSA"


def test_health_endpoint(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
