import pytest

from banking_service.application.open_account import open_account
from banking_service.application.read_account import list_own_accounts, read_account
from banking_service.domain.errors import AccountNotFound, NotAccountOwner


def test_customer_can_read_own_account(bag, alice):
    account = open_account(caller=alice, deps=bag.deps)
    got = read_account(account_id=account.id, caller=alice, deps=bag.deps)
    assert got.id == account.id


def test_customer_cannot_read_other_customer_account(bag, alice, bob):
    account = open_account(caller=alice, deps=bag.deps)
    with pytest.raises(NotAccountOwner):
        read_account(account_id=account.id, caller=bob, deps=bag.deps)


def test_admin_can_read_any_account(bag, alice, admin):
    account = open_account(caller=alice, deps=bag.deps)
    got = read_account(account_id=account.id, caller=admin, deps=bag.deps)
    assert got.id == account.id


def test_read_missing_account_raises(bag, admin):
    with pytest.raises(AccountNotFound):
        read_account(account_id="does-not-exist", caller=admin, deps=bag.deps)


def test_reads_are_audited_with_actor(bag, alice, admin):
    account = open_account(caller=alice, deps=bag.deps)
    read_account(account_id=account.id, caller=admin, deps=bag.deps)
    events = [e for e in bag.audit.events if e["event"] == "account_read"]
    assert len(events) == 1
    assert events[0]["actor_user_id"] == admin.user_id
    assert events[0]["actor_role"] == "admin"


def test_list_own_accounts_only_returns_owned(bag, alice, bob):
    a1 = open_account(caller=alice, deps=bag.deps)
    a2 = open_account(caller=alice, deps=bag.deps)
    open_account(caller=bob, deps=bag.deps)
    got = list_own_accounts(caller=alice, deps=bag.deps)
    assert {a.id for a in got} == {a1.id, a2.id}
