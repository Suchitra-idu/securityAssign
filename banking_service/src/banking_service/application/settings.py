from dataclasses import dataclass


@dataclass(frozen=True)
class BankingSettings:
    auth_public_key: str
    tx_signing_private_key: str
    tx_signing_public_key: str
