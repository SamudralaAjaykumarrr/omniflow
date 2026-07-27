.PHONY: help demo up down reset logs migrate setup-dev test test-contracts test-order test-inventory test-gateway \
	test-orchestrator test-data-platform test-failure-lab smoke replay generate dq-report backfill lint format \
	format-check typecheck coverage security docker-validate docker-build pre-commit ci \
	streaming-up streaming-down inspect-bronze inspect-bronze-rejects inspect-silver \
	inspect-silver-rejects inspect-late-events inspect-gold phase6-smoke phase6-validate clean-phase6 \
	forecast-generate-data forecast-prepare forecast-train-baseline forecast-train-model \
	forecast-evaluate forecast-select forecast-run forecast-inspect forecast-test forecast-smoke \
	forecast-clean-safe forecast-validate \
	dashboard-install dashboard-lint dashboard-format dashboard-format-check dashboard-typecheck \
	dashboard-test dashboard-build dashboard-validate \
	phase8-smoke phase8-validate clean-phase8

COMPOSE := docker compose
RUFF := python:3.12-slim
RUFF_VERSION := 0.6.9
PY_TEST_IMAGE := python:3.12-slim
DEVTOOLS_IMAGE := omniflow-devtools:local
COVERAGE_DIR := $(CURDIR)/coverage-reports/data

# Phase 7 (ops dashboard): no host Node, same "throwaway container" pattern
# as RUFF/PY_TEST_IMAGE above. node_modules lives in the bind-mounted
# directory (persists across `make dashboard-*` runs same as any local npm
# project would); --user + HOME=/tmp runs npm/tsc/vite as the host user
# (not root), so node_modules and every generated file (dist/, *.tsbuildinfo)
# come out host-owned, never needing a manual chown or sudo to touch
# afterward — unlike forecast_artifacts's root-owned-by-default case
# (Makefile's forecast-clean-safe comment), which this sidesteps entirely
# rather than needing a matching throwaway-container cleanup target.
NODE_IMAGE := node:22-alpine
DASHBOARD_DIR := services/ops-dashboard
DASHBOARD_RUN := docker run --rm --user "$(shell id -u):$(shell id -g)" -e HOME=/tmp \
	-v $(CURDIR)/$(DASHBOARD_DIR):/app -w /app $(NODE_IMAGE)

# Measured via `make coverage` against this branch (167 tests, six suites,
# combined statement coverage): 71.6%. Set a few points under that, not at
# the ceiling, so one new untested branch doesn't fail CI outright — see
# docs/phase-5-engineering-quality.md for the full per-service breakdown
# (ranges from event-contracts/order-service/inventory-service/api-gateway
# in the high 80s-90s down to fulfillment-orchestrator at 61% and
# data-platform at 45%, both dragged down by modules that need a live Kafka/
# Spark/HTTP stack to exercise and are covered by `make smoke` instead).
COV_THRESHOLD := 65

ORDER_TEST_DB := postgresql+psycopg://omniflow:omniflow_dev_only@postgres:5432/omniflow_orders_test
INVENTORY_TEST_DB := postgresql+psycopg://omniflow:omniflow_dev_only@postgres:5432/omniflow_inventory_test
ORCHESTRATOR_TEST_DB := postgresql+psycopg://omniflow:omniflow_dev_only@postgres:5432/omniflow_orchestrator_test
FAILURE_LAB_TEST_DB := postgresql+psycopg://omniflow:omniflow_dev_only@postgres:5432/omniflow_failure_lab_test
GATEWAY_TEST_DB := postgresql+psycopg://omniflow:omniflow_dev_only@postgres:5432/omniflow_gateway_test
# Test-only JWT secret — never used outside this suite's own throwaway
# containers (see .env.example / DECISIONS.md "Phase 9" for the real
# local-dev-vs-production distinction this is not trying to make).
GATEWAY_TEST_JWT_SECRET := test-only-jwt-secret-never-used-outside-pytest

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
	@echo "  MinIO Console        -> http://localhost:9001 (data lake: bronze/silver/gold)"
	@echo "  Ops Dashboard        -> http://localhost:3001"

