import pytest

from banking_service.application.freeze_account import freeze_account
from banking_service.application.open_account import open_account
from banking_service.application.transfer import transfer
from banking_service.application.unfreeze_account import unfreeze_account
from banking_service.domain.errors import AccountNotFound, Forbidden
from tests.conftest import credit


def test_admin_can_unfreeze_frozen_account(bag, alice, admin):
    account = open_account(caller=alice, deps=bag.deps)
    freeze_account(account_id=account.id, caller=admin, deps=bag.deps)
    active = unfreeze_account(account_id=account.id, caller=admin, deps=bag.deps)
    assert active.status == "active"
    assert bag.accounts.get(account.id).status == "active"


def test_customer_cannot_unfreeze_account(bag, alice, admin):
    account = open_account(caller=alice, deps=bag.deps)
    freeze_account(account_id=account.id, caller=admin, deps=bag.deps)
    with pytest.raises(Forbidden):
        unfreeze_account(account_id=account.id, caller=alice, deps=bag.deps)
    assert bag.accounts.get(account.id).status == "frozen"


def test_unfreeze_missing_account_raises(bag, admin):
    with pytest.raises(AccountNotFound):
        unfreeze_account(account_id="nope", caller=admin, deps=bag.deps)


def test_unfreeze_is_idempotent_on_active_account(bag, alice, admin):
    account = open_account(caller=alice, deps=bag.deps)
    # Never frozen — call twice; neither should audit an event.
    unfreeze_account(account_id=account.id, caller=admin, deps=bag.deps)
    unfreeze_account(account_id=account.id, caller=admin, deps=bag.deps)
    events = [e for e in bag.audit.events if e["event"] == "account_unfrozen"]
    assert events == []


def test_unfreeze_emits_single_audit_event(bag, alice, admin):
    account = open_account(caller=alice, deps=bag.deps)
    freeze_account(account_id=account.id, caller=admin, deps=bag.deps)
    unfreeze_account(account_id=account.id, caller=admin, deps=bag.deps)
    events = [e for e in bag.audit.events if e["event"] == "account_unfrozen"]
    assert len(events) == 1
    assert events[0]["account_id"] == account.id
    assert events[0]["actor_user_id"] == admin.user_id


def test_unfrozen_account_can_transfer_again(bag, alice, bob, admin):
    src = open_account(caller=alice, deps=bag.deps)
    credit(bag, src, 1_000)
    dst = open_account(caller=bob, deps=bag.deps)
    freeze_account(account_id=src.id, caller=admin, deps=bag.deps)
    unfreeze_account(account_id=src.id, caller=admin, deps=bag.deps)
    tx = transfer(
        from_account_id=src.id,
        to_account_number=dst.account_number,
        amount_minor=100,
        caller=alice,
        deps=bag.deps,
    )
    assert tx.amount_minor == 100
    assert bag.accounts.get(src.id).balance_minor == 900
