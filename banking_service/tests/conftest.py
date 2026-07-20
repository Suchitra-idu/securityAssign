import time
from dataclasses import dataclass, replace

import pytest

from shared_security.tokens import generate_signing_keypair

from banking_service.application.caller import Caller
from banking_service.application.deps import BankingDeps
from banking_service.application.settings import BankingSettings
from banking_service.domain.accounts import Account
from banking_service.domain.transactions import Transaction


class FakeAccountRepo:
    def __init__(self) -> None:
        self._by_id: dict[str, Account] = {}

    def get(self, account_id: str) -> Account | None:
        return self._by_id.get(account_id)

    def get_by_account_number(self, account_number: str) -> Account | None:
        return next((a for a in self._by_id.values() if a.account_number == account_number), None)

    def get_by_owner(self, owner_id: str) -> list[Account]:
        return [a for a in self._by_id.values() if a.owner_id == owner_id]

    def list_all(self) -> list[Account]:
        return list(self._by_id.values())

    def add(self, account: Account) -> None:
        self._by_id[account.id] = account

    def update(self, account: Account) -> None:
        self._by_id[account.id] = account


class FakeTransactionRepo:
    def __init__(self) -> None:
        self._records: list[Transaction] = []

    def add(self, tx: Transaction) -> None:
        self._records.append(tx)

    def list_for_account(self, account_id: str) -> list[Transaction]:
        return [
            t
            for t in self._records
            if t.from_account_id == account_id or t.to_account_id == account_id
        ]

    def list_all(self) -> list[Transaction]:
        return list(self._records)

    def replace(self, old: Transaction, new: Transaction) -> None:
        self._records = [new if r is old else r for r in self._records]


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
    deps: BankingDeps
    accounts: FakeAccountRepo
    transactions: FakeTransactionRepo
    audit: FakeAudit
    clock: FakeClock
    settings: BankingSettings
    auth_private_key: str


@pytest.fixture
def bag() -> Bag:
    auth_priv, auth_pub = generate_signing_keypair()
    tx_priv, tx_pub = generate_signing_keypair()
    settings = BankingSettings(
        auth_public_key=auth_pub,
        tx_signing_private_key=tx_priv,
        tx_signing_public_key=tx_pub,
    )
    accounts = FakeAccountRepo()
    transactions = FakeTransactionRepo()
    audit = FakeAudit()
    clock = FakeClock()
    deps = BankingDeps(
        accounts=accounts,
        transactions=transactions,
        audit=audit,
        clock=clock,
        settings=settings,
    )
    return Bag(deps, accounts, transactions, audit, clock, settings, auth_priv)


@pytest.fixture
def alice() -> Caller:
    return Caller(user_id="user-alice", role="customer")


@pytest.fixture
def bob() -> Caller:
    return Caller(user_id="user-bob", role="customer")


@pytest.fixture
def admin() -> Caller:
    return Caller(user_id="user-admin", role="admin")


def credit(bag: Bag, account: Account, amount_minor: int) -> Account:
    # Set (not add) — tests pass the exact starting balance they want and
    # should not have to know about the account-opening seed balance.
    updated = replace(account, balance_minor=amount_minor)
    bag.accounts.update(updated)
    return updated
