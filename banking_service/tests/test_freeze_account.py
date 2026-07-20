import pytest

from banking_service.application.freeze_account import freeze_account
from banking_service.application.open_account import open_account
from banking_service.application.transfer import transfer
from banking_service.domain.errors import AccountFrozen, AccountNotFound, Forbidden
from tests.conftest import credit


def test_admin_can_freeze_account(bag, alice, admin):
    account = open_account(caller=alice, deps=bag.deps)
    frozen = freeze_account(account_id=account.id, caller=admin, deps=bag.deps)
    assert frozen.status == "frozen"
    assert bag.accounts.get(account.id).status == "frozen"


def test_customer_cannot_freeze_account(bag, alice):
    account = open_account(caller=alice, deps=bag.deps)
    with pytest.raises(Forbidden):
        freeze_account(account_id=account.id, caller=alice, deps=bag.deps)


def test_freeze_missing_account_raises(bag, admin):
    with pytest.raises(AccountNotFound):
        freeze_account(account_id="nope", caller=admin, deps=bag.deps)


def test_freeze_is_idempotent(bag, alice, admin):
    account = open_account(caller=alice, deps=bag.deps)
    freeze_account(account_id=account.id, caller=admin, deps=bag.deps)
    freeze_account(account_id=account.id, caller=admin, deps=bag.deps)
    events = [e for e in bag.audit.events if e["event"] == "account_frozen"]
    assert len(events) == 1


def test_frozen_source_blocks_transfer(bag, alice, bob, admin):
    src = open_account(caller=alice, deps=bag.deps)
    credit(bag, src, 1_000)
    dst = open_account(caller=bob, deps=bag.deps)
    freeze_account(account_id=src.id, caller=admin, deps=bag.deps)
    with pytest.raises(AccountFrozen):
        transfer(
            from_account_id=src.id,
            to_account_number=dst.account_number,
            amount_minor=100,
            caller=alice,
            deps=bag.deps,
        )


def test_frozen_destination_blocks_transfer(bag, alice, bob, admin):
    src = open_account(caller=alice, deps=bag.deps)
    credit(bag, src, 1_000)
    dst = open_account(caller=bob, deps=bag.deps)
    freeze_account(account_id=dst.id, caller=admin, deps=bag.deps)
    with pytest.raises(AccountFrozen):
        transfer(
            from_account_id=src.id,
            to_account_number=dst.account_number,
            amount_minor=100,
            caller=alice,
            deps=bag.deps,
        )
