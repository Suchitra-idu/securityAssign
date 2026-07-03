import time
from dataclasses import dataclass

import pytest

from shared_security.tokens import generate_signing_keypair

from auth_service.application.deps import AuthDeps
from auth_service.application.register import register
from auth_service.application.settings import TokenSettings
from auth_service.domain.refresh import RefreshRecord


class FakeUserRepo:
    def __init__(self) -> None:
        self._by_username: dict = {}
        self._by_id: dict = {}

    def get_by_username(self, username):
        return self._by_username.get(username)

    def get_by_id(self, user_id):
        return self._by_id.get(user_id)

    def add(self, user) -> None:
        self._by_username[user.username] = user
        self._by_id[user.id] = user


class FakeRefreshStore:
    def __init__(self) -> None:
        self._records: dict[str, RefreshRecord] = {}

    def add(self, record: RefreshRecord) -> None:
        self._records[record.token_hash] = record

    def get(self, token_hash: str):
        return self._records.get(token_hash)

    def remove(self, token_hash: str) -> None:
        self._records.pop(token_hash, None)

    def count(self) -> int:
        return len(self._records)

    def contains_plaintext(self, token: str) -> bool:
        return token in self._records


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def record(self, event: dict) -> None:
        self.events.append(event)


class FakeClock:
    def __init__(self, now: int | None = None) -> None:
        self._now = int(time.time()) if now is None else now

    def now(self) -> int:
        return self._now

    def advance(self, seconds: int) -> None:
        self._now += seconds


@dataclass
class Bag:
    deps: AuthDeps
    users: FakeUserRepo
    refresh_tokens: FakeRefreshStore
    audit: FakeAudit
    clock: FakeClock
    settings: TokenSettings


@pytest.fixture
def bag() -> Bag:
    priv, pub = generate_signing_keypair()
    settings = TokenSettings(
        private_key=priv,
        public_key=pub,
        access_ttl=300,
        refresh_ttl=86_400,
    )
    users = FakeUserRepo()
    refresh_tokens = FakeRefreshStore()
    audit = FakeAudit()
    clock = FakeClock()
    deps = AuthDeps(
        users=users,
        refresh_tokens=refresh_tokens,
        audit=audit,
        clock=clock,
        settings=settings,
    )
    return Bag(deps, users, refresh_tokens, audit, clock, settings)


@pytest.fixture
def registered_customer(bag):
    return register(
        username="alice",
        password="c0rrect-horse-battery",
        role="customer",
        deps=bag.deps,
    )


@pytest.fixture
def registered_admin(bag):
    return register(
        username="root",
        password="hunter2-hunter2",
        role="admin",
        deps=bag.deps,
    )
