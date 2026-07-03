import hashlib
import secrets
from dataclasses import dataclass

from shared_security.tokens import sign_token

from auth_service.application.deps import AuthDeps
from auth_service.domain.refresh import RefreshRecord
from auth_service.domain.users import User

_REFRESH_BYTES = 32


@dataclass(frozen=True)
class TokenPair:
    access: str
    refresh: str


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def mint_token_pair(user: User, deps: AuthDeps) -> TokenPair:
    now = deps.clock.now()
    access = sign_token(
        {
            "sub": user.id,
            "role": user.role,
            "iat": now,
            "exp": now + deps.settings.access_ttl,
        },
        deps.settings.private_key,
    )
    raw_refresh = secrets.token_urlsafe(_REFRESH_BYTES)
    deps.refresh_tokens.add(
        RefreshRecord(
            token_hash=hash_refresh_token(raw_refresh),
            user_id=user.id,
            expires_at=now + deps.settings.refresh_ttl,
        )
    )
    return TokenPair(access=access, refresh=raw_refresh)
