from psycopg import Connection

from banking_service.domain.transactions import Transaction


class PostgresTransactionRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def add(self, tx: Transaction) -> None:
        self._conn.execute(
            "INSERT INTO transactions "
            "(id, from_account_id, to_account_id, amount_minor, signed_at, signature) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (
                tx.id,
                tx.from_account_id,
                tx.to_account_id,
                tx.amount_minor,
                tx.at,
                tx.signature,
            ),
        )

    def list_for_account(self, account_id: str) -> list[Transaction]:
        rows = self._conn.execute(
            "SELECT id, from_account_id, to_account_id, amount_minor, signed_at, signature "
            "FROM transactions "
            "WHERE from_account_id = %s OR to_account_id = %s "
            "ORDER BY signed_at ASC",
            (account_id, account_id),
        ).fetchall()
        return [_to_tx(r) for r in rows]

    def list_all(self) -> list[Transaction]:
        rows = self._conn.execute(
            "SELECT id, from_account_id, to_account_id, amount_minor, signed_at, signature "
            "FROM transactions ORDER BY signed_at ASC"
        ).fetchall()
        return [_to_tx(r) for r in rows]


def _to_tx(row) -> Transaction:
    return Transaction(
        id=str(row[0]),
        from_account_id=str(row[1]),
        to_account_id=str(row[2]),
        amount_minor=row[3],
        at=row[4],
        signature=bytes(row[5]),
    )
