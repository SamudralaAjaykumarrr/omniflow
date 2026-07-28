# Demo Guide

A reliable, time-bounded path for showing OmniFlow to a recruiter or
interviewer. Everything here runs entirely locally against Docker Compose —
no AWS, no paid services, no credentials beyond the dev-only demo accounts
already committed to `.env.example`.

## Prerequisites

- Docker + Docker Compose (this is the only host requirement — no host
  Python/Node/Java/Terraform needed).
- ~15Gi RAM and 8 CPUs free is what this project has been built and tested
  against; it may run on less but hasn't been verified there.
- Ports free on localhost: `8080` (gateway), `8001`–`8004` (direct service
  access), `3000` (Grafana), `3001` (dashboard), `9090` (Prometheus),
  `16686` (Jaeger), `9001` (MinIO console).

## Clean startup

```bash
cp .env.example .env
make demo        # docker compose up --build, prints service URLs when healthy
```

No specific startup time is claimed here — it depends on the host and
whether images are already built; watch `docker compose ps` for every
service to reach `healthy`/`running` before starting the demo.

## Demo accounts (local dev-only, already in `.env.example`)

| Role | Email | Password |
|---|---|---|
| Admin | `admin@omniflow.local` | `admin_dev_only` |
| Ops | `ops@omniflow.local` | `ops_dev_only` |
| Viewer | `viewer@omniflow.local` | `viewer_dev_only` |

These are seeded idempotently at every api-gateway startup. They are not
secrets — they're documented, dev-only defaults meant for exactly this kind
of local demo.

## Entry points

| What | URL |
|---|---|
| Ops Dashboard (start here for a UI walkthrough) | http://localhost:3001 |
| API Gateway / Swagger (start here for an API walkthrough) | http://localhost:8080/docs |
| Jaeger (traces) | http://localhost:16686 |
| Prometheus (metrics) | http://localhost:9090 |
| Grafana (dashboards, anonymous admin access) | http://localhost:3000 |
| MinIO Console (bronze/silver/gold browser) | http://localhost:9001 |
| Failure Laboratory API (direct) | http://localhost:8004/docs |

## 5-minute demo path

1. Open the Ops Dashboard, log in as `ops@omniflow.local`.
2. Create an order (Orders → Create Order). Watch its status move through
   the lifecycle on the Orders detail screen.
3. Open Saga Monitor — show the saga instance reaching `COMPLETED`.
4. Open Failure Laboratory, trigger `payment-decline`, and show the run
   reaching `PASSED` with the compensation (inventory released) visible in
   the run's evidence.
5. Open Observability and show a live Prometheus query (e.g. request rate).

## 15-minute technical demo path

Everything in the 5-minute path, plus:

6. **Order → fulfillment workflow in depth**: create an order, then open
   Jaeger and find the trace — show it spans the gateway, order service, and
   every saga step the orchestrator drove, in one trace, across the Kafka
   boundary.
7. **Dashboard walkthrough**: Inventory & Fulfillment Nodes (show the
   node-scoring formula's inputs), Dead Letter Queue (show the Replay
   button), Data Quality / Data Platform / Demand Forecasting screens (note
   which are live vs. clearly-labeled local mock data — the dashboard
   itself displays a `MOCK DATA` banner on the ones without a live read
   path yet).
8. **Data platform / forecasting walkthrough**:
   ```bash
   make generate      # synthetic traffic onto real Kafka topics
   make dq-report      # data-quality report against live MinIO data
   make forecast-run    # full forecasting pipeline: generate -> train -> evaluate -> select -> forecast
   ```
   Then inspect output: `make inspect-gold`, `make forecast-inspect ARGS="forecast"`.
9. **Failure injection and recovery**: trigger `saga-crash-resume` or
   `downstream-outage` from Failure Laboratory — show the scenario's
   evidence (timestamps, IDs touched, recovery path), then reset it.
10. **Observability demonstration**: open Grafana's provisioned dashboard —
    request rate/latency, Kafka consumer lag, saga duration, DB pool.

## Cleanup

```bash
make down    # stop containers, keep volumes (fast restart)
make reset   # stop containers and remove volumes (clean slate)
```

## Troubleshooting

- **A service shows unhealthy in `docker compose ps`**: give it another
  minute — some services (Spark jobs, MinIO init) take longer to become
  ready than the FastAPI services. Check `make logs` for the specific
  service.
- **Dashboard shows a proxy error**: confirm `api-gateway`/`inventory-
  service`/`fulfillment-orchestrator`/`prometheus` are all healthy — the
  dashboard's nginx proxies to all four.
- **Login fails**: confirm you copied `.env.example` to `.env` before
  `make demo` — the seed passwords come from there.
- **Want a clean environment for a repeat demo**: `make reset` then
  `make demo` again.

## Commands that should never be run

- `terraform plan` or `terraform apply` from `infra/terraform/` against a
  real AWS account, or any AWS API call — this Terraform is authored and
  validated only (`make tf-validate-all`), never applied, and no AWS
  credentials should ever be introduced into this environment (ADR 0007).
- Anything that installs system packages or paid services on the host.

## Local demo vs. AWS Terraform

Everything in this guide runs against the local `docker compose` stack. The
Terraform under `infra/terraform/` describes what an AWS deployment of this
same architecture would look like (ECS Fargate, RDS, MSK, S3, EMR
Serverless) — it has been formatted, initialized, and validated
(`make tf-validate-all`, zero warnings) but never planned or applied. There
is no live AWS deployment of this project to demo; `infra/terraform/README.md`
documents the named gaps that would need closing before there would be one.
