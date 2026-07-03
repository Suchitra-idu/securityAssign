from dataclasses import dataclass


@dataclass(frozen=True)
class TokenSettings:
    private_key: str
    public_key: str
    access_ttl: int
    refresh_ttl: int
