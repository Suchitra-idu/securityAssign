from uuid import uuid4

from shared_security.passwords import hash_password

from auth_service.application.audit import emit
from auth_service.application.deps import AuthDeps
from auth_service.domain.errors import UsernameTaken
from auth_service.domain.users import Role, User


def register(*, username: str, password: str, role: Role, deps: AuthDeps) -> User:
    if deps.users.get_by_username(username) is not None:
        raise UsernameTaken(username)
    user = User(
        id=str(uuid4()),
        username=username,
        password_hash=hash_password(password),
        role=role,
    )
    deps.users.add(user)
    emit(deps, "register", user_id=user.id, username=username)
    return user