## Build + start the full stack in the background.
up:
	$(COMPOSE) up --build -d
	$(COMPOSE) ps

## Stop the stack, keeping volumes (Postgres/Redpanda/MinIO data survives).
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
	$(COMPOSE) run --rm api-gateway alembic upgrade head

## Run every service's test suite against its dedicated *_test database.
test: test-contracts test-order test-inventory test-orchestrator test-gateway test-data-platform test-failure-lab

## Shared event-contracts package: schemas, envelope, Kafka helpers, consume-loop retry/DLQ logic.
## httpx is test-only (starlette.testclient, used by test_metrics_setup.py's
## MetricsMiddleware test, requires it even though the package itself never
## imports it) — installed ad hoc here rather than as a pyproject.toml
## dependency, same as pytest/pytest-cov.
test-contracts:
	@mkdir -p $(COVERAGE_DIR)
	docker run --rm -v $(CURDIR):/repo -w /repo/services/event-contracts \
		-e COVERAGE_FILE=/repo/coverage-reports/data/.coverage.event-contracts \
		$(PY_TEST_IMAGE) \
		sh -c "pip install --quiet -e . pytest==8.3.3 pytest-cov==5.0.0 httpx==0.27.2 && pytest --cov=event_contracts --cov-report=term-missing"

## entrypoint.sh always runs "alembic upgrade head" before exec-ing its argument,
## so pointing DATABASE_URL at the *_test database and passing pytest as the
## command migrates the test database first, then runs the suite against it.
test-order:
	@mkdir -p $(COVERAGE_DIR)
	$(COMPOSE) up -d postgres
	$(COMPOSE) run --rm -e ORDER_SERVICE_DATABASE_URL=$(ORDER_TEST_DB) \
		-e COVERAGE_FILE=/coverage-data/.coverage.order-service -v $(COVERAGE_DIR):/coverage-data \
		order-service pytest --cov=app --cov-report=term-missing

test-inventory:
	@mkdir -p $(COVERAGE_DIR)
	$(COMPOSE) up -d postgres
	$(COMPOSE) run --rm -e INVENTORY_SERVICE_DATABASE_URL=$(INVENTORY_TEST_DB) \
		-e COVERAGE_FILE=/coverage-data/.coverage.inventory-service -v $(COVERAGE_DIR):/coverage-data \
		inventory-service pytest --cov=app --cov-report=term-missing

test-orchestrator:
	@mkdir -p $(COVERAGE_DIR)
	$(COMPOSE) up -d postgres
	$(COMPOSE) run --rm -e ORCHESTRATOR_DATABASE_URL=$(ORCHESTRATOR_TEST_DB) \
		-e COVERAGE_FILE=/coverage-data/.coverage.fulfillment-orchestrator -v $(COVERAGE_DIR):/coverage-data \
		fulfillment-orchestrator pytest --cov=app --cov-report=term-missing

## Phase 9 (JWT/RBAC): api-gateway now owns a `users` table/database, same
## migrate-then-test pattern as order-service/inventory-service.
test-gateway:
	@mkdir -p $(COVERAGE_DIR)
	$(COMPOSE) up -d postgres
	$(COMPOSE) build api-gateway
	$(COMPOSE) run --rm -e GATEWAY_DATABASE_URL=$(GATEWAY_TEST_DB) \
		-e JWT_SECRET_KEY=$(GATEWAY_TEST_JWT_SECRET) -e GATEWAY_SEED_DEMO_USERS=false \
		-e COVERAGE_FILE=/coverage-data/.coverage.api-gateway -v $(COVERAGE_DIR):/coverage-data \
		api-gateway pytest --cov=app --cov-report=term-missing

## Phase 8 (Failure laboratory) service: scenario catalog, trigger/reset API,
## the 10 scenario implementations, and the poison-message consumer.
test-failure-lab:
	@mkdir -p $(COVERAGE_DIR)
	$(COMPOSE) up -d postgres
	$(COMPOSE) build failure-lab
	$(COMPOSE) run --rm -e FAILURE_LAB_DATABASE_URL=$(FAILURE_LAB_TEST_DB) \
		-e JWT_SECRET_KEY=$(GATEWAY_TEST_JWT_SECRET) \
		-e COVERAGE_FILE=/coverage-data/.coverage.failure-lab -v $(COVERAGE_DIR):/coverage-data \
		failure-lab pytest --cov=app --cov-report=term-missing

