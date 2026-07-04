from dataclasses import dataclass

from banking_service.application.ports import (
    AccountRepository,
    AuditLog,
    Clock,
    TransactionRepository,
)
from banking_service.application.settings import BankingSettings


@dataclass(frozen=True)
class BankingDeps:
    accounts: AccountRepository
    transactions: TransactionRepository
    audit: AuditLog
    clock: Clock
    settings: BankingSettings
