from banking_service.application.audit import emit
from banking_service.application.authz import require_owner_or_admin
from banking_service.application.caller import Caller
from banking_service.application.deps import BankingDeps
from banking_service.domain.accounts import Account
from banking_service.domain.errors import AccountNotFound


def read_account(*, account_id: str, caller: Caller, deps: BankingDeps) -> Account:
    account = deps.accounts.get(account_id)
    if account is None:
        raise AccountNotFound
    require_owner_or_admin(caller, account)
    emit(
        deps,
        "account_read",
        account_id=account.id,
        actor_user_id=caller.user_id,
        actor_role=caller.role,
    )
    return account


def list_own_accounts(*, caller: Caller, deps: BankingDeps) -> list[Account]:
    return deps.accounts.get_by_owner(caller.user_id)
