from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GATEWAY_")

    service_name: str = "api-gateway"
    order_service_url: str = "http://order-service:8000"
    inventory_service_url: str = "http://inventory-service:8000"
    rate_limit_per_minute: int = 120
    upstream_timeout_seconds: float = 10.0
    otel_exporter_otlp_endpoint: str = Field(
        default="http://otel-collector:4318", validation_alias="OTEL_EXPORTER_OTLP_ENDPOINT"
    )

    # Phase 9 (JWT/RBAC, ADR 0009): api-gateway is the sole issuer of user
    # JWTs and owns the `users` table — a new per-service database, same
    # "no live cross-service FKs" boundary every other service's own
    # database already follows (ADR 0008).
    database_url: str = "postgresql+psycopg://omniflow:omniflow@postgres:5432/omniflow_gateway"

    # Not service-prefixed, same reasoning as otel_exporter_otlp_endpoint
    # above: the signing secret/issuer/audience are shared infra config
    # every JWT verifier (api-gateway issues, failure-lab also verifies)
    # must agree on bit-for-bit, not a per-service value.
    #
    # jwt_secret_key has no code-level default: an app that starts without a
    # real secret set (missing env var) must fail loudly at startup, not
    # silently sign tokens with a well-known placeholder baked into source.
    # The only place a dev-only convenience value exists is
    # docker-compose.yml's environment default (documented there and in
    # .env.example), the same pattern this repo already uses for every
    # other secret (POSTGRES_PASSWORD, MINIO_ROOT_PASSWORD,
    # GRAFANA_ADMIN_PASSWORD).
    jwt_secret_key: str = Field(validation_alias="JWT_SECRET_KEY")
    jwt_issuer: str = Field(default="omniflow-api-gateway", validation_alias="JWT_ISSUER")
    jwt_audience: str = Field(default="omniflow-services", validation_alias="JWT_AUDIENCE")
    jwt_access_token_expires_minutes: int = 30

    # Demo/local-dev user seeding (idempotent, run at startup — see
    # app.seed). Every password below is a documented local-development-only
    # default, never a real credential; override via env var for any
    # non-throwaway use. Matches this repo's existing dev-secret convention.
    seed_demo_users: bool = True
    seed_admin_email: str = "admin@omniflow.local"
    seed_admin_password: str = "admin_dev_only"
    seed_ops_email: str = "ops@omniflow.local"
    seed_ops_password: str = "ops_dev_only"
    seed_viewer_email: str = "viewer@omniflow.local"
    seed_viewer_password: str = "viewer_dev_only"
    # A scoped service account (role `ops`, least privilege needed) other
    # backend processes log in as for machine-to-machine calls against this
    # gateway's protected routes — see failure-lab's GatewayClient, the only
    # current caller (DECISIONS.md "Phase 9").
    seed_service_email: str = "failure-lab-service@omniflow.local"
    seed_service_password: str = "service_dev_only"


@lru_cache
def get_settings() -> Settings:
    # mypy's native dataclass_transform support (PEP 681, which pydantic's
    # BaseModel stub opts into) treats jwt_secret_key as a required
    # constructor keyword since it has no code-level default — but
    # pydantic-settings resolves it from the JWT_SECRET_KEY env var at
    # runtime, not from a constructor argument. A real stub/type-system gap
    # (not a bug), same class of suppression as the SQLAlchemy
    # Mutable.as_mutable case in fulfillment-orchestrator/app/models.py.
    return Settings()  # type: ignore[call-arg]
