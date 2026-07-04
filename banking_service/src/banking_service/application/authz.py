from banking_service.application.caller import Caller
from banking_service.domain.accounts import Account
from banking_service.domain.errors import Forbidden, NotAccountOwner


def require_admin(caller: Caller) -> None:
    if caller.role != "admin":
        raise Forbidden


def require_owner_or_admin(caller: Caller, account: Account) -> None:
    if caller.role == "admin":
        return
    if account.owner_id != caller.user_id:
        raise NotAccountOwner
