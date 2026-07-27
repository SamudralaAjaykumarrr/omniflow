from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FAILURE_LAB_")

    service_name: str = "failure-lab"
    database_url: str = "postgresql+psycopg://omniflow:omniflow@postgres:5432/omniflow_failure_lab"

    # Customer-facing entry point — scenarios that create orders the way a
    # real customer would (payment-decline/timeout, duplicate-order-submit)
    # go through the gateway, not directly to order-service.
    api_gateway_url: str = "http://api-gateway:8000"
    order_service_url: str = "http://order-service:8000"
    inventory_service_url: str = "http://inventory-service:8000"
    orchestrator_service_url: str = "http://fulfillment-orchestrator:8000"

    kafka_bootstrap_servers: str = Field(
        default="redpanda:9092", validation_alias="KAFKA_BOOTSTRAP_SERVERS"
    )
    otel_exporter_otlp_endpoint: str = Field(
        default="http://otel-collector:4318", validation_alias="OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    # Standalone Prometheus server for the poison consumer worker — same
    # pattern as every other service's background workers (see
    # order-service/app/config.py's `metrics_port` docstring).
    metrics_port: int = Field(default=9100, validation_alias="METRICS_PORT")

    # How long a scenario is allowed to poll for an async outcome (saga
    # completion, a DLQ row appearing, etc.) before it is reported ERROR
    # rather than hanging forever. Generous but bounded — see
    # docs/phase-8-failure-laboratory.md "Determinism and timing".
    poll_timeout_seconds: float = 30.0
    poll_interval_seconds: float = 0.5

    # Safety bound for the downstream-outage scenario: inventory-service's
    # simulated-outage flag self-clears after this many seconds even if
    # nobody calls the disable endpoint, so a forgotten/crashed trigger can
    # never permanently wedge the shared dev stack.
    downstream_outage_max_duration_seconds: int = 30

    # Phase 9 (JWT/RBAC, ADR 0009): failure-lab verifies JWTs issued by
    # api-gateway, so the signing secret/issuer/audience must be the exact
    # same shared infra config api-gateway itself uses — not
    # FAILURE_LAB_-prefixed, same reasoning as kafka_bootstrap_servers
    # above. No code-level default for the secret (see api-gateway's
    # config.py for the full "fail loud, not a silent placeholder" reasoning).
    jwt_secret_key: str = Field(validation_alias="JWT_SECRET_KEY")
    jwt_issuer: str = Field(default="omniflow-api-gateway", validation_alias="JWT_ISSUER")
    jwt_audience: str = Field(default="omniflow-services", validation_alias="JWT_AUDIENCE")

    # The scoped `ops`-role service account (seeded by api-gateway's own
    # app.seed) this service's GatewayClient logs in as for its
    # machine-to-machine calls against the gateway's now-protected
    # POST /api/orders (payment-decline/timeout, duplicate-order-submit
    # scenarios go through the gateway deliberately — see docstring above).
    # Dev-only credentials, documented in .env.example, same convention as
    # every other seeded demo account.
    gateway_service_email: str = "failure-lab-service@omniflow.local"
    gateway_service_password: str = "service_dev_only"


@lru_cache
def get_settings() -> Settings:
    # See api-gateway/app/config.py's get_settings() for why this needs a
    # scoped ignore: jwt_secret_key has no code-level default (resolved from
    # the JWT_SECRET_KEY env var at runtime), which mypy's native
    # dataclass_transform support treats as a required constructor keyword.
    return Settings()  # type: ignore[call-arg]
