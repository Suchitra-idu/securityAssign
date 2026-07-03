from psycopg import Connection
from psycopg.errors import UniqueViolation

from auth_service.domain.errors import UsernameTaken
from auth_service.domain.users import User


class PostgresUserRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def get_by_username(self, username: str) -> User | None:
        row = self._conn.execute(
            "SELECT id, username, password_hash, role FROM users WHERE username = %s",
            (username,),
        ).fetchone()
        return _to_user(row)

    def get_by_id(self, user_id: str) -> User | None:
        row = self._conn.execute(
            "SELECT id, username, password_hash, role FROM users WHERE id = %s",
            (user_id,),
        ).fetchone()
        return _to_user(row)

    def add(self, user: User) -> None:
        try:
            self._conn.execute(
                "INSERT INTO users (id, username, password_hash, role) VALUES (%s, %s, %s, %s)",
                (user.id, user.username, user.password_hash, user.role),
            )
        except UniqueViolation as exc:
            raise UsernameTaken(user.username) from exc


def _to_user(row) -> User | None:
    if row is None:
        return None
    return User(id=str(row[0]), username=row[1], password_hash=row[2], role=row[3])
