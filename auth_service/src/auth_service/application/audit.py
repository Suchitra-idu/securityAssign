from auth_service.application.deps import AuthDeps


def emit(deps: AuthDeps, event: str, **fields) -> None:
    deps.audit.record({"event": event, "at": deps.clock.now(), **fields})
