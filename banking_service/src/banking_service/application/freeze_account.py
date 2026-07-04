from dataclasses import replace

from banking_service.application.audit import emit
from banking_service.application.authz import require_admin
from banking_service.application.caller import Caller
from banking_service.application.deps import BankingDeps
from banking_service.domain.accounts import Account
from banking_service.domain.errors import AccountNotFound


def freeze_account(*, account_id: str, caller: Caller, deps: BankingDeps) -> Account:
    require_admin(caller)
    account = deps.accounts.get(account_id)
    if account is None:
        raise AccountNotFound
    if account.status == "frozen":
        return account
    frozen = replace(account, status="frozen")
    deps.accounts.update(frozen)
    emit(deps, "account_frozen", account_id=account.id, actor_user_id=caller.user_id)
    return frozen