## Bronze/Silver/Gold Spark jobs, DQ checks, synthetic generator, backfill
## tooling. No live Kafka/MinIO needed for its own suite — every test runs
## a local Spark session against static/file data, not the real stack — so
## unlike the other test-* targets, this doesn't need `up -d` first. Any of
## the four data-platform compose services share the same image/Dockerfile;
## spark-gold is used here only as a stand-in to run pytest.
test-data-platform:
	@mkdir -p $(COVERAGE_DIR)
	$(COMPOSE) build spark-gold
	$(COMPOSE) run --rm -e COVERAGE_FILE=/coverage-data/.coverage.data-platform -v $(COVERAGE_DIR):/coverage-data \
		spark-gold pytest --cov=app --cov-report=term-missing

## End-to-end smoke test against the real running stack (Postgres, Redpanda,
## every service, both outbox relays, the validator consumer, and the saga
## consumer) — creates a real order and polls until it reaches SHIPPED.
smoke:
	bash scripts/compose_smoke_test.sh

## Replay dead-lettered events. Usage: make replay ARGS="--all" or ARGS="--id <uuid>"
replay:
	$(COMPOSE) run --rm fulfillment-orchestrator python -m app.replay $(ARGS)

## Generate synthetic order-lifecycle traffic onto Kafka, for exercising
## the data platform without a live order moving through the real saga.
## Usage: make generate ARGS="--orders 200 --dead-letters 5 --seed 1"
generate:
	$(COMPOSE) run --rm spark-gold python -m app.generator $(ARGS)

## Run data-quality checks for one date (default: today, UTC) against the
## real Bronze/Silver/late-events/rejects Parquet and write a report to
## MinIO. Usage: make dq-report ARGS="--date 2026-07-25"
dq-report:
	$(COMPOSE) run --rm spark-gold python -m app.dq.report $(ARGS)

## Backfill/reprocess Silver (from Bronze) or Gold (from Silver) over a
## bounded date range; add --apply to swap into the live path.
## Usage: make backfill ARGS="silver --event-type order.created --from-date 2026-07-25 --to-date 2026-07-25"
backfill:
	$(COMPOSE) run --rm spark-gold python -m app.backfill $(ARGS)

## Start only the Spark streaming pipeline (bronze/silver/gold + lag poller) against an already-up stack (Redpanda/MinIO/Postgres).
streaming-up:
	$(COMPOSE) up -d spark-bronze spark-silver spark-gold lag-poller

## Stop only the Spark streaming pipeline containers — leaves Redpanda/MinIO/Postgres and every volume/checkpoint untouched.
streaming-down:
	$(COMPOSE) stop spark-bronze spark-silver spark-gold lag-poller

## Inspect Bronze objects in MinIO (object count/bytes by event_type partition + sample keys).
inspect-bronze:
	$(COMPOSE) run --rm spark-gold python -m app.inspect bronze

## Inspect Bronze's malformed-JSON quarantine (unparseable Kafka records, never written to Bronze itself).
inspect-bronze-rejects:
	$(COMPOSE) run --rm spark-gold python -m app.inspect bronze_rejects

## Inspect Silver objects in MinIO (object count/bytes by event_type partition + sample keys).
inspect-silver:
	$(COMPOSE) run --rm spark-gold python -m app.inspect silver

## Inspect Silver's schema/business-validation quarantine (silver_rejects).
inspect-silver-rejects:
	$(COMPOSE) run --rm spark-gold python -m app.inspect silver_rejects

## Inspect late-arriving events routed out of Silver (late_events).
inspect-late-events:
	$(COMPOSE) run --rm spark-gold python -m app.inspect late_events

## Inspect Gold aggregates in MinIO (object count/bytes by dataset partition + sample keys).
inspect-gold:
	$(COMPOSE) run --rm spark-gold python -m app.inspect gold

