from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ORDER_SERVICE_")

    service_name: str = "order-service"
    database_url: str = "postgresql+psycopg://omniflow:omniflow@postgres:5432/omniflow_orders"
    idempotency_key_ttl_hours: int = 24
    # Not service-prefixed: the broker address is shared infra config, the
    # same value for every service that talks to it.
    kafka_bootstrap_servers: str = Field(
        default="redpanda:9092", validation_alias="KAFKA_BOOTSTRAP_SERVERS"
    )
    otel_exporter_otlp_endpoint: str = Field(
        default="http://otel-collector:4318", validation_alias="OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    # Background workers (outbox relay, validator consumer) have no HTTP
    # server of their own to hang a `/metrics` route off of, so they run a
    # standalone `prometheus_client` HTTP server on this port instead. Each
    # worker process gets its own port, set per docker-compose service
    # (the FastAPI process itself doesn't use this — it serves `/metrics`
    # on its normal port 8000).
    metrics_port: int = Field(default=9100, validation_alias="METRICS_PORT")


@lru_cache
def get_settings() -> Settings:
    return Settings()
