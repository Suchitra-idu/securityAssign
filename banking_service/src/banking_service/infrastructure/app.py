import logging
from collections.abc import Callable, Iterator

from fastapi import Depends, FastAPI, HTTPException, Request, status

from banking_service.application.caller import Caller
from banking_service.application.deps import BankingDeps
from banking_service.application.freeze_account import freeze_account
from banking_service.application.unfreeze_account import unfreeze_account
from banking_service.application.list_accounts import list_all_accounts
from banking_service.application.list_transactions import list_transactions
from banking_service.application.open_account import open_account
from banking_service.application.read_account import list_own_accounts, read_account
from banking_service.application.transfer import transfer
from banking_service.domain.accounts import Account
from banking_service.domain.errors import (
    AccountFrozen,
    AccountNotFound,
    Forbidden,
    InsufficientFunds,
    InvalidTransfer,
    NotAccountOwner,
)
from banking_service.domain.transactions import Transaction
from banking_service.infrastructure.audit_log import PostgresAuditLog
from banking_service.infrastructure.clock import SystemClock
from banking_service.infrastructure.config import Config
from banking_service.infrastructure.db import apply_schema, build_pool
from banking_service.infrastructure.repositories.accounts_repo import PostgresAccountRepository
from banking_service.infrastructure.repositories.transactions_repo import (
    PostgresTransactionRepository,
)
from banking_service.infrastructure.schemas import (
    AccountResponse,
    HealthResponse,
    TransactionResponse,
    TransferRequest,
)
from banking_service.infrastructure.token_verifier import bearer_caller

logger = logging.getLogger("banking")

DepsFactory = Callable[[], Iterator[BankingDeps]]


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-real-ip") or request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",", 1)[0].strip()
    return request.client.host if request.client else "-"