## Phase 6 end-to-end smoke test: synthetic traffic (incl. duplicate/late/
## malformed injection) -> real Kafka -> Bronze/Silver/Gold -> DQ report,
## plus a Bronze restart/checkpoint check. Usage: make phase6-smoke
phase6-smoke:
	bash scripts/phase6_smoke_test.sh

## Everything that gates Phase 6 as done: unit/Spark tests, the smoke test above, and the existing project CI gate.
phase6-validate: test-data-platform phase6-smoke ci

## Remove disposable local Phase 6 dev output only (pytest/mypy/ruff caches
## under services/data-platform) — deliberately never touches MinIO data,
## checkpoints, Kafka topics, or any Docker volume (hard restriction: this
## repo never deletes project data as part of routine/automated cleanup).
clean-phase6:
	rm -rf services/data-platform/.pytest_cache services/data-platform/.mypy_cache \
		services/data-platform/.ruff_cache
	find services/data-platform -type d -name __pycache__ -exec rm -rf {} +

# --- Phase 6 (the actual roadmap phase): demand forecasting ---------------
# `app.forecasting` is a pandas/scikit-learn batch pipeline (no Spark/JVM
# session needed) that lives inside the data-platform package/image; every
# target below reuses the already-built spark-gold image/container as its
# runner, same as app.generator/app.dq.report/app.backfill above. Default
# paths (no ARGS override) read/write real MinIO under
# s3a://<bucket>/forecasting/... — see docs/phase-6-demand-forecasting.md.

## Generate deterministic synthetic demand history. Usage: make forecast-generate-data ARGS="--output s3a://omniflow/forecasting/synthetic_history/history.parquet"
forecast-generate-data:
	$(COMPOSE) run --rm spark-gold python -m app.forecasting.cli generate-history $(ARGS)

## Build the feature-engineered forecasting dataset (grain: SKU x location x date) from synthetic history.
forecast-prepare:
	$(COMPOSE) run --rm spark-gold python -m app.forecasting.cli prepare $(ARGS)

## Train the seasonal-naive baseline. Usage: make forecast-train-baseline ARGS="--run-id my-run"
forecast-train-baseline:
	$(COMPOSE) run --rm spark-gold python -m app.forecasting.cli train-baseline $(ARGS)

## Train the HistGradientBoostingRegressor secondary model. Usage: make forecast-train-model ARGS="--run-id my-run"
forecast-train-model:
	$(COMPOSE) run --rm spark-gold python -m app.forecasting.cli train-secondary $(ARGS)

## Evaluate baseline + secondary against the chronological validation split. Usage: make forecast-evaluate ARGS="--run-id my-run"
forecast-evaluate:
	$(COMPOSE) run --rm spark-gold python -m app.forecasting.cli evaluate $(ARGS)

## Select the champion model from measured evaluation metrics (never a hardcoded winner). Usage: make forecast-select ARGS="--run-id my-run"
forecast-select:
	$(COMPOSE) run --rm spark-gold python -m app.forecasting.cli select $(ARGS)

## Run the full local forecasting pipeline end to end: generate -> prepare -> train baseline + secondary -> evaluate -> select -> future forecast.
forecast-run:
	$(COMPOSE) run --rm spark-gold python -m app.forecasting.cli run $(ARGS)

## Inspect forecast output, evaluation metrics, champion selection, or the prepared dataset. Usage: make forecast-inspect ARGS="forecast"
forecast-inspect:
	$(COMPOSE) run --rm spark-gold python -m app.forecasting.cli inspect $(ARGS)

## Run the forecasting unit + pipeline test suite only (pure pandas/scikit-learn — no live Kafka/MinIO needed; the full suite already runs these via test-data-platform).
forecast-test:
	$(COMPOSE) build spark-gold
	$(COMPOSE) run --rm spark-gold pytest tests/forecasting -v

## End-to-end forecasting smoke test: small deterministic history -> dataset -> both models -> evaluation -> champion -> future forecast -> inspect, entirely local (redirected away from MinIO — no live stack needed).
forecast-smoke:
	bash scripts/forecast_smoke_test.sh

