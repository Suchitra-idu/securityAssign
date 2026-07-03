from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from auth_service.application.settings import TokenSettings


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUTH_", env_file=".env", extra="ignore")

    database_url: str
    signing_private_key_pem: str
    signing_public_key_pem: str
    access_ttl_seconds: int = Field(default=300, ge=60)
    refresh_ttl_seconds: int = Field(default=86_400, ge=3_600)
    pool_min_size: int = 1
    pool_max_size: int = 10

    def tokens(self) -> TokenSettings:
        return TokenSettings(
            private_key=self.signing_private_key_pem,
            public_key=self.signing_public_key_pem,
            access_ttl=self.access_ttl_seconds,
            refresh_ttl=self.refresh_ttl_seconds,
        )
