from uuid import uuid4

from banking_service.application.audit import emit
from banking_service.application.caller import Caller
from banking_service.application.deps import BankingDeps
from banking_service.application.numbers import generate_account_number, generate_card_number
from banking_service.domain.accounts import Account


def open_account(*, caller: Caller, deps: BankingDeps) -> Account:
    account = Account(
        id=str(uuid4()),
        owner_id=caller.user_id,
        account_number=generate_account_number(),
        balance_minor=0,
        card_number=generate_card_number(),
        status="active",
    )
    deps.accounts.add(account)
    emit(deps, "account_opened", account_id=account.id, owner_id=account.owner_id)
    return account
