"""
Integration tests against a real Postgres container spun up per module.
Cover: field-encryption round trip on account_number/balance/card_number,
tampered ciphertext detection, transaction signature persistence, and the
hash-chained audit log.

Skipped automatically if Docker isn't reachable.
"""

import os
from contextlib import contextmanager
from dataclasses import replace

import pytest

from shared_security.audit_chain import verify_chain
from shared_security.canonical import canonical_json_bytes
from shared_security.field_crypto import DecryptionError, generate_field_key
from shared_security.tokens import generate_signing_keypair

from banking_service.application.caller import Caller
from banking_service.application.deps import BankingDeps
from banking_service.application.freeze_account import freeze_account
from banking_service.application.open_account import open_account
from banking_service.application.settings import BankingSettings
from banking_service.application.transfer import transfer
from banking_service.infrastructure.audit_log import PostgresAuditLog
from banking_service.infrastructure.clock import SystemClock
from banking_service.infrastructure.db import apply_schema, build_pool
from banking_service.infrastructure.repositories.accounts_repo import PostgresAccountRepository
from banking_service.infrastructure.repositories.transactions_repo import (
    PostgresTransactionRepository,
)

try:
    from testcontainers.postgres import PostgresContainer
except ImportError:
    PostgresContainer = None


@pytest.fixture(scope="module")
def pool():
    if PostgresContainer is None:
        pytest.skip("testcontainers not installed")
    try:
        container = PostgresContainer("postgres:16-alpine")
        container.start()
    except Exception as exc:
        pytest.skip(f"Docker not available for integration test: {exc}")
    try:
        url = container.get_connection_url()
        url = url.replace("postgresql+psycopg2://", "postgresql://")
        url = url.replace("postgresql+psycopg://", "postgresql://")
        p = build_pool(url, min_size=1, max_size=5)
        apply_schema(p)
        yield p
        p.close()
    finally:
        container.stop()


@pytest.fixture(scope="module")
def field_key() -> bytes:
    return generate_field_key()


@pytest.fixture(scope="module")
def settings() -> BankingSettings:
    _, auth_pub = generate_signing_keypair()
    tx_priv, tx_pub = generate_signing_keypair()
    return BankingSettings(
        auth_public_key=auth_pub,
        tx_signing_private_key=tx_priv,
        tx_signing_public_key=tx_pub,
    )


@pytest.fixture
def deps_scope(pool, settings, field_key):
    @contextmanager
    def _scope():
        with pool.connection() as main_conn, pool.connection() as audit_conn:
            audit_conn.autocommit = True
            with main_conn.transaction():
                yield BankingDeps(
                    accounts=PostgresAccountRepository(main_conn, field_key),
                    transactions=PostgresTransactionRepository(main_conn),
                    audit=PostgresAuditLog(audit_conn),
                    clock=SystemClock(),
                    settings=settings,
                )

    return _scope


def test_field_encryption_round_trip_across_transactions(deps_scope):
    alice = Caller(user_id=_uuid(), role="customer")
    with deps_scope() as deps:
        account = open_account(caller=alice, deps=deps)
        original_number = account.account_number

    with deps_scope() as deps:
        reloaded = deps.accounts.get(account.id)
    assert reloaded is not None
    assert reloaded.account_number == original_number
    assert reloaded.balance_minor == account.balance_minor
    assert reloaded.card_number == account.card_number


def test_sensitive_fields_are_ciphertext_on_disk(deps_scope, pool):
    alice = Caller(user_id=_uuid(), role="customer")
    with deps_scope() as deps:
        account = open_account(caller=alice, deps=deps)

    with pool.connection() as conn:
        row = conn.execute(
            "SELECT account_number, balance_minor, card_number FROM accounts WHERE id = %s",
            (account.id,),
        ).fetchone()
    for blob in row:
        blob = bytes(blob)
        # nonce prefix + AEAD ciphertext; not the plaintext strings
        assert account.account_number.encode() not in blob
        assert account.card_number.encode() not in blob
        assert b"0" != blob  # not the plaintext balance either
        assert len(blob) > 12  # nonce + tag at minimum


def test_tampered_ciphertext_fails_to_decrypt(deps_scope, pool, field_key):
    alice = Caller(user_id=_uuid(), role="customer")
    with deps_scope() as deps:
        account = open_account(caller=alice, deps=deps)

    with pool.connection() as conn:
        conn.execute(
            "UPDATE accounts SET account_number = %s WHERE id = %s",
            (os.urandom(64), account.id),
        )
        conn.commit()

    with deps_scope() as deps:
        with pytest.raises(DecryptionError):
            deps.accounts.get(account.id)

    # Remove the tampered row so later tests that scan the table (e.g.
    # get_by_account_number) don't blow up on decryption of the garbage.
    with pool.connection() as conn:
        conn.execute("DELETE FROM accounts WHERE id = %s", (account.id,))
        conn.commit()


def test_transfer_persists_signature_and_updates_balances(deps_scope):
    alice = Caller(user_id=_uuid(), role="customer")
    bob = Caller(user_id=_uuid(), role="customer")

    with deps_scope() as deps:
        src = open_account(caller=alice, deps=deps)
        dst = open_account(caller=bob, deps=deps)
        deps.accounts.update(replace(src, balance_minor=10_000))
        seeded_src = replace(src, balance_minor=10_000)

    with deps_scope() as deps:
        tx = transfer(
            from_account_id=seeded_src.id,
            to_account_number=dst.account_number,
            amount_minor=2_500,
            caller=alice,
            deps=deps,
        )

    with deps_scope() as deps:
        reloaded_src = deps.accounts.get(seeded_src.id)
        reloaded_dst = deps.accounts.get(dst.id)
        stored = deps.transactions.list_for_account(seeded_src.id)
    assert reloaded_src.balance_minor == 7_500
    assert reloaded_dst.balance_minor == dst.balance_minor + 2_500
    assert len(stored) == 1
    assert stored[0].signature == tx.signature


def test_audit_chain_valid_end_to_end(deps_scope, pool):
    alice = Caller(user_id=_uuid(), role="customer")
    bob = Caller(user_id=_uuid(), role="customer")
    admin = Caller(user_id=_uuid(), role="admin")

    with deps_scope() as deps:
        src = open_account(caller=alice, deps=deps)
        dst = open_account(caller=bob, deps=deps)
        deps.accounts.update(replace(src, balance_minor=5_000))

    with deps_scope() as deps:
        transfer(
            from_account_id=src.id,
            to_account_number=dst.account_number,
            amount_minor=1_000,
            caller=alice,
            deps=deps,
        )
    with deps_scope() as deps:
        freeze_account(account_id=dst.id, caller=admin, deps=deps)

    with pool.connection() as conn:
        rows = conn.execute("SELECT event, hash FROM audit_log ORDER BY id ASC").fetchall()

    chain = [(canonical_json_bytes(event), bytes(stored_hash)) for event, stored_hash in rows]
    assert verify_chain(chain)


def _uuid() -> str:
    from uuid import uuid4

    return str(uuid4())
