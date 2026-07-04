from functools import cache

from shared_security.passwords import hash_password, verify_password

from auth_service.application.audit import emit
from auth_service.application.deps import AuthDeps
from auth_service.application.tokens import TokenPair, mint_token_pair
from auth_service.domain.errors import InvalidCredentials


@cache
def _dummy_hash() -> str:
    # Bcrypt-hashed placeholder consulted only when the requested username
    # is unknown. Spending the same ~100ms of bcrypt work makes
    # unknown-user and wrong-password branches indistinguishable by
    # response time, blocking user-enumeration timing attacks.
    return hash_password("dummy-passphrase-for-timing-parity")


def login(*, username: str, password: str, deps: AuthDeps) -> TokenPair:
    user = deps.users.get_by_username(username)
    if user is None:
        verify_password(password, _dummy_hash())
        emit(deps, "login_failed", username=username)
        raise InvalidCredentials
    if not verify_password(password, user.password_hash):
        emit(deps, "login_failed", username=username)
        raise InvalidCredentials
    pair = mint_token_pair(user, deps)
    emit(deps, "login_success", user_id=user.id)
    return pair
