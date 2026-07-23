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


@lru_cache
def get_settings() -> Settings:
    return Settings()
