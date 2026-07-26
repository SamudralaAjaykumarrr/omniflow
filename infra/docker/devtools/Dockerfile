# Shared devtools image for Phase 5 engineering-quality tooling: coverage
# combine/report, security scanning (bandit/pip-audit), pre-commit. Not used
# by lint/format/typecheck (those stay self-contained per Phase 3 convention,
# see root Makefile) — this image exists for the targets that need more than
# one tool installed at once, or that need every service's runtime deps
# importable in a single interpreter (coverage's xml re-parses source).
#
# Versions pinned to match what's already used elsewhere in this repo
# (root Makefile's typecheck target, each service's requirements.txt) so a
# devtools run and a per-service run never disagree about what "correct" is.
FROM python:3.12-slim

# git: pre-commit clones/manages hook repos and needs a repo context to run
# `--all-files` against.
RUN apt-get update -qq && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --quiet --upgrade pip==26.1.2

RUN pip install --no-cache-dir --quiet \
        ruff==0.6.9 \
        mypy==1.11.2 \
        pytest==8.3.3 \
        pytest-cov==5.0.0 \
        coverage[toml]==7.6.1 \
        bandit==1.7.10 \
        pip-audit==2.7.3 \
        pre-commit==3.8.0 \
        pydantic==2.9.2 pydantic-settings==2.5.2 sqlalchemy==2.0.35 \
        fastapi==0.115.0 httpx==0.27.2 confluent-kafka==2.5.3 \
        opentelemetry-api==1.27.0 prometheus-client==0.21.0 \
        pyspark==3.5.3 pyarrow==17.0.0 s3fs==2024.9.0

WORKDIR /app
