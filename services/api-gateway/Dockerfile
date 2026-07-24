# Build context is the repo root (see docker-compose.yml) so this can COPY
# the sibling event-contracts package as a local dependency — the gateway
# now uses its shared logging/tracing/metrics helpers (Phase 3).
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY services/event-contracts /app/services/event-contracts
COPY services/api-gateway/requirements.txt /app/services/api-gateway/requirements.txt
RUN pip install --no-cache-dir -r /app/services/api-gateway/requirements.txt \
    && pip install --no-cache-dir -e /app/services/event-contracts

COPY services/api-gateway /app/services/api-gateway
WORKDIR /app/services/api-gateway

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
