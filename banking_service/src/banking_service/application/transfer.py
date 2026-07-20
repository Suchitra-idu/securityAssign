from dataclasses import replace
from uuid import uuid4

from shared_security.transaction_signatures import sign_transaction

from banking_service.application.audit import emit
from banking_service.application.caller import Caller
from banking_service.application.deps import BankingDeps
from banking_service.domain.accounts import Account
from banking_service.domain.errors import (
    AccountFrozen,
    AccountNotFound,
    InsufficientFunds,
    InvalidTransfer,
    NotAccountOwner,
)
from banking_service.domain.transactions import Transaction, transaction_payload


def transfer(
    *,
    from_account_id: str,
    to_account_number: str,
    amount_minor: int,
    caller: Caller,
    deps: BankingDeps,
) -> Transaction:
    if amount_minor <= 0:
        raise InvalidTransfer("amount must be positive")

    source = _load(deps, from_account_id)
    destination = deps.accounts.get_by_account_number(to_account_number)
    if destination is None:
        raise AccountNotFound
    if source.id == destination.id:
        raise InvalidTransfer("cannot transfer to the same account")

    if caller.role != "admin" and source.owner_id != caller.user_id:
        raise NotAccountOwner
    if source.status == "frozen" or destination.status == "frozen":
        raise AccountFrozen
    if source.balance_minor < amount_minor:
        emit(
            deps,
            "transfer_rejected",
            actor_user_id=caller.user_id,
            from_account=source.id,
            reason="insufficient_funds",
        )
        raise InsufficientFunds

    now = deps.clock.now()
    tx_id = str(uuid4())
    unsigned = Transaction(
        id=tx_id,
        from_account_id=source.id,
        to_account_id=destination.id,
        amount_minor=amount_minor,
        at=now,
        signature=b"",
    )
    signature = sign_transaction(transaction_payload(unsigned), deps.settings.tx_signing_private_key)
    signed = replace(unsigned, signature=signature)

    deps.accounts.update(replace(source, balance_minor=source.balance_minor - amount_minor))
    deps.accounts.update(
        replace(destination, balance_minor=destination.balance_minor + amount_minor)
    )
    deps.transactions.add(signed)
    emit(
        deps,
        "transfer",
        actor_user_id=caller.user_id,
        tx_id=tx_id,
        from_account=source.id,
        to_account=destination.id,
        amount_minor=amount_minor,
    )
    return signed


def _load(deps: BankingDeps, account_id: str) -> Account:
    account = deps.accounts.get(account_id)
    if account is None:
        raise AccountNotFound
    return account
