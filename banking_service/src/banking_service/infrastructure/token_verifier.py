from fastapi import Header, HTTPException, status

from shared_security.tokens import TokenError, verify_token

from banking_service.application.caller import Caller


def bearer_caller(public_key: str):
    def _dep(authorization: str | None = Header(default=None)) -> Caller:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
        token = authorization[len("Bearer ") :].strip()
        try:
            claims = verify_token(token, public_key)
        except TokenError:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")
        role = claims.get("role")
        sub = claims.get("sub")
        if role not in ("customer", "admin") or not isinstance(sub, str):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "malformed token claims")
        return Caller(user_id=sub, role=role)

    return _dep
