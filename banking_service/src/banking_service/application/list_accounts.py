from banking_service.application.authz import require_admin
from banking_service.application.caller import Caller
from banking_service.application.deps import BankingDeps
from banking_service.domain.accounts import Account


def list_all_accounts(*, caller: Caller, deps: BankingDeps) -> list[Account]:
    require_admin(caller)
    return deps.accounts.list_all()
