import pytest

from shared_security.tokens import verify_token

from auth_service.application.login import login
from auth_service.domain.errors import InvalidCredentials


def test_login_success_returns_verifiable_access_token_with_role(bag, registered_customer):
    pair = login(username="alice", password="c0rrect-horse-battery", deps=bag.deps)
    claims = verify_token(pair.access, bag.settings.public_key)
    assert claims["sub"] == registered_customer.id
    assert claims["role"] == "customer"
    assert claims["iat"] == bag.clock.now()
    assert claims["exp"] == bag.clock.now() + bag.settings.access_ttl


def test_login_success_carries_admin_role(bag, registered_admin):
    pair = login(username="root", password="hunter2-hunter2", deps=bag.deps)
    claims = verify_token(pair.access, bag.settings.public_key)
    assert claims["role"] == "admin"


def test_login_wrong_password_rejected_and_no_refresh_token_stored(bag, registered_customer):
    with pytest.raises(InvalidCredentials):
        login(username="alice", password="not-the-password", deps=bag.deps)
    assert bag.refresh_tokens.count() == 0


def test_login_unknown_user_rejected(bag):
    with pytest.raises(InvalidCredentials):
        login(username="ghost", password="whatever-whatever", deps=bag.deps)
    assert bag.refresh_tokens.count() == 0


def test_login_refresh_token_is_opaque_not_stored_plaintext(bag, registered_customer):
    pair = login(username="alice", password="c0rrect-horse-battery", deps=bag.deps)
    assert "." not in pair.refresh  # not a JWT
    assert len(pair.refresh) >= 32
    assert not bag.refresh_tokens.contains_plaintext(pair.refresh)
    assert bag.refresh_tokens.count() == 1


def test_login_stored_refresh_record_expires_in_future(bag, registered_customer):
    login(username="alice", password="c0rrect-horse-battery", deps=bag.deps)
    record = next(iter(bag.refresh_tokens._records.values()))
    assert record.user_id == registered_customer.id
    assert record.expires_at == bag.clock.now() + bag.settings.refresh_ttl


def test_login_success_writes_audit_event(bag, registered_customer):
    login(username="alice", password="c0rrect-horse-battery", deps=bag.deps)
    events = [e for e in bag.audit.events if e["event"] == "login_success"]
    assert len(events) == 1
    assert events[0]["user_id"] == registered_customer.id
    assert events[0]["at"] == bag.clock.now()


def test_login_failure_writes_audit_event_without_leaking_password(bag, registered_customer):
    plaintext = "not-the-password"
    with pytest.raises(InvalidCredentials):
        login(username="alice", password=plaintext, deps=bag.deps)
    failures = [e for e in bag.audit.events if e["event"] == "login_failed"]
    assert len(failures) == 1
    assert failures[0]["username"] == "alice"
    for value in failures[0].values():
        assert plaintext not in str(value)


def test_login_failure_for_unknown_user_still_audited(bag):
    with pytest.raises(InvalidCredentials):
        login(username="ghost", password="whatever-whatever", deps=bag.deps)
    failures = [e for e in bag.audit.events if e["event"] == "login_failed"]
    assert len(failures) == 1
    assert failures[0]["username"] == "ghost"
