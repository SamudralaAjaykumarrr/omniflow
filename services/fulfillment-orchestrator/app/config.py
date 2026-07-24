from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ORCHESTRATOR_")

    service_name: str = "fulfillment-orchestrator"
    database_url: str = "postgresql+psycopg://omniflow:omniflow@postgres:5432/omniflow_orchestrator"
    order_service_url: str = "http://order-service:8000"
    inventory_service_url: str = "http://inventory-service:8000"
    kafka_bootstrap_servers: str = Field(
        default="redpanda:9092", validation_alias="KAFKA_BOOTSTRAP_SERVERS"
    )
    otel_exporter_otlp_endpoint: str = Field(
        default="http://otel-collector:4318", validation_alias="OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    # See order-service/app/config.py's `metrics_port` docstring — same
    # standalone-Prometheus-server pattern for this service's saga consumer
    # and outbox relay.
    metrics_port: int = Field(default=9100, validation_alias="METRICS_PORT")
    payment_max_attempts: int = 5
    payment_retry_base_delay_seconds: float = 0.2
    payment_retry_max_delay_seconds: float = 30.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
