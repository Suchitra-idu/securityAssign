import secrets

_ACCOUNT_DIGITS = 12
_CARD_DIGITS = 16


def generate_account_number() -> str:
    return "".join(str(secrets.randbelow(10)) for _ in range(_ACCOUNT_DIGITS))


def generate_card_number() -> str:
    return "".join(str(secrets.randbelow(10)) for _ in range(_CARD_DIGITS))
