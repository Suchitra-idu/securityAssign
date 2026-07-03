import pytest

from shared_security.tokens import verify_token

from auth_service.application.login import login
from auth_service.application.refresh import refresh
from auth_service.domain.errors import InvalidRefreshToken


def _login(bag):
    return login(username="alice", password="c0rrect-horse-battery", deps=bag.deps)


def test_refresh_rotates_and_issues_new_pair(bag, registered_customer):
    pair = _login(bag)
    bag.clock.advance(1)
    new_pair = refresh(token=pair.refresh, deps=bag.deps)
    assert new_pair.access != pair.access
    assert new_pair.refresh != pair.refresh
    assert bag.refresh_tokens.count() == 1


def test_refresh_old_token_rejected_after_rotation(bag, registered_customer):
    pair = _login(bag)
    refresh(token=pair.refresh, deps=bag.deps)
    with pytest.raises(InvalidRefreshToken):
        refresh(token=pair.refresh, deps=bag.deps)


def test_refresh_expired_token_rejected(bag, registered_customer):
    pair = _login(bag)
    bag.clock.advance(bag.settings.refresh_ttl + 1)
    with pytest.raises(InvalidRefreshToken):
        refresh(token=pair.refresh, deps=bag.deps)


def test_refresh_unknown_token_rejected(bag):
    with pytest.raises(InvalidRefreshToken):
        refresh(token="not-a-real-token-not-a-real-token", deps=bag.deps)


def test_refresh_preserves_subject_and_role(bag, registered_admin):
    pair = login(username="root", password="hunter2-hunter2", deps=bag.deps)
    new_pair = refresh(token=pair.refresh, deps=bag.deps)
    claims = verify_token(new_pair.access, bag.settings.public_key)
    assert claims["sub"] == registered_admin.id
    assert claims["role"] == "admin"


def test_refresh_success_writes_audit_event(bag, registered_customer):
    pair = _login(bag)
    refresh(token=pair.refresh, deps=bag.deps)
    events = [e for e in bag.audit.events if e["event"] == "refresh_success"]
    assert len(events) == 1
    assert events[0]["user_id"] == registered_customer.id


def test_refresh_failure_writes_audit_event(bag):
    with pytest.raises(InvalidRefreshToken):
        refresh(token="bogus-token-bogus-token-bogus-tok", deps=bag.deps)
    failures = [e for e in bag.audit.events if e["event"] == "refresh_failed"]
    assert len(failures) == 1


def test_refresh_reused_token_never_leaks_new_pair(bag, registered_customer):
    pair = _login(bag)
    refresh(token=pair.refresh, deps=bag.deps)
    before = bag.refresh_tokens.count()
    with pytest.raises(InvalidRefreshToken):
        refresh(token=pair.refresh, deps=bag.deps)
    assert bag.refresh_tokens.count() == before
