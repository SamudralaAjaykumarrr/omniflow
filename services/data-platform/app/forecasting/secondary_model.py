"""Secondary model (ADR 0006, section D): `HistGradientBoostingRegressor` —
pure scikit-learn, no extra system toolchain, deterministic given a fixed
`random_state`. Chosen over `GradientBoostingRegressor`/
`RandomForestRegressor` for native missing-value support: this dataset's
earliest `max(lag_days)` rows of any SKU x location series are legitimately
NaN (the lag history simply doesn't exist yet) rather than a data quality
defect to impute away, and `HistGradientBoostingRegressor` handles NaN
features natively without requiring an imputer step.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

SECONDARY_MODEL_NAME = "hist_gradient_boosting"


@dataclass
class SecondaryModel:
    feature_columns: list[str]
    random_state: int = 42
    model: HistGradientBoostingRegressor | None = field(default=None, repr=False)

    def fit(self, train_df: pd.DataFrame, target_col: str) -> SecondaryModel:
        x = train_df[self.feature_columns]
        y = train_df[target_col]
        self.model = HistGradientBoostingRegressor(random_state=self.random_state)
        self.model.fit(x, y)
        return self

    def predict(self, df: pd.DataFrame) -> pd.Series:
        if self.model is None:
            raise RuntimeError("SecondaryModel.predict called before fit")
        preds = self.model.predict(df[self.feature_columns])
        return pd.Series(preds, index=df.index).clip(lower=0)
