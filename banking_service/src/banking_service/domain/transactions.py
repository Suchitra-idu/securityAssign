from dataclasses import dataclass


@dataclass(frozen=True)
class Transaction:
    id: str
    from_account_id: str
    to_account_id: str
    amount_minor: int
    at: int
    signature: bytes


def transaction_payload(tx: Transaction) -> dict:
    return {
        "id": tx.id,
        "from": tx.from_account_id,
        "to": tx.to_account_id,
        "amount_minor": tx.amount_minor,
        "at": tx.at,
    }
