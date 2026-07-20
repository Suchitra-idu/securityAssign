from dataclasses import replace

import pytest

from banking_service.application.list_transactions import list_transactions
from banking_service.application.open_account import open_account
from banking_service.application.transfer import transfer
from banking_service.domain.errors import NotAccountOwner
from tests.conftest import credit


def test_owner_lists_own_transactions(bag, alice, bob):
    src = open_account(caller=alice, deps=bag.deps)
    credit(bag, src, 10_000)
    dst = open_account(caller=bob, deps=bag.deps)
    transfer(
        from_account_id=src.id,
        to_account_number=dst.account_number,
        amount_minor=1_000,
        caller=alice,
        deps=bag.deps,
    )
    listed = list_transactions(account_id=src.id, caller=alice, deps=bag.deps)
    assert len(listed) == 1
    tx, ok = listed[0]
    assert ok is True
    assert tx.from_account_id == src.id


def test_other_customer_cannot_list(bag, alice, bob):
    src = open_account(caller=alice, deps=bag.deps)
    credit(bag, src, 10_000)
    dst = open_account(caller=bob, deps=bag.deps)
    transfer(
        from_account_id=src.id,
        to_account_number=dst.account_number,
        amount_minor=1_000,
        caller=alice,
        deps=bag.deps,
    )
    with pytest.raises(NotAccountOwner):
        list_transactions(account_id=src.id, caller=bob, deps=bag.deps)


def test_tampered_stored_amount_reports_signature_invalid(bag, alice, bob, admin):
    src = open_account(caller=alice, deps=bag.deps)
    credit(bag, src, 10_000)
    dst = open_account(caller=bob, deps=bag.deps)
    tx = transfer(
        from_account_id=src.id,
        to_account_number=dst.account_number,
        amount_minor=1_000,
        caller=alice,
        deps=bag.deps,
    )
    tampered = replace(tx, amount_minor=999_999)
    bag.transactions.replace(tx, tampered)
    listed = list_transactions(account_id=src.id, caller=admin, deps=bag.deps)
    assert listed[0][1] is False
