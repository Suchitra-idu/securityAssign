from banking_service.application.deps import BankingDeps


def emit(deps: BankingDeps, event: str, **fields) -> None:
    deps.audit.record({"event": event, "at": deps.clock.now(), **fields})
