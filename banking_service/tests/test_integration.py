import time

import pytest
from fastapi.testclient import TestClient

from shared_security.tokens import sign_token

from banking_service.application.deps import BankingDeps
from banking_service.infrastructure.app import create_app
from banking_service.infrastructure.clock import SystemClock


class _StubConfig:
    def __init__(self, settings):
        self._settings = settings

    def banking_settings(self):
        return self._settings


@pytest.fixture
def client(bag):
    def deps_factory():
        yield BankingDeps(
            accounts=bag.accounts,
            transactions=bag.transactions,
            audit=bag.audit,
            clock=SystemClock(),
            settings=bag.settings,
        )

    app = create_app(_StubConfig(bag.settings), deps_factory=deps_factory)
    return TestClient(app)


def _token(bag, *, sub: str, role: str, ttl: int = 300) -> str:
    now = int(time.time())
    return sign_token(
        {"sub": sub, "role": role, "iat": now, "exp": now + ttl},
        bag.auth_private_key,
    )


def _auth(bag, *, sub: str, role: str) -> dict:
    return {"Authorization": f"Bearer {_token(bag, sub=sub, role=role)}"}


def test_missing_bearer_returns_401(client):
    r = client.post("/accounts")
    assert r.status_code == 401


def test_malformed_bearer_returns_401(client):
    r = client.post("/accounts", headers={"Authorization": "Basic abc"})
    assert r.status_code == 401


def test_tampered_token_returns_401(client, bag):
    good = _token(bag, sub="user-alice", role="customer")
    tampered = good[:-4] + "AAAA"
    r = client.post("/accounts", headers={"Authorization": f"Bearer {tampered}"})
    assert r.status_code == 401


def test_expired_token_returns_401(client, bag):
    tok = _token(bag, sub="user-alice", role="customer", ttl=-10)
    r = client.post("/accounts", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401


def test_open_and_read_own_account_over_http(client, bag):
    headers = _auth(bag, sub="user-alice", role="customer")
    created = client.post("/accounts", headers=headers).json()
    assert created["owner_id"] == "user-alice"
    got = client.get(f"/accounts/{created['id']}", headers=headers).json()
    assert got["id"] == created["id"]


def test_customer_cannot_read_other_account(client, bag):
    alice = _auth(bag, sub="user-alice", role="customer")
    bob = _auth(bag, sub="user-bob", role="customer")
    created = client.post("/accounts", headers=alice).json()
    r = client.get(f"/accounts/{created['id']}", headers=bob)
    assert r.status_code == 403


def test_customer_forbidden_from_admin_list(client, bag):
    alice = _auth(bag, sub="user-alice", role="customer")
    r = client.get("/accounts", headers=alice)
    assert r.status_code == 403


def test_admin_can_list_all(client, bag):
    alice = _auth(bag, sub="user-alice", role="customer")
    admin = _auth(bag, sub="user-admin", role="admin")
    client.post("/accounts", headers=alice)
    r = client.get("/accounts", headers=admin)
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_transfer_flow(client, bag):
    alice = _auth(bag, sub="user-alice", role="customer")
    bob = _auth(bag, sub="user-bob", role="customer")
    admin = _auth(bag, sub="user-admin", role="admin")

    src = client.post("/accounts", headers=alice).json()
    dst = client.post("/accounts", headers=bob).json()

    # seed balance via admin: freeze isn't a credit, so we cheat via the fake
    from dataclasses import replace
    account = bag.accounts.get(src["id"])
    bag.accounts.update(replace(account, balance_minor=10_000))

    r = client.post(
        "/transfers",
        headers=alice,
        json={"from_account_id": src["id"], "to_account_id": dst["id"], "amount_minor": 2_500},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["signature_valid"] is True
    assert body["amount_minor"] == 2_500

    listed = client.get(f"/transactions/{src['id']}", headers=alice).json()
    assert len(listed) == 1
    assert listed[0]["signature_valid"] is True

    # admin can freeze
    fr = client.post(f"/accounts/{dst['id']}/freeze", headers=admin)
    assert fr.status_code == 200
    assert fr.json()["status"] == "frozen"

    # customer cannot freeze
    fr2 = client.post(f"/accounts/{src['id']}/freeze", headers=alice)
    assert fr2.status_code == 403

    # transfer to frozen destination now blocked
    blocked = client.post(
        "/transfers",
        headers=alice,
        json={"from_account_id": src["id"], "to_account_id": dst["id"], "amount_minor": 100},
    )
    assert blocked.status_code == 409