## Remove disposable local forecasting output only (local model artifacts + the local smoke-test scratch dir) — never touches MinIO, Docker volumes, checkpoints, or any Bronze/Silver/Gold data.
## Runs via a throwaway container (not a bare host `rm -rf`): both dirs are written by spark-gold's container user (root), so a host-user `rm` would hit "Permission denied" — this avoids needing sudo.
forecast-clean-safe:
	docker run --rm -v $(CURDIR)/services/data-platform:/target $(PY_TEST_IMAGE) \
		rm -rf /target/forecasting_artifacts /target/.forecast_smoke_output

## Everything that gates Phase 6 (demand forecasting) as done: unit/pipeline tests, the smoke test, and the existing project CI gate.
forecast-validate: forecast-test forecast-smoke ci

# --- Phase 7: ops dashboard (React + TypeScript) ---------------------------

## Install/refresh the dashboard's npm dependencies into the cached node_modules volume. Run once, or after editing package.json.
dashboard-install:
	$(DASHBOARD_RUN) npm install

## ESLint (flat config) over the dashboard's TypeScript/TSX sources.
dashboard-lint:
	$(DASHBOARD_RUN) npm run lint

## Auto-format the dashboard tree with Prettier (rewrites files in place).
dashboard-format:
	$(DASHBOARD_RUN) npm run format

## Same as dashboard-format, but fails instead of rewriting — the CI-safe variant.
dashboard-format-check:
	$(DASHBOARD_RUN) npm run format:check

## Static type checking (tsc --noEmit) for the dashboard.
dashboard-typecheck:
	$(DASHBOARD_RUN) npx tsc -b --noEmit

## Unit + component tests (vitest + Testing Library), single run (no watch).
dashboard-test:
	$(DASHBOARD_RUN) npm test

## Production build (tsc -b && vite build) — same build the Docker image runs; writes to services/ops-dashboard/dist.
dashboard-build:
	$(DASHBOARD_RUN) npm run build

## Everything that gates Phase 7 (ops dashboard) as done, mirroring `ci`'s fail-fast ordering.
dashboard-validate: dashboard-install dashboard-format-check dashboard-lint dashboard-typecheck dashboard-test dashboard-build

# --- Phase 8: failure laboratory (10 deterministic failure scenarios) -----

## End-to-end Phase 8 smoke test: brings up the full stack, triggers all 10
## failure-lab scenarios against the real running services, asserts each
## reaches PASSED/RECOVERED, resets every scenario, then reruns all 10 a
## second time to prove they're safe to rerun.
phase8-smoke:
	bash scripts/phase8_smoke_test.sh

## Everything that gates Phase 8 (failure laboratory) as done: unit/API
## tests, the smoke test above, and the existing project CI gate.
phase8-validate: test-failure-lab phase8-smoke ci

## Remove disposable local Phase 8 dev output only (pytest/mypy/ruff caches
## under services/failure-lab) — never touches Postgres/Redpanda/MinIO data
## or any Docker volume.
clean-phase8:
	rm -rf services/failure-lab/.pytest_cache services/failure-lab/.mypy_cache \
		services/failure-lab/.ruff_cache
	find services/failure-lab -type d -name __pycache__ -exec rm -rf {} +

## Lint/format run in a throwaway container — no host Python toolchain is assumed (see PROJECT_STATUS.md).
lint:
	docker run --rm -v $(CURDIR):/repo -w /repo $(RUFF) sh -c "pip install --quiet ruff==$(RUFF_VERSION) && ruff check ."

## Auto-format the whole tree with ruff (rewrites files in place).
format:
	docker run --rm -v $(CURDIR):/repo -w /repo $(RUFF) sh -c "pip install --quiet ruff==$(RUFF_VERSION) && ruff format ."

