from uuid import uuid4

from banking_service.application.audit import emit
from banking_service.application.caller import Caller
from banking_service.application.deps import BankingDeps
from banking_service.application.numbers import generate_account_number, generate_card_number
from banking_service.domain.accounts import Account

# Every new account is seeded with a demo starting balance so a customer
# can immediately try a transfer end-to-end. In a real bank this would be
# an admin-triggered "credit" flow; the demo has no funding endpoint.
NEW_ACCOUNT_STARTING_BALANCE_MINOR = 100_00


def open_account(*, caller: Caller, deps: BankingDeps) -> Account:
    account = Account(
        id=str(uuid4()),
        owner_id=caller.user_id,
        account_number=generate_account_number(),
        balance_minor=NEW_ACCOUNT_STARTING_BALANCE_MINOR,
        card_number=generate_card_number(),
        status="active",
    )
    deps.accounts.add(account)
    emit(deps, "account_opened", account_id=account.id, owner_id=account.owner_id)
    return account
