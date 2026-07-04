from shared_security.transaction_signatures import verify_transaction

from banking_service.application.authz import require_owner_or_admin
from banking_service.application.caller import Caller
from banking_service.application.deps import BankingDeps
from banking_service.domain.errors import AccountNotFound
from banking_service.domain.transactions import Transaction, transaction_payload


def list_transactions(
    *, account_id: str, caller: Caller, deps: BankingDeps
) -> list[tuple[Transaction, bool]]:
    account = deps.accounts.get(account_id)
    if account is None:
        raise AccountNotFound
    require_owner_or_admin(caller, account)
    txs = deps.transactions.list_for_account(account_id)
    return [
        (tx, verify_transaction(transaction_payload(tx), tx.signature, deps.settings.tx_signing_public_key))
        for tx in txs
    ]