## Same as format, but fails instead of rewriting — the CI-safe variant.
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
			opentelemetry-api==1.27.0 prometheus-client==0.21.0 \
			pyspark==3.5.3 pyarrow==17.0.0 s3fs==2024.9.0 \
			pandas==2.2.3 numpy==2.1.2 scikit-learn==1.5.2 joblib==1.4.2 \
			pyjwt==2.9.0 passlib==1.7.4 bcrypt==4.0.1 && \
		(cd services/event-contracts && mypy --config-file=/repo/pyproject.toml event_contracts) && \
		(cd services/order-service && mypy --config-file=/repo/pyproject.toml app) && \
		(cd services/inventory-service && mypy --config-file=/repo/pyproject.toml app) && \
		(cd services/fulfillment-orchestrator && mypy --config-file=/repo/pyproject.toml app) && \
		(cd services/api-gateway && mypy --config-file=/repo/pyproject.toml app) && \
		(cd services/data-platform && mypy --config-file=/repo/pyproject.toml app) && \
		(cd services/failure-lab && mypy --config-file=/repo/pyproject.toml app)"

## Build the shared devtools image (ruff/mypy/pytest/coverage/bandit/pip-audit/
## pre-commit, pinned in infra/docker/devtools/Dockerfile) used by coverage,
## security, and pre-commit. Run this once (and again after editing that
## Dockerfile); the other targets assume the image already exists rather than
## rebuilding it on every invocation, so a stale image is a `make setup-dev`
## away, not a silent no-op.
setup-dev:
	docker build -f infra/docker/devtools/Dockerfile -t $(DEVTOOLS_IMAGE) .

## Run every suite with coverage instrumentation on, combine the six
## per-service data files (each written by the matching test-* target above
## into coverage-reports/data/) into one root coverage.xml, and enforce
## COV_THRESHOLD. The combine step bind-mounts the repo at both /app and
## /repo because that's what each service's own container used as its
## coverage-recording root (see each Dockerfile's WORKDIR vs. test-contracts'
## -w /repo/services/event-contracts) — pyproject.toml's [tool.coverage.paths]
## reconciles the two into one relative path per file.
coverage:
	@mkdir -p $(COVERAGE_DIR)
	@rm -f $(COVERAGE_DIR)/.coverage.* $(CURDIR)/.coverage $(CURDIR)/coverage.xml
	$(MAKE) test
	docker run --rm -v $(CURDIR):/app -v $(CURDIR):/repo -w /app $(DEVTOOLS_IMAGE) sh -c "\
		coverage combine coverage-reports/data && \
		coverage xml -o coverage.xml; \
		status=\$$?; \
		chown $(shell id -u):$(shell id -g) .coverage coverage.xml 2>/dev/null || true; \
		if [ \$$status -ne 0 ]; then exit \$$status; fi; \
		coverage report --fail-under=$(COV_THRESHOLD)"

## Zero-cost static security scanning: bandit (SAST) over every service's
## own app/event_contracts package, pip-audit (dependency CVE scan, via the
## free/unauthenticated public OSV.dev database — not a paid service) over
## every service's requirements.txt. Findings fail the target and are never
## silently dropped; the handful of PYSEC IDs below are the sole exception,
## and each is individually justified in RISKS.md #20, not blanket-ignored:
##   - PYSEC-2026-1845 (pytest, local /tmp/pytest-of-{user} collision): a
##     test-only dependency in a single-user container; no other local user
##     exists to exploit it.
##   - PYSEC-2026-113 (pyarrow use-after-free): the advisory itself states
##     the vulnerable C++ API is "not exposed in language bindings (Python,
##     ...)" — unreachable from this codebase's pyarrow usage.
##   - PYSEC-2026-{161,248,249,1941,1943,2280,2281} (starlette, pulled in
##     transitively by fastapi==0.115.0): fixes require starlette >=1.0,
##     which fastapi==0.115.0 cannot resolve against (verified: pip reports
##     ResolutionImpossible) — needs a coordinated FastAPI major-version
##     upgrade across all four HTTP services with full re-test, tracked as
##     its own follow-up, not a same-pass dependency bump. This codebase
##     doesn't read request.url.hostname/netloc for auth (grepped, only
##     .path is used, for logging), and the stack isn't internet-facing
##     (ADR/RISKS' existing local-demo-only posture), which bounds the
##     practical exploitability of the host-header-confusion CVEs today.
## pip's own CVEs (path traversal in wheel/tar extraction) aren't ignored
## here — they're fixed outright by pinning pip==26.1.2 in every Dockerfile.
IGNORE_VULN_IDS := PYSEC-2026-1845 PYSEC-2026-113 PYSEC-2026-161 PYSEC-2026-248 \
	PYSEC-2026-249 PYSEC-2026-1941 PYSEC-2026-1943 PYSEC-2026-2280 PYSEC-2026-2281
