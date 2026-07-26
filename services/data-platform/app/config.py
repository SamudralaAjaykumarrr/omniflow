from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DATA_PLATFORM_")

    service_name: str = "data-platform"

    # Shared infra config — same value every service that talks to it uses,
    # not service-prefixed (mirrors every other service's `config.py`).
    kafka_bootstrap_servers: str = Field(
        default="redpanda:9092", validation_alias="KAFKA_BOOTSTRAP_SERVERS"
    )
    minio_endpoint: str = Field(default="http://minio:9000", validation_alias="MINIO_ENDPOINT")
    minio_root_user: str = Field(default="omniflow", validation_alias="MINIO_ROOT_USER")
    minio_root_password: str = Field(
        default="omniflow_dev_only", validation_alias="MINIO_ROOT_PASSWORD"
    )
    data_lake_bucket: str = Field(default="omniflow", validation_alias="DATA_LAKE_BUCKET")

    # Background workers have no HTTP server of their own — same standalone
    # prometheus_client server pattern as every other worker (outbox relays,
    # validator consumer, saga consumer). Optional here: not every
    # data-platform entrypoint (e.g. batch jobs) needs a metrics port.
    metrics_port: int = Field(default=9106, validation_alias="METRICS_PORT")

    # Watermarks, tunable per dataset in code; this is the shared default.
    default_watermark: str = "10 minutes"

    @property
    def bronze_path(self) -> str:
        return f"s3a://{self.data_lake_bucket}/bronze"

    @property
    def bronze_rejects_path(self) -> str:
        return f"s3a://{self.data_lake_bucket}/bronze_rejects"

    @property
    def silver_path(self) -> str:
        return f"s3a://{self.data_lake_bucket}/silver"

    @property
    def silver_rejects_path(self) -> str:
        return f"s3a://{self.data_lake_bucket}/silver_rejects"

    @property
    def late_events_path(self) -> str:
        return f"s3a://{self.data_lake_bucket}/late_events"

    @property
    def gold_path(self) -> str:
        return f"s3a://{self.data_lake_bucket}/gold"

    @property
    def checkpoints_path(self) -> str:
        return f"s3a://{self.data_lake_bucket}/checkpoints"

    @property
    def forecasting_path(self) -> str:
        """Root prefix for Phase 6 demand-forecasting artifacts (synthetic
        history, prepared dataset, forecast output) — a new top-level prefix
        alongside bronze/silver/gold/dq-reports, not nested under gold,
        since it isn't a Spark streaming aggregation like the other ten
        Gold datasets. See docs/phase-6-demand-forecasting.md."""
        return f"s3a://{self.data_lake_bucket}/forecasting"


@lru_cache
def get_settings() -> Settings:
    return Settings()
