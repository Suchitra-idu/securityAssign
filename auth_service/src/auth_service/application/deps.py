from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field

from auth_service.application.ports import AuditLog, Clock, RefreshTokenStore, UserRepository
from auth_service.application.settings import TokenSettings


@dataclass(frozen=True)
class AuthDeps:
    users: UserRepository
    refresh_tokens: RefreshTokenStore
    audit: AuditLog
    clock: Clock
    settings: TokenSettings
    # Transaction boundary the caller wraps mutating work in. In production
    # this is `psycopg.Connection.transaction` so the DB commit happens
    # before the HTTP response is sent — otherwise FastAPI's yield-dep
    # teardown commits after the response, and a client that fires the
    # next request quickly (e.g. auto-login right after register) can hit
    # the DB before the previous write is visible. Defaults to a no-op
    # for in-memory test fakes that need no transaction management.
    transaction: Callable[[], AbstractContextManager[None]] = field(
        default_factory=lambda: nullcontext
    )
