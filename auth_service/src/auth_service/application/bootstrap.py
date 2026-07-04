from auth_service.application.deps import AuthDeps
from auth_service.application.register import register


def ensure_admin(*, username: str, password: str, deps: AuthDeps) -> None:
    """
    Create the named admin if it does not already exist.

    Idempotent: safe to call on every process start. If the admin was
    deleted, next boot restores it. If someone changed the password
    after seeding, this does not overwrite the change.
    """
    if deps.users.get_by_username(username) is not None:
        return
    register(username=username, password=password, role="admin", deps=deps)
