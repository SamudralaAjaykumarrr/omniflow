"""Shared s3fs/pyarrow S3 connection options for MinIO — used by any
data-platform component that talks to S3 directly rather than through
Spark's own S3A connector (e.g. `app.lag_poller`, `app.dq.report`)."""

from __future__ import annotations

import boto3
import s3fs

from app.config import Settings


def s3_options(settings: Settings) -> dict:
    return {
        "key": settings.minio_root_user,
        "secret": settings.minio_root_password,
        "client_kwargs": {"endpoint_url": settings.minio_endpoint},
    }


def boto3_client(settings: Settings):
    """A plain boto3 (sync) S3 client, for the one operation s3fs can't do
    against this MinIO version: deleting objects. s3fs's `rm` — even for a
    single path — always goes through S3's bulk `DeleteObjects` API
    (a POST with an XML body), which this MinIO version rejects
    (`MissingContentMD5`) regardless of how many keys are in the request —
    a real S3-compatibility gap hit running this for real, not a
    hypothetical. boto3's `delete_object` (singular) is a plain `DELETE
    /bucket/key` with no body, a different code path that doesn't hit this
    at all."""
    return boto3.client(
        "s3",
        endpoint_url=settings.minio_endpoint,
        aws_access_key_id=settings.minio_root_user,
        aws_secret_access_key=settings.minio_root_password,
    )


def ensure_prefix_exists(settings: Settings, path: str) -> None:
    """Structured Streaming's file source requires its source path to
    already exist at query-*start* time (`AnalysisException:
    [PATH_NOT_FOUND]` otherwise) — a real problem the very first time a
    fresh environment starts Silver/Gold before Bronze/Silver have ever
    written a single event of that type (exactly what a clean `docker
    compose up` produces: `minio-init` only creates the top-level
    `bronze`/`silver`/... prefixes, never any `event_type=<X>`
    subdirectory). Touches a hidden placeholder object under the prefix if
    nothing is there yet — Spark's file listing silently ignores hidden
    files (leading `.`/`_`, same convention as its own `_SUCCESS` markers),
    so this is invisible to any actual read of real data.

    This alone is *not* enough to make a fresh Structured Streaming query
    survive real data showing up later, though — Structured Streaming
    additionally auto-discovers which further columns are Hive-style
    partition columns (here: `date`) once, from whatever `date=<Y>`
    directories exist at query-start; a path with no data at all resolves
    with zero partition columns, and the first *real* `date=<Y>` directory
    that appears afterward then breaks the query with a schema-mismatch
    assertion (`Invalid batch: ...,ingested_at#N != ...,ingested_at#N,
    date#M`) — hit for real running this against MinIO. The fix for that
    part is on the caller: declare `date` explicitly in the schema passed
    to `.schema(...)` (see `app.silver.read_bronze_stream_for_type` /
    `app.silver_io.read_silver_stream`) instead of relying on
    auto-discovery at all, so the partition *column* is known from the
    very first query-start regardless of what partition *values* exist yet.

    `path` is `s3a://...`; s3fs/boto3 want the bucket-relative form."""
    fs = s3fs.S3FileSystem(**s3_options(settings))
    marker = f"{path.removeprefix('s3a://')}/.keep"
    if not fs.exists(marker):
        with fs.open(marker, "wb"):
            pass
