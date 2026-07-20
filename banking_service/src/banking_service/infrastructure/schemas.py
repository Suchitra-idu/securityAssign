from pydantic import BaseModel, ConfigDict, Field


class AccountResponse(BaseModel):
    id: str
    owner_id: str
    account_number: str
    balance_minor: int
    card_number: str
    status: str


class TransferRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_account_id: str = Field(min_length=1, max_length=64)
    to_account_number: str = Field(pattern=r"^\d{8,32}$")
    amount_minor: int = Field(gt=0, le=10_000_000_00)


class TransactionResponse(BaseModel):
    id: str
    from_account_id: str
    to_account_id: str
    amount_minor: int
    at: int
    signature_hex: str
    signature_valid: bool


class HealthResponse(BaseModel):
    status: str = "ok"