IGNORE_VULN_FLAGS := $(foreach id,$(IGNORE_VULN_IDS),--ignore-vuln $(id))

security:
	docker run --rm -v $(CURDIR):/repo -w /repo $(DEVTOOLS_IMAGE) sh -c "\
		echo '--- bandit (SAST) ---' && \
		bandit -r services/event-contracts/event_contracts services/order-service/app \
			services/inventory-service/app services/fulfillment-orchestrator/app \
			services/api-gateway/app services/data-platform/app services/failure-lab/app \
			-ll -x '*/tests/*,*/migrations/versions/*' && \
		echo '--- pip-audit (dependency CVEs; accepted-risk IDs documented in RISKS.md #20 excluded, never silently) ---' && \
		status=0; \
		for req in services/order-service/requirements.txt services/inventory-service/requirements.txt \
			services/fulfillment-orchestrator/requirements.txt services/api-gateway/requirements.txt \
			services/data-platform/requirements.txt services/failure-lab/requirements.txt; do \
			echo \">>> \$$req\"; \
			pip-audit -r \"\$$req\" --strict $(IGNORE_VULN_FLAGS) || status=1; \
		done; \
		echo '>>> services/event-contracts (pyproject.toml deps, installed into devtools image)'; \
		pip-audit --strict --local $(IGNORE_VULN_FLAGS) || status=1; \
		exit \$$status"

## Validate docker-compose.yml resolves cleanly (no `docker compose up` — no
## containers started, no cost, catches YAML/interpolation/schema errors).
docker-validate:
	$(COMPOSE) config --quiet
	@echo "docker-compose.yml is valid."

## Build every application service's image (not the infra images — postgres/
## redpanda/minio/prometheus/grafana/jaeger/otel-collector are pulled, not
## built here). event-contracts has no image of its own; it's installed as a
## local dependency into the other five during their own builds. ops-dashboard
## (Phase 7) builds its own npm dependencies inside its own Dockerfile stage,
## independent of dashboard-install's cached volume.
docker-build:
	$(COMPOSE) build order-service inventory-service fulfillment-orchestrator api-gateway spark-gold ops-dashboard failure-lab

## Run pre-commit against every tracked file, not just staged ones — this is
## the "does the whole tree pass" check, distinct from the git-hook install
## step (not done here; nothing in this repo runs pre-commit automatically
## on commit, see docs/phase-5-engineering-quality.md for why that's a
## deliberate choice for a solo portfolio repo).
pre-commit:
	docker run --rm -v $(CURDIR):/repo -w /repo $(DEVTOOLS_IMAGE) sh -c "\
		git config --global --add safe.directory /repo && pre-commit run --all-files --show-diff-on-failure"

## Full local CI gate, in the order a real pipeline would fail fastest:
## formatting/lint (seconds) before type-checking (tens of seconds) before
## tests+coverage (minutes) before security scanning before the Docker
## Compose/image validation that only matters once the code itself is known
## good. Mirrors .github/workflows/ci.yml job-for-job. dashboard-validate
## (Phase 7) runs alongside the Python gates, same fail-fast ordering.
ci: format-check lint typecheck coverage security dashboard-validate docker-validate docker-build
	@echo ""
	@echo "make ci: all Phase 5 quality gates passed."

## Self-documenting help: lists every target with a `##` comment on the line
## directly above it, in file order.
help:
	@echo "OmniFlow — available make targets:"
	@awk '/^## /{ comment = comment (comment ? " " : "") substr($$0, 4); next } \
		/^[a-zA-Z][a-zA-Z0-9_-]*:/{ if (comment) { split($$1, parts, ":"); printf "  \033[36m%-20s\033[0m %s\n", parts[1], comment; comment = "" } else { comment = "" } }' \
		$(MAKEFILE_LIST)
