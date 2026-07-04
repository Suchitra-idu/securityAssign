from psycopg import Connection

from shared_security.field_crypto import decrypt_field, encrypt_field

from banking_service.domain.accounts import Account


class PostgresAccountRepository:
    def __init__(self, conn: Connection, field_key: bytes) -> None:
        self._conn = conn
        self._key = field_key

    def get(self, account_id: str) -> Account | None:
        row = self._conn.execute(
            "SELECT id, owner_id, account_number, balance_minor, card_number, status "
            "FROM accounts WHERE id = %s",
            (account_id,),
        ).fetchone()
        return self._to_account(row)

    def get_by_owner(self, owner_id: str) -> list[Account]:
        rows = self._conn.execute(
            "SELECT id, owner_id, account_number, balance_minor, card_number, status "
            "FROM accounts WHERE owner_id = %s ORDER BY created_at ASC",
            (owner_id,),
        ).fetchall()
        return [self._to_account(r) for r in rows]

    def list_all(self) -> list[Account]:
        rows = self._conn.execute(
            "SELECT id, owner_id, account_number, balance_minor, card_number, status "
            "FROM accounts ORDER BY created_at ASC"
        ).fetchall()
        return [self._to_account(r) for r in rows]

    def add(self, account: Account) -> None:
        self._conn.execute(
            "INSERT INTO accounts "
            "(id, owner_id, account_number, balance_minor, card_number, status) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (
                account.id,
                account.owner_id,
                encrypt_field(account.account_number.encode("utf-8"), self._key),
                encrypt_field(str(account.balance_minor).encode("utf-8"), self._key),
                encrypt_field(account.card_number.encode("utf-8"), self._key),
                account.status,
            ),
        )

    def update(self, account: Account) -> None:
        self._conn.execute(
            "UPDATE accounts SET "
            "account_number = %s, balance_minor = %s, card_number = %s, status = %s "
            "WHERE id = %s",
            (
                encrypt_field(account.account_number.encode("utf-8"), self._key),
                encrypt_field(str(account.balance_minor).encode("utf-8"), self._key),
                encrypt_field(account.card_number.encode("utf-8"), self._key),
                account.status,
                account.id,
            ),
        )

    def _to_account(self, row) -> Account | None:
        if row is None:
            return None
        return Account(
            id=str(row[0]),
            owner_id=str(row[1]),
            account_number=decrypt_field(bytes(row[2]), self._key).decode("utf-8"),
            balance_minor=int(decrypt_field(bytes(row[3]), self._key).decode("utf-8")),
            card_number=decrypt_field(bytes(row[4]), self._key).decode("utf-8"),
            status=row[5],
        )
