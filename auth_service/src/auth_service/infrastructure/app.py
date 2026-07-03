import logging
from collections.abc import Callable, Iterator

from fastapi import Depends, FastAPI, HTTPException, status

from auth_service.application.deps import AuthDeps
from auth_service.application.login import login
from auth_service.application.refresh import refresh
from auth_service.application.register import register
from auth_service.domain.errors import (
    InvalidCredentials,
    InvalidRefreshToken,
    UsernameTaken,
)
from auth_service.infrastructure.audit_log import PostgresAuditLog
from auth_service.infrastructure.clock import SystemClock
from auth_service.infrastructure.config import Config
from auth_service.infrastructure.db import apply_schema, build_pool
from auth_service.infrastructure.repositories.refresh_repo import PostgresRefreshTokenStore
from auth_service.infrastructure.repositories.users_repo import PostgresUserRepository
from auth_service.infrastructure.schemas import (
    LoginRequest,
    PublicKeyResponse,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)

logger = logging.getLogger("auth")

DepsFactory = Callable[[], Iterator[AuthDeps]]


def create_app(config: Config, deps_factory: DepsFactory | None = None) -> FastAPI:
    if deps_factory is None:
        pool = build_pool(
            config.database_url,
            min_size=config.pool_min_size,
            max_size=config.pool_max_size,
        )
        apply_schema(pool)

        def deps_factory() -> Iterator[AuthDeps]:
            with pool.connection() as main_conn, pool.connection() as audit_conn:
                audit_conn.autocommit = True
                with main_conn.transaction():
                    yield AuthDeps(
                        users=PostgresUserRepository(main_conn),
                        refresh_tokens=PostgresRefreshTokenStore(main_conn),
                        audit=PostgresAuditLog(audit_conn),
                        clock=SystemClock(),
                        settings=config.tokens(),
                    )

    app = FastAPI(title="Auth Service")

    @app.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
    def register_route(
        body: RegisterRequest, deps: AuthDeps = Depends(deps_factory)
    ) -> UserResponse:
        try:
            user = register(
                username=body.username, password=body.password, role="customer", deps=deps
            )
        except UsernameTaken:
            raise HTTPException(status.HTTP_409_CONFLICT, "username taken")
        logger.info("REGISTER user_id=%s username=%s", user.id, user.username)
        return UserResponse(user_id=user.id, username=user.username, role=user.role)

    @app.post("/login", response_model=TokenResponse)
    def login_route(
        body: LoginRequest, deps: AuthDeps = Depends(deps_factory)
    ) -> TokenResponse:
        try:
            pair = login(username=body.username, password=body.password, deps=deps)
        except InvalidCredentials:
            logger.warning("LOGIN_FAILED username=%s", body.username)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
        logger.info("LOGIN_SUCCESS username=%s", body.username)
        return TokenResponse(access_token=pair.access, refresh_token=pair.refresh)

    @app.post("/refresh", response_model=TokenResponse)
    def refresh_route(
        body: RefreshRequest, deps: AuthDeps = Depends(deps_factory)
    ) -> TokenResponse:
        try:
            pair = refresh(token=body.refresh_token, deps=deps)
        except InvalidRefreshToken:
            logger.warning("REFRESH_FAILED")
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid refresh token")
        return TokenResponse(access_token=pair.access, refresh_token=pair.refresh)

    @app.get("/public-key", response_model=PublicKeyResponse)
    def public_key_route() -> PublicKeyResponse:
        return PublicKeyResponse(public_key=config.signing_public_key_pem)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    return app
