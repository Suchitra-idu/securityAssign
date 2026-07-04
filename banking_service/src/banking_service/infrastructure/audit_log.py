from psycopg import Connection
from psycopg.types.json import Jsonb

from shared_security.audit_chain import GENESIS_HASH, compute_chain_hash
from shared_security.canonical import canonical_json_bytes


class PostgresAuditLog:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def record(self, event: dict) -> None:
        with self._conn.transaction():
            self._conn.execute("LOCK TABLE audit_log IN SHARE ROW EXCLUSIVE MODE")
            row = self._conn.execute(
                "SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1"
            ).fetchone()
            prev_hash = bytes(row[0]) if row else GENESIS_HASH
            new_hash = compute_chain_hash(prev_hash, canonical_json_bytes(event))
            self._conn.execute(
                "INSERT INTO audit_log (event, prev_hash, hash) VALUES (%s, %s, %s)",
                (Jsonb(event), prev_hash, new_hash),
            )
