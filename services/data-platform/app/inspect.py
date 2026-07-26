"""CLI to inspect a MinIO data-lake prefix — object count, total size, and a
breakdown by top-level partition, without booting a Spark/JVM session. Used
by the `make inspect-*` targets to answer "did Bronze/Silver/Gold/quarantine
actually get written, and how much" from the command line (see
docs/phase-6-streaming-data-platform.md's "Local setup"/"Observability").
"""

from __future__ import annotations

import argparse
from collections import Counter

from app.config import Settings, get_settings
from app.s3 import boto3_client


def list_prefix(settings: Settings, prefix: str) -> list[dict]:
    client = boto3_client(settings)
    paginator = client.get_paginator("list_objects_v2")
    key_prefix = f"{prefix.strip('/')}/"
    objects: list[dict] = []
    for page in paginator.paginate(Bucket=settings.data_lake_bucket, Prefix=key_prefix):
        objects.extend(page.get("Contents", []))
    return objects


def summarize(prefix: str, objects: list[dict]) -> str:
    """Pure formatting — no I/O — so it's unit-testable against a hand-built
    `objects` list without a real MinIO connection."""
    key_prefix = f"{prefix.strip('/')}/"
    total_bytes = sum(obj["Size"] for obj in objects)
    partitions: Counter[str] = Counter()
    for obj in objects:
        rest = obj["Key"].removeprefix(key_prefix)
        segment = rest.split("/", 1)[0] if rest else "(root)"
        # `.keep` placeholder objects (app.s3.ensure_prefix_exists) aren't
        # real data — worth excluding from the partition breakdown so an
        # empty-but-initialized prefix reads as "0 objects", not "1".
        if segment == ".keep":
            continue
        partitions[segment] += 1

    lines = [f"{prefix}: {sum(partitions.values())} object(s), {total_bytes} byte(s)"]
    for segment, count in sorted(partitions.items()):
        lines.append(f"  {segment}: {count} object(s)")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect a MinIO data-lake prefix (bronze, bronze_rejects, silver, "
        "silver_rejects, late_events, gold, dq-reports, ...)."
    )
    parser.add_argument("prefix", help="Bucket-relative prefix, e.g. bronze or silver_rejects")
    parser.add_argument(
        "--limit", type=int, default=20, help="Max sample object keys to print (default 20)."
    )
    args = parser.parse_args()

    settings = get_settings()
    objects = list_prefix(settings, args.prefix)
    print(summarize(args.prefix, objects))
    if objects:
        print(f"\nSample keys (up to {args.limit}):")
        for obj in objects[: args.limit]:
            print(f"  {obj['Key']}  ({obj['Size']} bytes)")


if __name__ == "__main__":
    main()
