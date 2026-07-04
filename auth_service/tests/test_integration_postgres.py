"""
Integration tests exercising the real Postgres repositories and the
hash-chained audit sink against a Postgres container spun up per module.

Skipped automatically if Docker isn't reachable.
"""

import time
from contextlib import contextmanager

import pytest

from shared_security.audit_chain import verify_chain
from shared_security.canonical import canonical_json_bytes
from shared_security.tokens import generate_signing_keypair, verify_token

from auth_service.application.deps import AuthDeps
from auth_service.application.login import login
from auth_service.application.refresh import refresh
from auth_service.application.register import register
from auth_service.application.settings import TokenSettings
from auth_service.domain.errors import (
    InvalidCredentials,
    InvalidRefreshToken,
    UsernameTaken,
)
from auth_service.infrastructure.audit_log import PostgresAuditLog
from auth_service.infrastructure.clock import SystemClock
from auth_service.infrastructure.db import apply_schema, build_pool
from auth_service.infrastructure.repositories.refresh_repo import PostgresRefreshTokenStore
from auth_service.infrastructure.repositories.users_repo import PostgresUserRepository

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
    except Exception as exc:  # docker unreachable, image pull failure, etc.
        pytest.skip(f"Docker not available for integration test: {exc}")
    try:
        url = container.get_connection_url()
        # testcontainers hands back a SQLAlchemy-style URL. psycopg wants
        # the plain scheme.
        url = url.replace("postgresql+psycopg2://", "postgresql://")
        url = url.replace("postgresql+psycopg://", "postgresql://")
        p = build_pool(url, min_size=1, max_size=5)
        apply_schema(p)
        yield p
        p.close()
    finally:
        container.stop()


@pytest.fixture(scope="module")
def settings():
    priv, pub = generate_signing_keypair()
    return TokenSettings(private_key=priv, public_key=pub, access_ttl=300, refresh_ttl=86_400)


@pytest.fixture
def deps_scope(pool, settings):
    @contextmanager
    def _scope():
        with pool.connection() as main_conn, pool.connection() as audit_conn:
            audit_conn.autocommit = True
            with main_conn.transaction():
                yield AuthDeps(
                    users=PostgresUserRepository(main_conn),
                    refresh_tokens=PostgresRefreshTokenStore(main_conn),
                    audit=PostgresAuditLog(audit_conn),
                    clock=SystemClock(),
                    settings=settings,
                )

    return _scope


def test_full_flow_persists_across_transactions(deps_scope, settings):
    with deps_scope() as deps:
        user = register(
            username="itest_alice",
            password="c0rrect-horse-battery",
            role="customer",
            deps=deps,
        )

    with deps_scope() as deps:
        pair = login(username="itest_alice", password="c0rrect-horse-battery", deps=deps)
    claims = verify_token(pair.access, settings.public_key)
    assert claims["sub"] == user.id
    assert claims["role"] == "customer"

    time.sleep(1)  # advance real wall clock so refresh tokens differ

    with deps_scope() as deps:
        new_pair = refresh(token=pair.refresh, deps=deps)
    assert new_pair.refresh != pair.refresh

    with pytest.raises(InvalidRefreshToken):
        with deps_scope() as deps:
            refresh(token=pair.refresh, deps=deps)


def test_failed_login_audit_persists_when_main_txn_rolls_back(deps_scope, pool):
    with deps_scope() as deps:
        register(
            username="itest_bob",
            password="c0rrect-horse-battery",
            role="customer",
            deps=deps,
        )

    before = _count_audit(pool, event="login_failed")
    with pytest.raises(InvalidCredentials):
        with deps_scope() as deps:
            login(username="itest_bob", password="wrong-wrong-wrong", deps=deps)
    after = _count_audit(pool, event="login_failed")
    # Main transaction rolled back on the exception; the audit event
    # still landed via the autocommit audit connection.
    assert after == before + 1


def test_audit_chain_valid_end_to_end(deps_scope, pool):
    with deps_scope() as deps:
        register(
            username="itest_carol",
            password="c0rrect-horse-battery",
            role="customer",
            deps=deps,
        )
    with deps_scope() as deps:
        login(username="itest_carol", password="c0rrect-horse-battery", deps=deps)
    with pytest.raises(InvalidCredentials):
        with deps_scope() as deps:
            login(username="itest_carol", password="wrong-wrong-wrong", deps=deps)

    with pool.connection() as conn:
        rows = conn.execute("SELECT event, hash FROM audit_log ORDER BY id ASC").fetchall()

    chain = [(canonical_json_bytes(event), bytes(stored_hash)) for event, stored_hash in rows]
    assert verify_chain(chain)


def test_unique_username_race_translates_to_domain_error(deps_scope):
    with deps_scope() as deps:
        register(
            username="itest_dup",
            password="c0rrect-horse-battery",
            role="customer",
            deps=deps,
        )
    with pytest.raises(UsernameTaken):
        with deps_scope() as deps:
            register(
                username="itest_dup",
                password="c0rrect-horse-battery",
                role="customer",
                deps=deps,
            )


def _count_audit(pool, *, event: str) -> int:
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT count(*) FROM audit_log WHERE event->>'event' = %s", (event,)
        ).fetchone()
    return row[0]
