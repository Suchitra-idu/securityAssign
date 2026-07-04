from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from banking_service.application.settings import BankingSettings


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BANKING_", env_file=".env", extra="ignore")

    database_url: str

    auth_public_key_pem: str | None = None
    auth_public_key_path: str | None = None

    tx_signing_private_key_pem: str | None = None
    tx_signing_private_key_path: str | None = None
    tx_signing_public_key_pem: str | None = None
    tx_signing_public_key_path: str | None = None

    field_key_hex: str | None = None
    field_key_path: str | None = None

    pool_min_size: int = Field(default=1, ge=1)
    pool_max_size: int = Field(default=10, ge=1)

    @model_validator(mode="after")
    def _resolve(self) -> "Config":
        if self.auth_public_key_path:
            self.auth_public_key_pem = Path(self.auth_public_key_path).read_text()
        if self.tx_signing_private_key_path:
            self.tx_signing_private_key_pem = Path(self.tx_signing_private_key_path).read_text()
        if self.tx_signing_public_key_path:
            self.tx_signing_public_key_pem = Path(self.tx_signing_public_key_path).read_text()
        if not self.auth_public_key_pem:
            raise ValueError(
                "BANKING_AUTH_PUBLIC_KEY_PEM or BANKING_AUTH_PUBLIC_KEY_PATH must be set"
            )
        if not self.tx_signing_private_key_pem or not self.tx_signing_public_key_pem:
            raise ValueError(
                "BANKING_TX_SIGNING_PRIVATE_KEY_* and BANKING_TX_SIGNING_PUBLIC_KEY_* must be set"
            )
        if not self.field_key_hex and not self.field_key_path:
            raise ValueError("BANKING_FIELD_KEY_HEX or BANKING_FIELD_KEY_PATH must be set")
        return self

    def field_key(self) -> bytes:
        raw = (
            Path(self.field_key_path).read_text().strip()
            if self.field_key_path
            else self.field_key_hex
        )
        key = bytes.fromhex(raw)
        if len(key) != 32:
            raise ValueError("field key must be 32 bytes (64 hex chars)")
        return key

    def banking_settings(self) -> BankingSettings:
        return BankingSettings(
            auth_public_key=self.auth_public_key_pem,
            tx_signing_private_key=self.tx_signing_private_key_pem,
            tx_signing_public_key=self.tx_signing_public_key_pem,
        )
