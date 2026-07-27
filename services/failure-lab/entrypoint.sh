#!/usr/bin/env bash
set -euo pipefail

alembic upgrade head

if [ "$#" -gt 0 ]; then
  exec "$@"
else
  exec uvicorn app.main:app --host 0.0.0.0 --port 8000
fi
