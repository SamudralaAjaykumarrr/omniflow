from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ORDER_SERVICE_")

    service_name: str = "order-service"
    database_url: str = "postgresql+psycopg://omniflow:omniflow@postgres:5432/omniflow_orders"
    idempotency_key_ttl_hours: int = 24


@lru_cache
def get_settings() -> Settings:
    return Settings()
