from dataclasses import dataclass
from typing import Literal

AccountStatus = Literal["active", "frozen"]


@dataclass(frozen=True)
class Account:
    id: str
    owner_id: str
    account_number: str
    balance_minor: int
    card_number: str
    status: AccountStatus
