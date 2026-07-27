"""Password hashing + JWT dependency wiring for api-gateway (Phase 9, ADR
0009). The gateway is the sole issuer of user JWTs (`/auth/login`) and also
verifies them on its own protected routes, so both directions live here.
"""

from passlib.context import CryptContext

from app.config import get_settings
from event_contracts import Role, build_current_user_dependency, build_require_role_dependency
from event_contracts import create_access_token as _create_access_token

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _pwd_context.verify(password, password_hash)


def issue_token(*, user_id: str, email: str, role: Role) -> tuple[str, int]:
    """Returns (token, expires_in_seconds)."""
    settings = get_settings()
    token = _create_access_token(
        subject=user_id,
        email=email,
        role=role,
        secret=settings.jwt_secret_key,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        expires_minutes=settings.jwt_access_token_expires_minutes,
    )
    return token, settings.jwt_access_token_expires_minutes * 60


def _jwt_settings() -> dict[str, str]:
    settings = get_settings()
    return {
        "secret": settings.jwt_secret_key,
        "issuer": settings.jwt_issuer,
        "audience": settings.jwt_audience,
    }


get_current_user = build_current_user_dependency(**_jwt_settings())
require_viewer = build_require_role_dependency(get_current_user, "viewer")
require_ops = build_require_role_dependency(get_current_user, "ops")
require_admin = build_require_role_dependency(get_current_user, "admin")
