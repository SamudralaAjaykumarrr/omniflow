# Build context is the repo root (see docker-compose.yml) so this can COPY
# the sibling event-contracts package as a local dependency — the gateway
# now uses its shared logging/tracing/metrics helpers (Phase 3) and, since
# Phase 9, its shared JWT/RBAC helpers plus its own Postgres-backed `users`
# table (ADR 0009), migrated via Alembic like every other stateful service.
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY services/event-contracts /app/services/event-contracts
COPY services/api-gateway/requirements.txt /app/services/api-gateway/requirements.txt
RUN pip install --no-cache-dir --upgrade pip==26.1.2 \
    && pip install --no-cache-dir -r /app/services/api-gateway/requirements.txt \
    && pip install --no-cache-dir -e /app/services/event-contracts

COPY services/api-gateway /app/services/api-gateway
WORKDIR /app/services/api-gateway
RUN chmod +x entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
