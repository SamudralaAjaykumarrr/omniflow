"""Shared helpers for Gold streaming queries.

Every Gold dataset here is a windowed aggregation with a watermark, written
in `append` output mode: Structured Streaming only emits a window's final
row once the watermark has advanced past its end, so append mode already
gives "write each window exactly once, when it's done" without needing a
separate upsert-by-key merge step (which would need Delta Lake/Iceberg-style
MERGE support that plain Parquet doesn't have) — see docs/data-pipeline.md.
"""

from __future__ import annotations

import logging

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.streaming import StreamingQuery

from app.config import Settings
from app.metrics import record_rows, track_batch_duration

logger = logging.getLogger("data_platform.gold")


def flatten_window(df: DataFrame, window_col: str = "window") -> DataFrame:
    """`F.window(...)` produces a nested `struct<start,end>` column — flatten
    it into `window_start`/`window_end` (nested structs partition and read
    back awkwardly) and derive the `date` partition column from the start."""
    return (
        df.withColumn("window_start", F.col(window_col)["start"])
        .withColumn("window_end", F.col(window_col)["end"])
        .drop(window_col)
        .withColumn("date", F.to_date("window_start"))
    )


def write_gold_stream(
    df: DataFrame,
    settings: Settings,
    name: str,
    *,
    partition_cols: list[str] | None = None,
    trigger_once: bool = False,
) -> StreamingQuery:
    """Writes via `foreachBatch` + a plain `DataFrame.write` call, not
    `.writeStream.format("parquet")` directly — the latter uses
    Structured Streaming's `FileStreamSink`, which maintains its own
    `_spark_metadata` commit log alongside the actual Parquet files. Any
    batch reader that respects that log (including a plain
    `spark.read.parquet(path)`) only sees files recorded in it — so a file
    `app.backfill`'s swap step writes directly via raw S3 operations would
    be physically present but invisible to any such reader, since the swap
    has no way to also append to that internal log. `foreachBatch` with a
    plain write never creates `_spark_metadata` at all, so every file that
    physically exists under the path is exactly what any reader sees — the
    same reasoning, and the same pattern, `app.silver._write_batch`
    already uses for exactly this reason."""

    def _write(batch_df: DataFrame, batch_id: int) -> None:
        with track_batch_duration("gold", name):
            if batch_df.isEmpty():
                output_count = 0
            else:
                output_count = batch_df.count()
                writer = batch_df.write.mode("append")
                if partition_cols:
                    writer = writer.partitionBy(*partition_cols)
                writer.parquet(f"{settings.gold_path}/{name}")
        record_rows("gold", name, {"output": output_count})
        logger.info("gold batch %s (%s): %s output rows", batch_id, name, output_count)

    writer = (
        df.writeStream.foreachBatch(_write)
        .option("checkpointLocation", f"{settings.checkpoints_path}/gold/{name}")
        .outputMode("append")
    )
    writer = (
        writer.trigger(availableNow=True)
        if trigger_once
        else writer.trigger(processingTime="10 seconds")
    )
    return writer.start()
