from dataclasses import dataclass
from typing import Literal

CallerRole = Literal["customer", "admin"]


@dataclass(frozen=True)
class Caller:
    user_id: str
    role: CallerRole
