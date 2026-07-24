from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="INVENTORY_SERVICE_")

    service_name: str = "inventory-service"
    database_url: str = "postgresql+psycopg://omniflow:omniflow@postgres:5432/omniflow_inventory"
    reservation_ttl_minutes: int = 15
    low_stock_default_threshold: int = 10
    kafka_bootstrap_servers: str = Field(
        default="redpanda:9092", validation_alias="KAFKA_BOOTSTRAP_SERVERS"
    )
    otel_exporter_otlp_endpoint: str = Field(
        default="http://otel-collector:4318", validation_alias="OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    # See order-service/app/config.py's `metrics_port` docstring — same
    # standalone-Prometheus-server pattern for this service's outbox relay.
    metrics_port: int = Field(default=9100, validation_alias="METRICS_PORT")


@lru_cache
def get_settings() -> Settings:
    return Settings()
