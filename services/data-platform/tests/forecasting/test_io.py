from __future__ import annotations

import pandas as pd

from app.config import Settings
from app.forecasting import io as fio


def test_write_read_parquet_roundtrip_local(tmp_path):
    settings = Settings()
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    path = str(tmp_path / "nested" / "data.parquet")
    fio.write_parquet(df, path, settings)
    loaded = fio.read_parquet(path, settings)
    pd.testing.assert_frame_equal(df, loaded)


def test_write_read_json_roundtrip_local(tmp_path):
    settings = Settings()
    payload = {"a": 1, "b": {"c": [1, 2, 3]}}
    path = str(tmp_path / "nested" / "data.json")
    fio.write_json(payload, path, settings)
    loaded = fio.read_json(path, settings)
    assert loaded == payload


def test_is_remote_detects_s3_schemes():
    assert fio._is_remote("s3a://bucket/path") is True
    assert fio._is_remote("s3://bucket/path") is True
    assert fio._is_remote("/local/path") is False


def test_bucket_relative_strips_scheme():
    assert fio._bucket_relative("s3a://bucket/path") == "bucket/path"
    assert fio._bucket_relative("s3://bucket/path") == "bucket/path"
