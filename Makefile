.PHONY: demo up down reset logs migrate test test-contracts test-order test-inventory test-gateway \
	test-orchestrator smoke replay lint format format-check typecheck

COMPOSE := docker compose
RUFF := python:3.12-slim
RUFF_VERSION := 0.6.9
PY_TEST_IMAGE := python:3.12-slim

ORDER_TEST_DB := postgresql+psycopg://omniflow:omniflow_dev_only@postgres:5432/omniflow_orders_test
INVENTORY_TEST_DB := postgresql+psycopg://omniflow:omniflow_dev_only@postgres:5432/omniflow_inventory_test
ORCHESTRATOR_TEST_DB := postgresql+psycopg://omniflow:omniflow_dev_only@postgres:5432/omniflow_orchestrator_test

## Bring up the full local stack (build + start), matching the single-command demo requirement.
demo: up
	@echo ""
	@echo "OmniFlow is up."
	@echo "  API Gateway          -> http://localhost:8080/docs"
	@echo "  Order Service        -> http://localhost:8001/docs"
	@echo "  Inventory Service    -> http://localhost:8002/docs"
	@echo "  Fulfillment Orchestrator -> http://localhost:8003/docs"
	@echo "  Redpanda Kafka API   -> localhost:9092"
	@echo "  Jaeger UI            -> http://localhost:16686"
	@echo "  Prometheus           -> http://localhost:9090"
	@echo "  Grafana              -> http://localhost:3000 (anonymous admin access)"

up:
	$(COMPOSE) up --build -d
	$(COMPOSE) ps

down:
	$(COMPOSE) down

## Full teardown including volumes (Postgres + Redpanda data) — use when you want a clean slate.
reset:
	$(COMPOSE) down -v

logs:
	$(COMPOSE) logs -f

## Apply Alembic migrations for every stateful service against the dev databases.
migrate:
	$(COMPOSE) up -d postgres
	$(COMPOSE) run --rm order-service alembic upgrade head
	$(COMPOSE) run --rm inventory-service alembic upgrade head
	$(COMPOSE) run --rm fulfillment-orchestrator alembic upgrade head

## Run every service's test suite against its dedicated *_test database.
test: test-contracts test-order test-inventory test-orchestrator test-gateway

## Shared event-contracts package: schemas, envelope, Kafka helpers, consume-loop retry/DLQ logic.
## httpx is test-only (starlette.testclient, used by test_metrics_setup.py's
## MetricsMiddleware test, requires it even though the package itself never
## imports it) — installed ad hoc here rather than as a pyproject.toml
## dependency, same as pytest/pytest-cov.
test-contracts:
	docker run --rm -v $(CURDIR):/repo -w /repo/services/event-contracts $(PY_TEST_IMAGE) \
		sh -c "pip install --quiet -e . pytest==8.3.3 pytest-cov==5.0.0 httpx==0.27.2 && pytest --cov=event_contracts --cov-report=term-missing"

## entrypoint.sh always runs "alembic upgrade head" before exec-ing its argument,
## so pointing DATABASE_URL at the *_test database and passing pytest as the
## command migrates the test database first, then runs the suite against it.
test-order:
	$(COMPOSE) up -d postgres
	$(COMPOSE) run --rm -e ORDER_SERVICE_DATABASE_URL=$(ORDER_TEST_DB) order-service \
		pytest --cov=app --cov-report=term-missing

test-inventory:
	$(COMPOSE) up -d postgres
	$(COMPOSE) run --rm -e INVENTORY_SERVICE_DATABASE_URL=$(INVENTORY_TEST_DB) inventory-service \
		pytest --cov=app --cov-report=term-missing

test-orchestrator:
	$(COMPOSE) up -d postgres
	$(COMPOSE) run --rm -e ORCHESTRATOR_DATABASE_URL=$(ORCHESTRATOR_TEST_DB) fulfillment-orchestrator \
		pytest --cov=app --cov-report=term-missing

test-gateway:
	$(COMPOSE) build api-gateway
	$(COMPOSE) run --rm api-gateway pytest --cov=app --cov-report=term-missing

## End-to-end smoke test against the real running stack (Postgres, Redpanda,
## every service, both outbox relays, the validator consumer, and the saga
## consumer) — creates a real order and polls until it reaches SHIPPED.
smoke:
	bash scripts/compose_smoke_test.sh

## Replay dead-lettered events. Usage: make replay ARGS="--all" or ARGS="--id <uuid>"
replay:
	$(COMPOSE) run --rm fulfillment-orchestrator python -m app.replay $(ARGS)

## Lint/format run in a throwaway container — no host Python toolchain is assumed (see PROJECT_STATUS.md).
lint:
	docker run --rm -v $(CURDIR):/repo -w /repo $(RUFF) sh -c "pip install --quiet ruff==$(RUFF_VERSION) && ruff check ."

format:
	docker run --rm -v $(CURDIR):/repo -w /repo $(RUFF) sh -c "pip install --quiet ruff==$(RUFF_VERSION) && ruff format ."

format-check:
	docker run --rm -v $(CURDIR):/repo -w /repo $(RUFF) sh -c "pip install --quiet ruff==$(RUFF_VERSION) && ruff format --check ."

## Static type checking (mypy) run in a throwaway container, scoped to each
## service's own `app`/`event_contracts` package (not third-party code, not
## Alembic's generated migration scripts). Non-strict: this codebase never
## adopted mypy before Phase 3, so this checks the type hints that are
## already there (CLAUDE.md's "type hints throughout" convention) without
## retroactively demanding annotations Phase 1/2 code never had.
## Each service's `app` package shares the same name across services (they're
## separate deployables, not a shared namespace), so mypy checks each one in
## its own invocation with that service's directory as the package root —
## same isolation `pytest`/Docker builds already give each service.
typecheck:
	docker run --rm -v $(CURDIR):/repo -w /repo $(PY_TEST_IMAGE) sh -c "\
		pip install --quiet mypy==1.11.2 \
			pydantic==2.9.2 pydantic-settings==2.5.2 sqlalchemy==2.0.35 \
			fastapi==0.115.0 httpx==0.27.2 confluent-kafka==2.5.3 \
			opentelemetry-api==1.27.0 prometheus-client==0.21.0 && \
		(cd services/event-contracts && mypy --ignore-missing-imports event_contracts) && \
		(cd services/order-service && mypy --ignore-missing-imports app) && \
		(cd services/inventory-service && mypy --ignore-missing-imports app) && \
		(cd services/fulfillment-orchestrator && mypy --ignore-missing-imports app) && \
		(cd services/api-gateway && mypy --ignore-missing-imports app)"
