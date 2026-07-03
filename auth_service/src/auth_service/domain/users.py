from dataclasses import dataclass
from typing import Literal

Role = Literal["customer", "admin"]


@dataclass(frozen=True)
class User:
    id: str
    username: str
    password_hash: str
    role: Role
