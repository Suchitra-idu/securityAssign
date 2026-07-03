from psycopg import Connection

from auth_service.domain.refresh import RefreshRecord


class PostgresRefreshTokenStore:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def add(self, record: RefreshRecord) -> None:
        self._conn.execute(
            "INSERT INTO refresh_tokens (token_hash, user_id, expires_at) VALUES (%s, %s, %s)",
            (record.token_hash, record.user_id, record.expires_at),
        )

    def get(self, token_hash: str) -> RefreshRecord | None:
        row = self._conn.execute(
            "SELECT token_hash, user_id, expires_at FROM refresh_tokens WHERE token_hash = %s",
            (token_hash,),
        ).fetchone()
        if row is None:
            return None
        return RefreshRecord(token_hash=row[0], user_id=str(row[1]), expires_at=row[2])

    def remove(self, token_hash: str) -> None:
        self._conn.execute(
            "DELETE FROM refresh_tokens WHERE token_hash = %s", (token_hash,)
        )
