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


@lru_cache
def get_settings() -> Settings:
    return Settings()
