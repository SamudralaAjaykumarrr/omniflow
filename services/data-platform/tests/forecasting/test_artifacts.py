from __future__ import annotations

from app.forecasting import artifacts
from app.forecasting.baseline import SeasonalNaiveModel


def test_build_metadata_captures_required_fields():
    metadata = artifacts.build_metadata(
        run_id="run1",
        model_name="seasonal_naive",
        model_version="v1",
        feature_columns=["lag_7"],
        training_range={"start": "2025-01-01", "end": "2025-03-01"},
        evaluation_range={"start": "2025-03-02", "end": "2025-03-08"},
        training_rows=100,
    )
    assert metadata.run_id == "run1"
    assert metadata.feature_columns == ["lag_7"]
    assert metadata.trained_at  # populated, non-empty


def test_save_and_load_model_roundtrip(tmp_path):
    model = SeasonalNaiveModel().fit(None, "units_demanded")
    metadata = artifacts.build_metadata(
        run_id="run1",
        model_name="seasonal_naive",
        model_version="v1",
        feature_columns=["lag_7"],
        training_range={"start": "2025-01-01", "end": "2025-03-01"},
        evaluation_range={"start": "2025-03-02", "end": "2025-03-08"},
        training_rows=100,
    )
    model_path, metadata_path = artifacts.save_model(model, metadata, str(tmp_path))

    assert model_path.exists()
    assert metadata_path.exists()

    loaded_model = artifacts.load_model(model_path)
    assert isinstance(loaded_model, SeasonalNaiveModel)
    assert loaded_model.fitted is True

    loaded_metadata = artifacts.load_metadata(metadata_path)
    assert loaded_metadata["run_id"] == "run1"
    assert loaded_metadata["training_rows"] == 100


def test_model_paths_are_namespaced_by_model_name_and_run_id(tmp_path):
    model_path, metadata_path = artifacts.model_paths(str(tmp_path), "seasonal_naive", "run1")
    assert "seasonal_naive" in str(model_path)
    assert "run1" in str(model_path)
    assert model_path.name == "model.joblib"
    assert metadata_path.name == "metadata.json"


def test_latest_run_id_returns_none_when_no_runs_exist(tmp_path):
    assert artifacts.latest_run_id(str(tmp_path), "seasonal_naive") is None


def test_latest_run_id_returns_lexicographically_last_run(tmp_path):
    model = SeasonalNaiveModel().fit(None, "units_demanded")
    for run_id in ["run-a", "run-b", "run-c"]:
        metadata = artifacts.build_metadata(
            run_id=run_id,
            model_name="seasonal_naive",
            model_version="v1",
            feature_columns=["lag_7"],
            training_range={"start": "2025-01-01", "end": "2025-03-01"},
            evaluation_range={"start": "2025-03-02", "end": "2025-03-08"},
            training_rows=1,
        )
        artifacts.save_model(model, metadata, str(tmp_path))

    assert artifacts.latest_run_id(str(tmp_path), "seasonal_naive") == "run-c"
