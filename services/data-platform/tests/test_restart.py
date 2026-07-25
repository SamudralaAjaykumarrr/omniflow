from __future__ import annotations

from pyspark.sql.types import StringType, StructField, StructType


def test_streaming_query_restart_does_not_reprocess_already_seen_files(spark, tmp_path):
    """Every real streaming job in this pipeline (`app.bronze`, `app.silver`,
    `app.gold.runner`) uses a durable Parquet sink + `.option(
    "checkpointLocation", ...)` + `trigger(availableNow=True)` for its
    `--once` mode — the primitive docs/data-pipeline.md's "Checkpointing"
    section claims makes a restart resume exactly where it left off, with
    no reprocessing and no gap. Exercised here against a real file
    source/checkpoint (Kafka isn't available in this test environment) —
    the checkpoint mechanism itself is source-agnostic, so this proves the
    same guarantee the real jobs rely on. Uses a Parquet sink, not
    `memory` — Spark's memory sink doesn't support checkpoint-based
    recovery across separate query instances at all ("This query does not
    support recovering from checkpoint location"), so it can't stand in for
    a "restart" in the first place."""
    schema = StructType([StructField("event_id", StringType())])
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    checkpoint_dir = tmp_path / "checkpoint"

    # Written directly into `input_dir` (not a nested subdirectory) — a
    # plain file source only lists files one level deep by default (no
    # `recursiveFileLookup`), same as the real Bronze/Silver/Gold jobs,
    # which only ever read a single `event_type=<X>` partition directory
    # directly, never an arbitrarily-named subdirectory beneath it.
    spark.createDataFrame([("evt-1",), ("evt-2",)], schema=schema).write.mode("append").parquet(
        str(input_dir)
    )

    def run_once() -> None:
        query = (
            spark.readStream.schema(schema)
            .parquet(str(input_dir))
            .writeStream.format("parquet")
            .option("path", str(output_dir))
            .option("checkpointLocation", str(checkpoint_dir))
            .outputMode("append")
            .trigger(availableNow=True)
            .start()
        )
        query.awaitTermination()

    def output_count() -> int:
        return spark.read.parquet(str(output_dir)).count()

    run_once()
    assert output_count() == 2

    # "Restart" against the same checkpoint, no new input written — a real
    # restart should pick up exactly 0 new rows, never reprocess batch-1.
    run_once()
    assert output_count() == 2

    # New data arrives after the restart — only the new file is processed,
    # the first batch is never touched again.
    spark.createDataFrame([("evt-3",)], schema=schema).write.mode("append").parquet(str(input_dir))
    run_once()
    assert output_count() == 3
