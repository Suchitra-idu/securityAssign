from dataclasses import dataclass

from auth_service.application.ports import AuditLog, Clock, RefreshTokenStore, UserRepository
from auth_service.application.settings import TokenSettings


@dataclass(frozen=True)
class AuthDeps:
    users: UserRepository
    refresh_tokens: RefreshTokenStore
    audit: AuditLog
    clock: Clock
    settings: TokenSettings
