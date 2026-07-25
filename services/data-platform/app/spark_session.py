"""Shared SparkSession builder.

Single-node `local[*]` mode per ADR 0005 — one JVM, no cluster manager. The
Kafka source connector and S3A/AWS SDK jars are already baked into the image
(`Dockerfile`), so this never needs `spark.jars.packages` (and therefore
never touches the network) at job-start time.
"""

from __future__ import annotations

from pyspark.sql import SparkSession

from app.config import Settings


def build_spark_session(
    app_name: str,
    settings: Settings,
    *,
    master: str = "local[*]",
    shuffle_partitions: int = 4,
) -> SparkSession:
    builder = (
        SparkSession.builder.appName(app_name)
        .master(master)
        # Keep the JVM's footprint predictable on a shared 15Gi host running
        # many other containers alongside three of these (RISKS.md #2).
        .config("spark.driver.memory", "1g")
        .config("spark.sql.shuffle.partitions", str(shuffle_partitions))
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.ui.enabled", "false")
        # Structured Streaming's own docs call this out explicitly for any
        # app running multiple *concurrent* queries in one SparkSession
        # (app.silver runs 11, app.gold.runner runs 9): Spark's default FIFO
        # job scheduler can starve a later-submitted query's micro-batches
        # indefinitely behind an earlier one's, especially with few cores —
        # hit for real running 11 concurrent Silver queries on `local[2]`
        # (one query's batches simply stopped being scheduled at all, not
        # just lagging). FAIR round-robins job slots across all concurrently
        # running queries instead.
        .config("spark.scheduler.mode", "FAIR")
        # S3A -> MinIO. Path-style access + a fixed endpoint is what makes
        # this target real S3 unchanged (just swap the endpoint/creds) in
        # the AWS deployment story (docs/data-pipeline.md).
        .config("spark.hadoop.fs.s3a.endpoint", settings.minio_endpoint)
        .config("spark.hadoop.fs.s3a.access.key", settings.minio_root_user)
        .config("spark.hadoop.fs.s3a.secret.key", settings.minio_root_password)
        .config("spark.hadoop.fs.s3a.path.style.access", "true")
        .config(
            "spark.hadoop.fs.s3a.aws.credentials.provider",
            "org.apache.hadoop.fs.s3a.SimpleAWSCredentialsProvider",
        )
        .config("spark.hadoop.fs.s3a.connection.ssl.enabled", "false")
        .config("spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem")
    )
    return builder.getOrCreate()
