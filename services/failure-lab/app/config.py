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


@lru_cache
def get_settings() -> Settings:
    return Settings()
