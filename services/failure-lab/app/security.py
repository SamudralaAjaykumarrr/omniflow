"""JWT dependency wiring for failure-lab (Phase 9, ADR 0009). Unlike
api-gateway, this service only ever verifies tokens (it never issues
them) — trigger/reset need `ops`/`admin`; the read-only catalog/run
endpoints accept any authenticated role."""

from app.config import get_settings
from event_contracts import build_current_user_dependency, build_require_role_dependency


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
