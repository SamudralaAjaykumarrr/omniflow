# ADR 0008: Monorepo Layout and Service Boundaries

## Status
Accepted

## Context
The system has four independently deployable backend services, a shared event
contract, a multi-stage data platform, a frontend, infra-as-code, and a large
documentation set. A single developer (or one agent session at a time) is
doing all the work, and everything must build/run/test through one
`docker compose up` — favoring a monorepo with clear internal boundaries over
many small repos, which would add cross-repo versioning overhead with no
corresponding team-scaling benefit here.

## Decision
```
/services/api-gateway
/services/order-service
/services/inventory-service
/services/fulfillment-orchestrator
/services/event-contracts        (shared, versioned Python package: envelope + payload schemas)
/data-platform/streaming         (PySpark bronze/silver/gold jobs)
/data-platform/quality           (data-quality checks + report generator)
/data-platform/forecasting       (synthetic data gen, baseline + model, evaluation)
/frontend                        (React + TypeScript ops dashboard)
/infra/docker                    (Dockerfiles, docker-compose.yml)
/infra/terraform                 (AWS IaC, authored not applied)
/observability                   (OTel collector config, Prometheus, Grafana dashboards)
/docs                            (architecture, ADRs, event catalog, guides)
/scripts                         (seed data, event generator, failure-lab scripts)
```
Each service under `/services` and `/data-platform` owns its own
`pyproject.toml`/dependencies and Dockerfile — they are independently
buildable and independently testable, sharing only the `event-contracts`
package (installed as a path/local dependency, not copy-pasted schemas) so
producers and consumers cannot silently drift on event shape.

## Consequences
- One repo, one `docker compose up`, one CI pipeline with per-service jobs —
  matches the "single documented command" requirement directly.
- Shared code is limited to `event-contracts`; anything else duplicated
  across services is a deliberate boundary, not an oversight (e.g. each
  service has its own DB session/config setup rather than a shared "common"
  package, to keep services genuinely independently deployable).
- A future real split into separate repos-per-service is possible without
  restructuring internals, since boundaries already match deployable units.

## Alternatives considered
- **Polyrepo (one repo per service)**: adds real overhead (versioning the
  shared event-contracts package across repos, multi-repo CI coordination)
  with no benefit for a single-contributor project that must run as one
  system via one command; rejected.
- **Single flat repo with no service subdivision (one FastAPI app, modules
  instead of services)**: would not demonstrate independent service
  deployability, independent Dockerfiles, or the service-boundary reasoning
  the spec asks for; rejected.
