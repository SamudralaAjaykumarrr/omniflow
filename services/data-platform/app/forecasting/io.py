"""Local-filesystem or MinIO Parquet/JSON I/O for the forecasting
subsystem. `app.forecasting` is a pandas/scikit-learn batch pipeline, not a
Spark job — this is a thin, independent I/O shim (distinct from `app.s3`,
which backs Spark-adjacent tooling like `app.inspect`/`app.backfill`) so its
own tests can point every path at a plain `tmp_path` directory and never
need a live MinIO connection, matching `make test-data-platform`'s existing
"no live Kafka/MinIO needed for its own suite" contract. The production CLI
defaults (see `app.forecasting.paths`) point at real `s3a://` MinIO paths,
same storage convention as the rest of the data platform.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import s3fs

from app.config import Settings
from app.s3 import s3_options


def _is_remote(path: str) -> bool:
    return path.startswith("s3a://") or path.startswith("s3://")


def _bucket_relative(path: str) -> str:
    return path.removeprefix("s3a://").removeprefix("s3://")


def write_parquet(df: pd.DataFrame, path: str, settings: Settings) -> None:
    if _is_remote(path):
        df.to_parquet(
            f"s3://{_bucket_relative(path)}", storage_options=s3_options(settings), index=False
        )
    else:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False)


def read_parquet(path: str, settings: Settings) -> pd.DataFrame:
    if _is_remote(path):
        return pd.read_parquet(
            f"s3://{_bucket_relative(path)}", storage_options=s3_options(settings)
        )
    return pd.read_parquet(path)


def write_json(payload: dict[str, Any], path: str, settings: Settings) -> None:
    text = json.dumps(payload, indent=2, default=str)
    if _is_remote(path):
        fs = s3fs.S3FileSystem(**s3_options(settings))
        with fs.open(_bucket_relative(path), "w") as f:
            f.write(text)
    else:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(text)


def read_json(path: str, settings: Settings) -> dict[str, Any]:
    if _is_remote(path):
        fs = s3fs.S3FileSystem(**s3_options(settings))
        with fs.open(_bucket_relative(path), "r") as f:
            return json.load(f)
    return json.loads(Path(path).read_text())
