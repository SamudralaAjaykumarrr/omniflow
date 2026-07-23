from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GATEWAY_")

    service_name: str = "api-gateway"
    order_service_url: str = "http://order-service:8000"
    inventory_service_url: str = "http://inventory-service:8000"
    rate_limit_per_minute: int = 120
    upstream_timeout_seconds: float = 10.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
