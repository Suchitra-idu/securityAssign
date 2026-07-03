from dataclasses import dataclass


@dataclass(frozen=True)
class RefreshRecord:
    token_hash: str
    user_id: str
    expires_at: int
