from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from auth_service.application.settings import TokenSettings


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUTH_", env_file=".env", extra="ignore")

    database_url: str
    # Signing keys can be supplied inline (env) or as a file path (Docker
    # secret / mounted PEM). The file path wins if both are set. In
    # production prefer the file: env vars are visible via docker inspect
    # and process env; Docker secrets are memory-mounted at /run/secrets
    # with 0400 perms.
    signing_private_key_pem: str | None = None
    signing_private_key_path: str | None = None
    signing_public_key_pem: str | None = None
    signing_public_key_path: str | None = None
    access_ttl_seconds: int = Field(default=300, ge=60)
    refresh_ttl_seconds: int = Field(default=86_400, ge=3_600)
    pool_min_size: int = 1
    pool_max_size: int = 10
    initial_admin_username: str | None = None
    initial_admin_password: str | None = None

    @model_validator(mode="after")
    def _resolve_keys(self) -> "Config":
        if self.signing_private_key_path:
            self.signing_private_key_pem = Path(self.signing_private_key_path).read_text()
        if self.signing_public_key_path:
            self.signing_public_key_pem = Path(self.signing_public_key_path).read_text()
        if not self.signing_private_key_pem:
            raise ValueError(
                "AUTH_SIGNING_PRIVATE_KEY_PEM or AUTH_SIGNING_PRIVATE_KEY_PATH must be set"
            )
        if not self.signing_public_key_pem:
            raise ValueError(
                "AUTH_SIGNING_PUBLIC_KEY_PEM or AUTH_SIGNING_PUBLIC_KEY_PATH must be set"
            )
        return self

    def tokens(self) -> TokenSettings:
        return TokenSettings(
            private_key=self.signing_private_key_pem,
            public_key=self.signing_public_key_pem,
            access_ttl=self.access_ttl_seconds,
            refresh_ttl=self.refresh_ttl_seconds,
        )
