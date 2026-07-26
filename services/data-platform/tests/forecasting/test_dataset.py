from __future__ import annotations

import pandas as pd
import pytest

from app.forecasting.dataset import DataQualityError, prepare_dataset
from app.forecasting.features import feature_columns
from app.forecasting.synthetic import generate_synthetic_history


def test_prepare_dataset_happy_path(small_config):
    history = generate_synthetic_history(small_config)
    frame = prepare_dataset(history, small_config)
    for col in feature_columns(small_config):
        assert col in frame.columns
    assert len(frame) == len(history)


def test_prepare_dataset_raises_on_negative_demand(small_config):
    history = generate_synthetic_history(small_config)
    history.loc[0, "units_demanded"] = -5
    with pytest.raises(DataQualityError) as exc_info:
        prepare_dataset(history, small_config)
    assert any(f.name == "no_negative_demand" for f in exc_info.value.failures)


def test_prepare_dataset_raises_on_missing_required_column(small_config):
    history = generate_synthetic_history(small_config).drop(columns=["price"])
    with pytest.raises(DataQualityError) as exc_info:
        prepare_dataset(history, small_config)
    assert any(f.name == "required_columns" for f in exc_info.value.failures)


def test_prepare_dataset_raises_on_empty_input(small_config):
    with pytest.raises(DataQualityError):
        prepare_dataset(pd.DataFrame(), small_config)
