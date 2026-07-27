# Phase 7: Operations Dashboard

## Purpose / business problem

`docs/product-requirements.md` requirement 12: "Present business and
technical state in an operations dashboard aimed at the people who run the
system, not at shoppers." Everything built in Phases 1-6 (order/inventory
APIs, the saga orchestrator, the event bus, the Bronze/Silver/Gold data
platform, demand forecasting) is real and running, but the only way to see
any of it was `curl`/Swagger, `docker compose logs`, or Grafana/Jaeger/
Prometheus/MinIO's own UIs — no single surface presents order, inventory,
saga, DLQ, pipeline-health, data-quality, and forecast state together for
an ops user. This phase builds that surface.

## Scope

React + TypeScript single-page app (`services/ops-dashboard`), served by
nginx in its own Docker image, added as an `ops-dashboard` Compose service.
It is a **read-mostly, thin presentation layer**: it reads existing
services' real APIs directly, writes only through the same endpoints a
script or `curl` already could (create/cancel an order, an advisory stock
check), and reimplements no business logic client-side (`docs/architecture.md`'s
existing "Dashboard: presentation ... does not reimplement logic
client-side" boundary, unchanged since Phase 0).

**Not in scope**, and explicitly not attempted:
- Any change to `order-service`/`inventory-service`/`fulfillment-orchestrator`/
  `api-gateway`/`data-platform` beyond `docker-compose.yml` gaining one new
  service block. No new backend endpoints were added anywhere, even where
  the dashboard would have benefited from one (see "Missing API contracts"
  below) — the roadmap scopes this phase as a frontend build against what
  already exists.
- JWT/RBAC login. ADR 0009 designed a `users`/JWT scheme, but Phase 9 never
  implemented it (`PROJECT_STATUS.md`: "JWT/RBAC finalization ... still not
  started") — there is no `users` table, no login route, nothing to
  authenticate this dashboard's own users against. Building a login screen
  with nothing real behind it would be exactly the kind of fabricated
  capability `CLAUDE.md` forbids, so the dashboard is unauthenticated,
  matching the backend's current, honest state. This is named again as a
  limitation below, not glossed over.
- Phase 8 (Failure Laboratory). Not started (`PROJECT_STATUS.md`), so its
  screen is an inert, clearly-labeled preview of the planned scenario
  catalog, not a working control panel.

## The ten screens — how this list was derived

The roadmap table (`PROJECT_STATUS.md` / `README.md`) says only "React +
TypeScript, 10 screens" — no enumeration exists anywhere in the repo (`grep`
confirmed before starting). The ten below were derived from two documents
that predate this phase and describe target state:
`docs/architecture.md`'s container diagram ("Ops Dashboard: Executive, ops,
DQ, forecast, failure-lab UIs") and `docs/product-requirements.md`'s
dashboard-facing functional requirements (order-stream view, DLQ viewer,
inventory/stockout risk, pipeline health, forecast, failure-lab triggers).

| # | Screen | Route |
|---|---|---|
| 1 | Overview (executive summary) | `/` |
| 2 | Orders | `/orders`, `/orders/:orderId` |
| 3 | Inventory & Fulfillment Nodes | `/inventory` |
| 4 | Saga Monitor | `/saga-monitor` |
| 5 | Dead Letter Queue | `/dead-letters` |
| 6 | Observability / Pipeline Health | `/observability` |
| 7 | Data Quality | `/data-quality` |
| 8 | Data Platform / Gold Datasets | `/data-platform` |
| 9 | Demand Forecasting | `/forecasting` |
| 10 | Failure Laboratory (Phase 8 preview) | `/failure-lab` |

## Existing backend surface used (real, not mocked)

Found by reading every service's `app/routes.py` and `app/schemas.py`
before writing any frontend code — this is the actual, current API
surface, not an assumed one:

| Service | Endpoint | Used by |
|---|---|---|
| API Gateway | `POST /api/orders`, `GET /api/orders/{id}`, `GET /api/orders/{id}/history`, `POST /api/orders/{id}/cancel` | Orders, Order detail |
| API Gateway | `GET /api/inventory/stock/{sku}/{node_id}` | Inventory |
| API Gateway | `GET /readyz` | Overview |
| Inventory Service (direct) | `GET /fulfillment-nodes`, `POST /stock/check` | Inventory |
| Fulfillment Orchestrator (direct) | `GET /saga-instances`, `GET /saga-instances/{order_id}`, `GET /dead-letters`, `GET /healthz` | Saga Monitor, Dead Letter Queue, Overview |
| Prometheus (direct) | `GET /api/v1/query`, `GET /api/v1/query_range` | Observability |

Inventory Service and the Fulfillment Orchestrator are reached **directly**
(not through the gateway, which doesn't proxy their read-only surfaces) —
same-network container-to-container calls via nginx, exactly like the
gateway itself already calls them over REST for the saga.

## Missing API contracts / where mock data was necessary

- **No list-all-orders endpoint.** `order-service` only exposes
  `GET /orders/{id}` and `GET /orders/{id}/history` — confirmed by reading
  `services/order-service/app/routes.py`. Rather than add one (out of this
  phase's scope — see "Scope" above), the Orders screen tracks order IDs
  **client-side** (`useTrackedOrders`, `localStorage`) — created via the
  dashboard's own "create demo order" form or entered manually — then
  fetches each one's real, current state individually. This is real data
  about real orders, just client-curated instead of server-listed. Labeled
  as such directly in the screen's own copy, not hidden.
- **No read API over MinIO.** `docs/architecture.md` names this outright:
  "Dashboard reads DQ report / forecast / gold summaries via a thin read
  API" is listed as target state, and the diagram's own caption calls the
  Ops Dashboard container "not yet built" for exactly this reason. Three
  screens are affected, all clearly labeled with a persistent `MOCK DATA`
  banner naming the specific gap, never blended silently with real data:
  - **Data Quality** — fixture shaped exactly like `app.dq.report`'s real
    JSON output (`services/data-platform/app/dq/report.py`'s schema:
    reconciliation, schema-rejection-rate, duplicate-rate, late-event-rate,
    freshness).
  - **Data Platform** — fixtures shaped like the 10 Gold datasets from
    `docs/data-pipeline.md`'s table.
  - **Demand Forecasting** — split into two provenances, not conflated:
    the champion-selection WAPE/MAE/RMSE numbers shown are **real**,
    copied verbatim from this repo's own `TEST_RESULTS.md` (a measured,
    point-in-time result, not a live query, and labeled as exactly that);
    the day-by-day forecast curve is illustrative/mock, since
    `app.forecasting`'s real output has no browser-facing read path yet.
- **Failure Laboratory** — Phase 8 doesn't exist yet at all. The screen is
  an inert catalog of the ten planned scenarios (each named after a real,
  already-documented mechanism — saga compensation, retry/backoff, DLQ
  routing, the dedup/late-event paths, etc. — see
  `src/api/mock/failureLab.ts`), every trigger button permanently
  `disabled`, with its own `MOCK DATA`-style banner explaining why.

## API integration approach: same-origin nginx proxy, no new backend

The dashboard's own Docker image runs nginx in front of the static build.
`nginx.conf` reverse-proxies four path prefixes to the real containers on
the same Compose network:

| Path prefix | Proxies to |
|---|---|
| `/gw/` | `api-gateway:8000` |
| `/inventory-api/` | `inventory-service:8000` |
| `/orchestrator-api/` | `fulfillment-orchestrator:8000` |
| `/prom-api/` | `prometheus:9090` |

The browser only ever calls same-origin paths — no backend service needed
a CORS change. `src/api/client.ts`'s `API_BASE` constants match these
prefixes exactly, and `vite.config.ts`'s dev-server proxy mirrors them
(against `localhost:<published-port>` instead of container DNS names) for
`npm run dev` iteration outside Compose.

**Two real bugs found and fixed, not just the first assumed to be enough**:

1. A straightforward `proxy_pass http://api-gateway:8000/;` makes nginx
   resolve that hostname once at **startup** and refuse to start at all
   ("host not found in upstream") if it isn't resolvable yet — which would
   take down the whole dashboard, including the static SPA, over one
   not-yet-ready dependency, and makes the image impossible to smoke-test
   standalone. Fixed by assigning each proxy target to a variable
   (`set $upstream_gateway ...; proxy_pass $upstream_gateway;`) with
   `resolver 127.0.0.11` (Docker's embedded DNS) declared once — this
   defers resolution to **request time**, so an unreachable upstream
   returns a 502 for just that one route instead of crashing nginx.
   Verified directly: `nginx -t` failed with the exact "host not found in
   upstream" error before the fix and passed after; a standalone
   `docker run` of the image (no other containers on its network) served
   `/` and SPA routes with `200` and `/gw/healthz` with a clean `502`
   rather than refusing to start.
2. **Found only by actually running the full stack**, not by the
   standalone smoke test above: nginx only auto-strips a location's
   matched prefix when `proxy_pass`'s target is a *literal* URI — with the
   *variable* target the fix above requires, nginx instead forwards the
   client's full original request URI unchanged, so `GET /gw/healthz`
   reached `api-gateway` as literally `/gw/healthz` (a real 404, not the
   intended `/healthz`) once `api-gateway`/`inventory-service`/
   `fulfillment-orchestrator`/`prometheus` were actually up to receive it —
   invisible to the standalone smoke test, which never had a real upstream
   to be wrong against. A second bug compounded the first attempted fix:
   adding `rewrite ^/gw/(.*)$ /$1 break;` *after* the `set` line left every
   proxied request 500-ing with nginx's own "using uninitialized
   `upstream_gateway` variable" warning — `break` halts every remaining
   rewrite-phase directive in that location, including a `set` that comes
   after it, so `set` must be ordered *before* `rewrite` for both to take
   effect. Fixed and verified with real traffic against the live Compose
   stack (`docker compose up`, all four upstreams actually running): a real
   order created and read back through `/gw/api/orders`, real fulfillment
   nodes/saga instances/dead letters through their respective proxies, and
   a real Prometheus `up` query through `/prom-api/` — not just a 200/502
   smoke check.
3. **Found only after 1 and 2 were both fixed and traffic was already
   flowing correctly**: `docker compose ps` still reported the container
   **unhealthy**. nginx's `listen 80;` only binds IPv4, but this image's
   `wget` resolves `localhost` to `::1` (IPv6) first — both the
   Dockerfile's own `HEALTHCHECK` and `docker-compose.yml`'s separate,
   overriding `healthcheck:` block were querying an address nginx never
   listens on, independent of the service actually working. Confirmed
   directly (`wget http://127.0.0.1:80` inside the container: OK;
   `wget http://[::1]:80`: connection refused) before fixing both
   healthcheck definitions to query `127.0.0.1` explicitly. After
   rebuilding and force-recreating (`docker compose up -d --force-recreate
   ops-dashboard` — a plain `up -d` alone did not pick up the rebuilt
   image against an already-existing container of the same name/tag, a
   separate Compose behavior worth knowing), `docker compose ps` reports
   `omniflow-ops-dashboard-1  Up ... (healthy)`.

## Component architecture

```
src/
  api/            typed client (client.ts, orders.ts, inventory.ts,
                   orchestrator.ts, metrics.ts) + mock/ (clearly-labeled
                   fallback fixtures) + types.ts (hand-mirrors the Pydantic
                   response models — no shared codegen exists between the
                   Python services and this app)
  components/
    layout/        AppShell, Sidebar (the 10 nav items), TopBar
    common/         StatCard, StatusBadge, DataTable, LoadingState,
                    EmptyState, ErrorState, MockDataNotice, BarChart,
                    LineChart (hand-rolled SVG, dataviz-skill palette/marks)
    forms/          CreateOrderForm, CancelOrderForm, StockCheckForm
  hooks/            useAsync (loading/error/success + polling + retry),
                    useTrackedOrders (localStorage-backed order tracking)
  pages/            one file per screen
```

`useAsync` never conflates "no data yet" with "failed": every screen
explicitly renders one of loading / empty / error / success, never a blank
screen or a stale previous render on failure. Deps-array changes (e.g.
navigating to a different order ID) reset to loading synchronously during
render — React's documented "adjusting state during rendering" pattern —
rather than via a `setState` inside the effect body, which
`eslint-plugin-react-hooks@7`'s stricter rules flag.

## Routing

`react-router-dom` v7 in plain client-side ("library") mode —
`<BrowserRouter>`/`<Routes>`/`<Route>`/`<Link>`/`<NavLink>`/`useNavigate`/
`useParams` only. No data-router APIs (`createBrowserRouter`, loaders,
actions), no RSC, no SSR. This is directly relevant to the accepted-risk
note below, not incidental.

## Accessibility

- Every form field has a real `<label>` (visible or `.visually-hidden`),
  native `required`/`type`/`min`/`step` constraints, and an `aria-live`
  error region.
- `DataTable` renders a real `<caption>` and `<th scope="col">`; interactive
  rows are real `role="button"` + `tabIndex={0}` with Enter/Space handling
  — not click-only.
- `LoadingState`/`ErrorState` use `role="status"`/`role="alert"`;
  `MockDataNotice` uses `role="note"`.
- Status is never color-alone: `StatusBadge` pairs an icon + text label
  with one of the dataviz skill's four reserved status colors
  (good/warning/serious/critical), never a categorical hue.
- Charts (`BarChart`/`LineChart`) are real `role="img"` with a computed
  `aria-labelledby`/`aria-label` per chart and per bar; line charts render
  a legend once 2+ series are present and a hover/focus crosshair +
  tooltip, per the dataviz skill's interaction rule.

## Real vs. mock data — summary table

| Screen | Data | Provenance |
|---|---|---|
| Overview | Gateway/orchestrator health, saga counts, DLQ count | Live |
| Orders | Order create/read/cancel/history | Live (order IDs client-tracked, see above) |
| Inventory & Nodes | Nodes, stock lookup, stock pre-check | Live |
| Saga Monitor | Saga instances | Live |
| Dead Letter Queue | Dead-lettered events | Live |
| Observability | Prometheus metrics (request rate, latency, Kafka lag, saga duration, DB pool, inventory conflicts) | Live |
| Data Quality | DQ report | Mock (labeled) — see "Missing API contracts" |
| Data Platform | Gold datasets | Mock (labeled) |
| Demand Forecasting | Champion WAPE/MAE/RMSE | Real, measured (`TEST_RESULTS.md`), not live |
| Demand Forecasting | Forecast curve | Mock (labeled) |
| Failure Laboratory | Scenario catalog | Mock/inert (Phase 8 not started) |

## Testing strategy

Vitest + React Testing Library, 50 tests across 14 files: the API client
(success/error/network-failure paths), `useAsync`/`useTrackedOrders`,
every shared component (`StatusBadge`, `DataTable` keyboard activation,
`LoadingState`/`EmptyState`/`ErrorState`/`MockDataNotice`,
`BarChart`/`LineChart`), both forms (validation, submit, error surfacing —
mocking the real API modules with `vi.spyOn`, not a fetch-level mock, so a
form's own logic is what's under test), `OverviewPage` (loading → success
and loading → error), `DataQualityPage`, `FailureLabPage` (every trigger
button disabled), and an `App` routing smoke test (all 10 nav links
present, navigation works, unknown routes hit the 404 page).

No coverage-threshold gate was added for the dashboard (unlike the
Python suites' `make coverage`) — this phase didn't attempt to set one
without a measured baseline to set it from; a future pass could add one
the same way Phase 5 did for the Python suites.

## Docker Compose integration

New service `ops-dashboard` (`docker-compose.yml`): built from
`services/ops-dashboard/Dockerfile` (multi-stage — `node:22-alpine` builds
the static app, `nginx:1.27-alpine` serves it), published on `3001` (`3000`
is already Grafana's), depends on `api-gateway`/`inventory-service`/
`fulfillment-orchestrator`/`prometheus` all reaching `service_healthy`
(the proxy's request-time DNS resolution means the dashboard would still
start and serve its static UI even if one of these were slow, but ordering
them this way keeps `make demo`'s first real request working immediately
rather than transiently 502-ing).

## Makefile targets

All run inside `node:22-alpine` throwaway containers (no host Node,
matching every other language's toolchain in this repo) as the host UID/GID
(`--user "$(id -u):$(id -g)"`, `HOME=/tmp`) so `node_modules`, `dist/`, and
`*.tsbuildinfo` never end up root-owned on the host:

```
make dashboard-install       # npm install
make dashboard-lint          # eslint (flat config)
make dashboard-format        # prettier --write
make dashboard-format-check  # prettier --check (CI-safe)
make dashboard-typecheck     # tsc -b --noEmit
make dashboard-test          # vitest run
make dashboard-build         # tsc -b && vite build
make dashboard-validate      # all of the above, in fail-fast order
```

`make ci` now runs `dashboard-validate` alongside the existing Python
gates, and `make docker-build` builds the `ops-dashboard` image alongside
the five existing application images.

## Local demonstration

```bash
make demo   # or: docker compose up --build -d ops-dashboard (plus its deps)
# -> http://localhost:3001
```

Create a demo order from the Orders screen (writes a real order through the
gateway), watch it move through the saga on the Saga Monitor screen, look
up its assigned node's stock on Inventory, and check Observability for the
resulting request-rate/latency samples — an end-to-end path through real
data, not a scripted demo mode.

## Limitations

- **Unauthenticated.** No JWT/RBAC exists in the backend yet (Phase 9
  remainder) — see "Scope" above. Every action this dashboard can take
  (create/cancel an order, a stock check) is exactly what an unauthenticated
  `curl` against these same endpoints could already do; the dashboard adds
  no new privilege.
- **Order listing is client-curated, not server-listed** (see "Missing API
  contracts"). An order created outside this browser session (another
  script, another machine) won't appear until its ID is entered manually.
- ~~**DLQ replay is documented, not wired up.**~~ **Closed in Phase 8**
  (`docs/phase-8-failure-laboratory.md`): fulfillment-orchestrator gained a
  real `POST /dead-letters/{id}/replay` endpoint (needed for the
  downstream-outage failure scenario's own recovery step), and the Dead
  Letter Queue screen now has a working "Replay" button backed by it,
  alongside the still-available `make replay` CLI.
- **Data Quality / Data Platform / Forecasting curve are mock**, clearly
  labeled, pending a real MinIO read API (`docs/architecture.md`'s own
  named target state, not new scope invented by this phase).
- **`react-router-dom`'s current advisories are accepted, not silently
  ignored** — see `RISKS.md`. Every currently-published version has at
  least one `npm audit`-flagged advisory (RSC-mode CSRF bypass on 7.12+;
  older 6.x/7.x releases carry several SSR/data-router/RSC-specific ones
  instead); this dashboard uses none of RSC, SSR, or the data-router
  loader/action APIs (plain `BrowserRouter`/`Routes`/`Link`, grepped to
  confirm), so the vulnerable code paths are unreachable here — the same
  accepted-risk pattern this repo already uses for `starlette`/`pyarrow`
  (`RISKS.md` #20).
- **No coverage threshold** for the dashboard's own test suite (see
  "Testing strategy").

## Acceptance criteria

- [x] React + TypeScript, responsive, professional UI
- [x] Reusable component architecture (layout/common/forms, no
      screen-specific one-off duplicated markup for tables/states/charts)
- [x] Routing and navigation (10 screens, all reachable from the sidebar)
- [x] Loading, empty, success, and error states on every data-bearing screen
- [x] Accessible forms and tables (labels, roles, keyboard activation)
- [x] Typed API client, real contracts mirrored from the actual Pydantic schemas
- [x] Realistic local data from existing APIs where available (6 of 10
      screens are fully live; a 7th mixes real measured + mock)
- [x] Mock/fallback data clearly labeled everywhere it's used, never blended silently
- [x] Unit and component tests (50 tests, 14 files)
- [x] Linting, formatting, type-checking, production build all pass
- [x] Docker Compose integration (`ops-dashboard` service, healthcheck)
- [x] Makefile targets, wired into `make ci`
- [x] This document, plus `README.md`/`PROJECT_STATUS.md`/`TEST_RESULTS.md`/
      `DECISIONS.md`/`RISKS.md` updated
- [x] All existing backend/streaming/forecasting/CI/Docker functionality
      preserved (no existing service's code changed — only
      `docker-compose.yml`, `Makefile`, `.github/workflows/ci.yml`, and a
      new root `.dockerignore` touched outside `services/ops-dashboard/`)

## Zero-cost compliance

No paid service, no cloud dependency, no new external API. `npm install`
pulls public npm packages (same zero-cost class as `pip install` from
PyPI, already this repo's norm); the built image runs entirely inside the
existing local Docker Compose network.
