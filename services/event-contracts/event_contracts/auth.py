"""Shared JWT authentication + role-based authorization (ADR 0009).

Reused by every FastAPI service that needs to verify a caller's identity:
`api-gateway` (issues tokens via `/auth/login`) and `failure-lab` (verifies
tokens issued by api-gateway) as of Phase 9. A service builds its own
dependencies from its own settings (secret/issuer/audience come from that
service's environment, never hardcoded here) via `build_current_user_dependency`/
`build_require_role_dependency`, the same "shared helper, per-service wiring"
pattern `metrics_setup.MetricsMiddleware`/`configure_logging`/`configure_tracing`
already use.

Roles are ranked, not enumerated per-route: `viewer < ops < admin`, so
`require_role("ops")` also admits `admin` — least-privilege by construction
(every route defaults to the lowest role that can do the job; `admin` is a
strict superset, not a separate permission set to keep in sync).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Literal, get_args

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

Role = Literal["viewer", "ops", "admin"]

ROLES: tuple[Role, ...] = get_args(Role)
_ROLE_RANK: dict[str, int] = {role: rank for rank, role in enumerate(ROLES)}

ALGORITHM = "HS256"


class TokenError(Exception):
    """Base class for JWT validation failures — every subclass maps to a 401
    (authentication failure), never a 403 (that's an authorization failure
    on an otherwise-valid token, handled separately by role-rank checks)."""


class TokenExpiredError(TokenError):
    pass


class TokenInvalidError(TokenError):
    pass


@dataclass(frozen=True)
class TokenPayload:
    sub: str
    email: str
    role: Role
    jti: str
    iat: int
    exp: int


def create_access_token(
    *,
    subject: str,
    email: str,
    role: Role,
    secret: str,
    issuer: str,
    audience: str,
    expires_minutes: int,
) -> str:
    """Issues a short-lived signed JWT. No refresh-token rotation — a
    deliberate simplification named in ADR 0009's consequences, not an
    oversight; an expired token just requires logging in again."""
    now = int(time.time())
    claims = {
        "sub": subject,
        "email": email,
        "role": role,
        "iss": issuer,
        "aud": audience,
        "iat": now,
        "exp": now + expires_minutes * 60,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(claims, secret, algorithm=ALGORITHM)


def decode_access_token(token: str, *, secret: str, issuer: str, audience: str) -> TokenPayload:
    """Verifies signature, issuer, audience, and expiration (all via PyJWT's
    own `decode`, not hand-rolled comparisons — the exact fields this
    project's Phase 9 requirements call out). Raises `TokenExpiredError` /
    `TokenInvalidError`, never lets a `jwt.PyJWTError` leak past this
    module's boundary, so every caller has one exception hierarchy to catch."""
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=[ALGORITHM],
            audience=audience,
            issuer=issuer,
            options={"require": ["exp", "iat", "sub", "role", "aud", "iss"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError("token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenInvalidError(str(exc)) from exc

    role = claims.get("role")
    if role not in _ROLE_RANK:
        raise TokenInvalidError(f"unknown role in token: {role!r}")

    return TokenPayload(
        sub=str(claims["sub"]),
        email=str(claims.get("email", "")),
        role=role,
        jti=str(claims.get("jti", "")),
        iat=int(claims["iat"]),
        exp=int(claims["exp"]),
    )


_bearer_scheme = HTTPBearer(auto_error=False)


def build_current_user_dependency(*, secret: str, issuer: str, audience: str):
    """Builds a FastAPI dependency that extracts the `Authorization: Bearer
    <token>` header, validates it, and returns the decoded `TokenPayload` —
    or raises 401 for every failure mode (missing header, malformed token,
    expired, bad signature, wrong audience/issuer). Never 403 here: a 403
    means "I know who you are and you're not allowed", which requires a
    valid token in the first place."""

    def _get_current_user(
        credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    ) -> TokenPayload:
        if credentials is None or not credentials.credentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            return decode_access_token(
                credentials.credentials, secret=secret, issuer=issuer, audience=audience
            )
        except TokenError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"invalid token: {exc}",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

    return _get_current_user


def build_require_role_dependency(current_user_dependency, min_role: Role):
    """Builds a dependency that requires an already-valid token (via
    `current_user_dependency`) whose role ranks at or above `min_role`.
    Insufficient role -> 403, distinct from the 401s above."""

    def _require_role(user: TokenPayload = Depends(current_user_dependency)) -> TokenPayload:
        if _ROLE_RANK[user.role] < _ROLE_RANK[min_role]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"requires role >= {min_role!r}, caller has {user.role!r}",
            )
        return user

    return _require_role
