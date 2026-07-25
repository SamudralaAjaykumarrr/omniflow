#!/usr/bin/env bash
# One-shot job: create the data-lake bucket and its top-level prefixes if they
# don't already exist. Idempotent — safe to re-run on every `docker compose up`.
set -euo pipefail

MINIO_HOST="${MINIO_HOST:-minio:9000}"
BUCKET="${DATA_LAKE_BUCKET:-omniflow}"

mc alias set local "http://${MINIO_HOST}" "${MINIO_ROOT_USER}" "${MINIO_ROOT_PASSWORD}"

if mc ls "local/${BUCKET}" >/dev/null 2>&1; then
  echo "bucket already exists: ${BUCKET}"
else
  mc mb "local/${BUCKET}"
  echo "created bucket: ${BUCKET}"
fi

for prefix in bronze silver silver_rejects late_events gold checkpoints dq-reports; do
  mc mb -p "local/${BUCKET}/${prefix}" >/dev/null 2>&1 || true
done

echo "bucket layout ready:"
mc ls "local/${BUCKET}"
