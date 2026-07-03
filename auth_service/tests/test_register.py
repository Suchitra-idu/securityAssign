import pytest

from shared_security.passwords import verify_password

from auth_service.application.register import register
from auth_service.domain.errors import UsernameTaken


def test_register_stores_hashed_password_not_plaintext(bag):
    plaintext = "c0rrect-horse-battery"
    user = register(username="alice", password=plaintext, role="customer", deps=bag.deps)
    stored = bag.users.get_by_username("alice")
    assert stored is user
    assert stored.password_hash != plaintext
    assert plaintext not in stored.password_hash
    assert verify_password(plaintext, stored.password_hash)


def test_register_records_role_verbatim(bag):
    user = register(username="root", password="pw-pw-pw-pw", role="admin", deps=bag.deps)
    assert user.role == "admin"
    assert bag.users.get_by_username("root").role == "admin"


def test_register_assigns_stable_user_id(bag):
    a = register(username="a", password="pw-pw-pw-pw", role="customer", deps=bag.deps)
    b = register(username="b", password="pw-pw-pw-pw", role="customer", deps=bag.deps)
    assert a.id and b.id and a.id != b.id


def test_register_rejects_duplicate_username(bag):
    register(username="alice", password="pw-pw-pw-pw", role="customer", deps=bag.deps)
    with pytest.raises(UsernameTaken):
        register(username="alice", password="different", role="customer", deps=bag.deps)


def test_register_writes_audit_event(bag):
    user = register(username="alice", password="pw-pw-pw-pw", role="customer", deps=bag.deps)
    events = [e for e in bag.audit.events if e["event"] == "register"]
    assert len(events) == 1
    assert events[0]["user_id"] == user.id
    assert events[0]["username"] == "alice"
    assert events[0]["at"] == bag.clock.now()


def test_register_audit_event_never_carries_password(bag):
    plaintext = "c0rrect-horse-battery"
    register(username="alice", password=plaintext, role="customer", deps=bag.deps)
    for event in bag.audit.events:
        for value in event.values():
            assert plaintext not in str(value)
