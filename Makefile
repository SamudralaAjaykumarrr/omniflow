.PHONY: demo up down reset logs migrate test test-order test-inventory test-gateway lint format format-check

COMPOSE := docker compose
RUFF := python:3.12-slim
RUFF_VERSION := 0.6.9

ORDER_TEST_DB := postgresql+psycopg://omniflow:omniflow_dev_only@postgres:5432/omniflow_orders_test
INVENTORY_TEST_DB := postgresql+psycopg://omniflow:omniflow_dev_only@postgres:5432/omniflow_inventory_test

## Bring up the full local stack (build + start), matching the single-command demo requirement.
demo: up
	@echo ""
	@echo "OmniFlow is up."
	@echo "  API Gateway   -> http://localhost:8080/docs"
	@echo "  Order Service -> http://localhost:8001/docs"
	@echo "  Inventory Svc -> http://localhost:8002/docs"

up:
	$(COMPOSE) up --build -d
	$(COMPOSE) ps

down:
	$(COMPOSE) down

## Full teardown including volumes (Postgres data) — use when you want a clean slate.
reset:
	$(COMPOSE) down -v

logs:
	$(COMPOSE) logs -f

## Apply Alembic migrations for both stateful services against the dev databases.
migrate:
	$(COMPOSE) up -d postgres
	$(COMPOSE) run --rm order-service alembic upgrade head
	$(COMPOSE) run --rm inventory-service alembic upgrade head

## Run every service's test suite against its dedicated *_test database.
test: test-order test-inventory test-gateway

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

test-gateway:
	$(COMPOSE) build api-gateway
	$(COMPOSE) run --rm api-gateway pytest --cov=app --cov-report=term-missing

## Lint/format run in a throwaway container — no host Python toolchain is assumed (see PROJECT_STATUS.md).
lint:
	docker run --rm -v $(CURDIR):/repo -w /repo $(RUFF) sh -c "pip install --quiet ruff==$(RUFF_VERSION) && ruff check ."

format:
	docker run --rm -v $(CURDIR):/repo -w /repo $(RUFF) sh -c "pip install --quiet ruff==$(RUFF_VERSION) && ruff format ."

format-check:
	docker run --rm -v $(CURDIR):/repo -w /repo $(RUFF) sh -c "pip install --quiet ruff==$(RUFF_VERSION) && ruff format --check ."
