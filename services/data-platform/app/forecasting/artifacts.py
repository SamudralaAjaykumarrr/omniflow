"""Local persistence for trained model artifacts + metadata (section H).
`joblib` (the standard scikit-learn-recommended serializer) writes the
model binary under `config.artifact_dir`; a plain-JSON metadata file lives
alongside it so a human — or the `select`/`inspect` CLI commands — can read
training range, feature list, and run identity without deserializing the
model itself. `config.artifact_dir` is gitignored; nothing under it is ever
committed.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib


@dataclass
class ModelMetadata:
    run_id: str
    model_name: str
    model_version: str
    trained_at: str
    feature_columns: list[str]
    training_range: dict[str, str]
    evaluation_range: dict[str, str]
    training_rows: int
    random_state: int | None
    extra: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_metadata(
    *,
    run_id: str,
    model_name: str,
    model_version: str,
    feature_columns: list[str],
    training_range: dict[str, str],
    evaluation_range: dict[str, str],
    training_rows: int,
    random_state: int | None = None,
    extra: dict[str, Any] | None = None,
) -> ModelMetadata:
    return ModelMetadata(
        run_id=run_id,
        model_name=model_name,
        model_version=model_version,
        trained_at=datetime.now(UTC).isoformat(),
        feature_columns=feature_columns,
        training_range=training_range,
        evaluation_range=evaluation_range,
        training_rows=training_rows,
        random_state=random_state,
        extra=extra or {},
    )


def model_paths(artifact_dir: str, model_name: str, run_id: str) -> tuple[Path, Path]:
    base = Path(artifact_dir) / model_name / run_id
    return base / "model.joblib", base / "metadata.json"


def save_model(model: Any, metadata: ModelMetadata, artifact_dir: str) -> tuple[Path, Path]:
    model_path, metadata_path = model_paths(artifact_dir, metadata.model_name, metadata.run_id)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, model_path)
    metadata_path.write_text(json.dumps(metadata.to_dict(), indent=2))
    return model_path, metadata_path


def load_model(model_path: Path) -> Any:
    return joblib.load(model_path)


def load_metadata(metadata_path: Path) -> dict[str, Any]:
    return json.loads(metadata_path.read_text())


def latest_run_id(artifact_dir: str, model_name: str) -> str | None:
    base = Path(artifact_dir) / model_name
    if not base.exists():
        return None
    run_dirs = sorted(p.name for p in base.iterdir() if p.is_dir())
    return run_dirs[-1] if run_dirs else None
