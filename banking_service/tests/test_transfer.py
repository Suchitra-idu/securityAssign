from dataclasses import replace

import pytest

from shared_security.transaction_signatures import verify_transaction

from banking_service.application.open_account import open_account
from banking_service.application.transfer import transfer
from banking_service.domain.errors import (
    InsufficientFunds,
    InvalidTransfer,
    NotAccountOwner,
)
from banking_service.domain.transactions import transaction_payload
from tests.conftest import credit


def test_transfer_moves_balance(bag, alice, bob):
    src = open_account(caller=alice, deps=bag.deps)
    credit(bag, src, 10_000)
    dst = open_account(caller=bob, deps=bag.deps)
    dst_start = bag.accounts.get(dst.id).balance_minor

    transfer(
        from_account_id=src.id,
        to_account_number=dst.account_number,
        amount_minor=2_500,
        caller=alice,
        deps=bag.deps,
    )
    assert bag.accounts.get(src.id).balance_minor == 7_500
    assert bag.accounts.get(dst.id).balance_minor == dst_start + 2_500


def test_transfer_produces_verifiable_signature(bag, alice, bob):
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
    assert tx.signature != b""
    assert verify_transaction(
        transaction_payload(tx), tx.signature, bag.settings.tx_signing_public_key
    )


def test_tampered_transaction_signature_fails_verification(bag, alice, bob):
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
    assert not verify_transaction(
        transaction_payload(tampered), tx.signature, bag.settings.tx_signing_public_key
    )


def test_customer_cannot_transfer_from_someone_elses_account(bag, alice, bob):
    src = open_account(caller=alice, deps=bag.deps)
    credit(bag, src, 10_000)
    dst = open_account(caller=bob, deps=bag.deps)

    with pytest.raises(NotAccountOwner):
        transfer(
            from_account_id=src.id,
            to_account_number=dst.account_number,
            amount_minor=1_000,
            caller=bob,
            deps=bag.deps,
        )


def test_insufficient_funds_rejected_and_audited(bag, alice, bob):
    src = open_account(caller=alice, deps=bag.deps)
    credit(bag, src, 500)
    dst = open_account(caller=bob, deps=bag.deps)

    with pytest.raises(InsufficientFunds):
        transfer(
            from_account_id=src.id,
            to_account_number=dst.account_number,
            amount_minor=10_000,
            caller=alice,
            deps=bag.deps,
        )
    events = [e for e in bag.audit.events if e["event"] == "transfer_rejected"]
    assert len(events) == 1
    assert events[0]["reason"] == "insufficient_funds"
    # source balance untouched
    assert bag.accounts.get(src.id).balance_minor == 500


def test_zero_or_negative_amount_rejected(bag, alice, bob):
    src = open_account(caller=alice, deps=bag.deps)
    credit(bag, src, 10_000)
    dst = open_account(caller=bob, deps=bag.deps)
    for bad in (0, -1, -100):
        with pytest.raises(InvalidTransfer):
            transfer(
                from_account_id=src.id,
                to_account_number=dst.account_number,
                amount_minor=bad,
                caller=alice,
                deps=bag.deps,
            )


def test_self_transfer_rejected(bag, alice):
    src = open_account(caller=alice, deps=bag.deps)
    credit(bag, src, 10_000)
    with pytest.raises(InvalidTransfer):
        transfer(
            from_account_id=src.id,
            to_account_number=src.account_number,
            amount_minor=100,
            caller=alice,
            deps=bag.deps,
        )


def test_admin_can_transfer_from_any_account(bag, alice, bob, admin):
    src = open_account(caller=alice, deps=bag.deps)
    credit(bag, src, 10_000)
    dst = open_account(caller=bob, deps=bag.deps)

    tx = transfer(
        from_account_id=src.id,
        to_account_number=dst.account_number,
        amount_minor=1_000,
        caller=admin,
        deps=bag.deps,
    )
    assert tx.amount_minor == 1_000


def test_transfer_audited(bag, alice, bob):
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
    events = [e for e in bag.audit.events if e["event"] == "transfer"]
    assert len(events) == 1
    assert events[0]["tx_id"] == tx.id
    assert events[0]["actor_user_id"] == alice.user_id
