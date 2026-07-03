from auth_service.application.audit import emit
from auth_service.application.deps import AuthDeps
from auth_service.application.tokens import TokenPair, hash_refresh_token, mint_token_pair
from auth_service.domain.errors import InvalidRefreshToken


def refresh(*, token: str, deps: AuthDeps) -> TokenPair:
    token_hash = hash_refresh_token(token)
    record = deps.refresh_tokens.get(token_hash)
    if record is None or record.expires_at <= deps.clock.now():
        emit(deps, "refresh_failed")
        raise InvalidRefreshToken
    user = deps.users.get_by_id(record.user_id)
    if user is None:
        emit(deps, "refresh_failed")
        raise InvalidRefreshToken
    deps.refresh_tokens.remove(token_hash)
    pair = mint_token_pair(user, deps)
    emit(deps, "refresh_success", user_id=user.id)
    return pair
