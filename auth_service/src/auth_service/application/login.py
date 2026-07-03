from shared_security.passwords import verify_password

from auth_service.application.audit import emit
from auth_service.application.deps import AuthDeps
from auth_service.application.tokens import TokenPair, mint_token_pair
from auth_service.domain.errors import InvalidCredentials


def login(*, username: str, password: str, deps: AuthDeps) -> TokenPair:
    user = deps.users.get_by_username(username)
    if user is None or not verify_password(password, user.password_hash):
        emit(deps, "login_failed", username=username)
        raise InvalidCredentials
    pair = mint_token_pair(user, deps)
    emit(deps, "login_success", user_id=user.id)
    return pair