def create_app(config: Config, deps_factory: DepsFactory | None = None) -> FastAPI:
    banking_settings = config.banking_settings()
    caller_dep = bearer_caller(banking_settings.auth_public_key)

    if deps_factory is None:
        pool = build_pool(
            config.database_url,
            min_size=config.pool_min_size,
            max_size=config.pool_max_size,
        )
        apply_schema(pool)
        field_key = config.field_key()

        def deps_factory() -> Iterator[BankingDeps]:
            with pool.connection() as main_conn, pool.connection() as audit_conn:
                audit_conn.autocommit = True
                with main_conn.transaction():
                    yield BankingDeps(
                        accounts=PostgresAccountRepository(main_conn, field_key),
                        transactions=PostgresTransactionRepository(main_conn),
                        audit=PostgresAuditLog(audit_conn),
                        clock=SystemClock(),
                        settings=banking_settings,
                    )

    app = FastAPI(title="Banking Service")

    @app.post("/accounts", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
    def open_route(
        request: Request,
        caller: Caller = Depends(caller_dep),
        deps: BankingDeps = Depends(deps_factory),
    ) -> AccountResponse:
        account = open_account(caller=caller, deps=deps)
        logger.info(
            "ACCOUNT_OPENED ip=%s user_id=%s account_id=%s",
            _client_ip(request),
            caller.user_id,
            account.id,
        )
        return _account_response(account)

    @app.get("/accounts", response_model=list[AccountResponse])
    def list_route(
        caller: Caller = Depends(caller_dep),
        deps: BankingDeps = Depends(deps_factory),
    ) -> list[AccountResponse]:
        try:
            accounts = list_all_accounts(caller=caller, deps=deps)
        except Forbidden:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "admin only")
        return [_account_response(a) for a in accounts]

    @app.get("/accounts/me", response_model=list[AccountResponse])
    def list_own_route(
        caller: Caller = Depends(caller_dep),
        deps: BankingDeps = Depends(deps_factory),
    ) -> list[AccountResponse]:
        return [_account_response(a) for a in list_own_accounts(caller=caller, deps=deps)]

    @app.get("/accounts/{account_id}", response_model=AccountResponse)
    def read_route(
        account_id: str,
        caller: Caller = Depends(caller_dep),
        deps: BankingDeps = Depends(deps_factory),
    ) -> AccountResponse:
        try:
            account = read_account(account_id=account_id, caller=caller, deps=deps)
        except AccountNotFound:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "account not found")
        except NotAccountOwner:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "not the account owner")
        return _account_response(account)

    @app.post("/accounts/{account_id}/freeze", response_model=AccountResponse)
    def freeze_route(
        account_id: str,
        request: Request,
        caller: Caller = Depends(caller_dep),
        deps: BankingDeps = Depends(deps_factory),
    ) -> AccountResponse:
        try:
            account = freeze_account(account_id=account_id, caller=caller, deps=deps)
        except Forbidden:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "admin only")
        except AccountNotFound:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "account not found")
        logger.info(
            "ACCOUNT_FROZEN ip=%s actor=%s account_id=%s",
            _client_ip(request),
            caller.user_id,
            account.id,
        )
        return _account_response(account)

    @app.post("/accounts/{account_id}/unfreeze", response_model=AccountResponse)
    def unfreeze_route(
        account_id: str,
        request: Request,
        caller: Caller = Depends(caller_dep),
        deps: BankingDeps = Depends(deps_factory),
    ) -> AccountResponse:
        try:
            account = unfreeze_account(account_id=account_id, caller=caller, deps=deps)
        except Forbidden:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "admin only")
        except AccountNotFound:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "account not found")
        logger.info(
            "ACCOUNT_UNFROZEN ip=%s actor=%s account_id=%s",
            _client_ip(request),
            caller.user_id,
            account.id,
        )
        return _account_response(account)

    @app.post("/transfers", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED)
    def transfer_route(
        body: TransferRequest,
        request: Request,
        caller: Caller = Depends(caller_dep),
        deps: BankingDeps = Depends(deps_factory),
    ) -> TransactionResponse:
        try:
            tx = transfer(
                from_account_id=body.from_account_id,
                to_account_number=body.to_account_number,
                amount_minor=body.amount_minor,
                caller=caller,
                deps=deps,
            )
        except AccountNotFound:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "account not found")
        except NotAccountOwner:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "not the source account owner")
        except AccountFrozen:
            raise HTTPException(status.HTTP_409_CONFLICT, "account frozen")
        except InsufficientFunds:
            logger.warning(
                "TRANSFER_REJECTED ip=%s user_id=%s from=%s reason=insufficient_funds",
                _client_ip(request),
                caller.user_id,
                body.from_account_id,
            )
            raise HTTPException(status.HTTP_409_CONFLICT, "insufficient funds")
        except InvalidTransfer as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
        logger.info(
            "TRANSFER ip=%s user_id=%s tx_id=%s",
            _client_ip(request),
            caller.user_id,
            tx.id,
        )
        return _transaction_response(tx, signature_valid=True)

    @app.get("/transactions/{account_id}", response_model=list[TransactionResponse])
    def list_tx_route(
        account_id: str,
        caller: Caller = Depends(caller_dep),
        deps: BankingDeps = Depends(deps_factory),
    ) -> list[TransactionResponse]:
        try:
            entries = list_transactions(account_id=account_id, caller=caller, deps=deps)
        except AccountNotFound:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "account not found")
        except NotAccountOwner:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "not the account owner")
        return [_transaction_response(tx, signature_valid=ok) for tx, ok in entries]

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse()

    return app


def _account_response(account: Account) -> AccountResponse:
    return AccountResponse(
        id=account.id,
        owner_id=account.owner_id,
        account_number=account.account_number,
        balance_minor=account.balance_minor,
        card_number=account.card_number,
        status=account.status,
    )


def _transaction_response(tx: Transaction, *, signature_valid: bool) -> TransactionResponse:
    return TransactionResponse(
        id=tx.id,
        from_account_id=tx.from_account_id,
        to_account_id=tx.to_account_id,
        amount_minor=tx.amount_minor,
        at=tx.at,
        signature_hex=tx.signature.hex(),
        signature_valid=signature_valid,
    )
