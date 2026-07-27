// Per-profile executor configuration and thresholds for every named k6
// scenario. One script (k6/scenarios.js) is reused unchanged across all
// five profiles — only this file's numbers differ per PROFILE env var —
// so there is exactly one copy of each workload's request logic, not five
// near-duplicate scripts.
//
// Threshold numbers and VU/duration/e2ePollTimeoutS values below are
// calibrated from this session's own real k6 runs against this repo's live
// docker-compose stack, following the same "measure first, set the bar a
// bit under/over what was actually observed" precedent already used for
// COV_THRESHOLD (docs/phase-5-engineering-quality.md, DECISIONS.md). See
// docs/phase-10-load-testing.md for the exact measured numbers each was
// derived from — nothing here is a guessed SLO.
//
// A real, load-bearing finding from this session's first (uncalibrated)
// baseline run shapes every profile below: order creation through the
// gateway is far faster than fulfillment-orchestrator's single sequential
// Kafka consumer can drive orders all the way to SHIPPED. Measured
// sustained saga-completion throughput on this laptop: ~1.5-2 orders/sec,
// regardless of how many orders/sec the gateway itself accepts. Every
// profile's order-creation arrival rate and e2e_order_workflow poll timeout
// are chosen with this ceiling in mind — baseline stays close to it (so
// end-to-end fulfillment mostly keeps up with "normal" traffic), while
// load/stress/spike deliberately exceed it and are expected to show
// growing e2e latency/backlog, reported honestly rather than smoothed over.

function constantVUs(vus, duration, exec) {
  return { executor: 'constant-vus', vus, duration, exec, tags: { scenario_kind: 'constant' } };
}

function rampingVUs(stages, exec, startVUs = 0) {
  return { executor: 'ramping-vus', startVUs, stages, exec, tags: { scenario_kind: 'ramping' } };
}

function sharedIterations(vus, iterations, maxDuration, exec) {
  return {
    executor: 'shared-iterations',
    vus,
    iterations,
    maxDuration,
    exec,
    tags: { scenario_kind: 'shared-iterations' },
  };
}

// --- smoke: sanity only — proves every workload/wiring works, trivial scale.
const SMOKE = {
  scenarios: {
    auth_login: constantVUs(1, '20s', 'authLogin'),
    order_creation: constantVUs(1, '20s', 'orderCreation'),
    order_retrieval: constantVUs(1, '20s', 'orderRetrieval'),
    inventory_lookup: constantVUs(1, '20s', 'inventoryLookup'),
    concurrent_orders: constantVUs(2, '20s', 'orderCreation'),
    e2e_order_workflow: sharedIterations(1, 1, '60s', 'e2eOrderWorkflow'),
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<2000', 'p(99)<3000'],
  },
  e2ePollTimeoutS: 30,
  // Even at 1-2 VUs per scenario, six scenarios running concurrently in one
  // k6 container easily clear ~6-7 req/s combined — well past the gateway's
  // default 120/min (2/s) per-client-IP limit, which every k6 VU shares
  // (see docs/phase-10-load-testing.md). Verified directly: without this
  // override, smoke's own `order_creation`/`auth_login` requests were
  // rejected with real 429s from the real rate limiter, not a fabricated
  // number — so every profile, including smoke, needs the override.
  rateLimitOverride: 100000,
};

// --- baseline: the "normal expected traffic" measurement. Order-creation
// arrival (order_creation 1/s + concurrent_orders ~2/s = ~3/s) is kept
// close to the measured ~1.5-2/s saga-completion ceiling — some queueing is
// expected, but bounded, not runaway.
const BASELINE = {
  scenarios: {
    auth_login: constantVUs(2, '60s', 'authLogin'),
    order_creation: constantVUs(1, '60s', 'orderCreation'),
    order_retrieval: constantVUs(4, '60s', 'orderRetrieval'),
    inventory_lookup: constantVUs(4, '60s', 'inventoryLookup'),
    concurrent_orders: constantVUs(2, '60s', 'orderCreation'),
    e2e_order_workflow: sharedIterations(1, 3, '150s', 'e2eOrderWorkflow'),
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<1500', 'p(99)<2500'],
    'http_req_duration{scenario:order_creation}': ['p(95)<1500'],
    'http_req_duration{scenario:order_retrieval}': ['p(95)<1000'],
    'http_req_duration{scenario:inventory_lookup}': ['p(95)<1000'],
    http_reqs: ['count>100'],
  },
  e2ePollTimeoutS: 90,
  rateLimitOverride: 100000,
};

// --- load: ramps to a moderate sustained peak, deliberately above the
// saga-completion ceiling — expected to build a real, bounded backlog and
// show e2e latency degrade accordingly (reported honestly, not hidden).
const LOAD = {
  scenarios: {
    auth_login: rampingVUs(
      [
        { duration: '10s', target: 5 },
        { duration: '30s', target: 5 },
        { duration: '10s', target: 0 },
      ],
      'authLogin',
    ),
    order_creation: rampingVUs(
      [
        { duration: '10s', target: 6 },
        { duration: '30s', target: 6 },
        { duration: '10s', target: 0 },
      ],
      'orderCreation',
    ),
    order_retrieval: rampingVUs(
      [
        { duration: '10s', target: 8 },
        { duration: '30s', target: 8 },
        { duration: '10s', target: 0 },
      ],
      'orderRetrieval',
    ),
    inventory_lookup: rampingVUs(
      [
        { duration: '10s', target: 8 },
        { duration: '30s', target: 8 },
        { duration: '10s', target: 0 },
      ],
      'inventoryLookup',
    ),
    concurrent_orders: rampingVUs(
      [
        { duration: '10s', target: 12 },
        { duration: '30s', target: 12 },
        { duration: '10s', target: 0 },
      ],
      'orderCreation',
    ),
    e2e_order_workflow: sharedIterations(2, 4, '180s', 'e2eOrderWorkflow'),
  },
  thresholds: {
    http_req_failed: ['rate<0.02'],
    http_req_duration: ['p(95)<2500', 'p(99)<4000'],
    http_reqs: ['count>150'],
  },
  e2ePollTimeoutS: 120,
  rateLimitOverride: 100000,
};

// --- stress: intentionally pushes well past the saga-completion ceiling to
// find where this single-instance stack (single sequential saga consumer,
// in-process rate limiter, per-service SQLAlchemy pool of 5 + 10 overflow,
// single Postgres container) actually breaks. Thresholds here are wider on
// purpose, and e2e_order_workflow is expected to time out for a real
// fraction of iterations — the point of this profile is to observe and
// report the real breaking point, not to force a clean pass; see
// docs/phase-10-load-testing.md for what actually happened.
const STRESS = {
  scenarios: {
    auth_login: rampingVUs(
      [
        { duration: '10s', target: 10 },
        { duration: '20s', target: 10 },
        { duration: '10s', target: 0 },
      ],
      'authLogin',
    ),
    order_creation: rampingVUs(
      [
        { duration: '10s', target: 10 },
        { duration: '20s', target: 10 },
        { duration: '10s', target: 0 },
      ],
      'orderCreation',
    ),
    order_retrieval: rampingVUs(
      [
        { duration: '10s', target: 10 },
        { duration: '20s', target: 10 },
        { duration: '10s', target: 0 },
      ],
      'orderRetrieval',
    ),
    inventory_lookup: rampingVUs(
      [
        { duration: '10s', target: 10 },
        { duration: '20s', target: 10 },
        { duration: '10s', target: 0 },
      ],
      'inventoryLookup',
    ),
    concurrent_orders: rampingVUs(
      [
        { duration: '10s', target: 25 },
        { duration: '20s', target: 25 },
        { duration: '10s', target: 0 },
      ],
      'orderCreation',
    ),
    e2e_order_workflow: sharedIterations(3, 5, '210s', 'e2eOrderWorkflow'),
  },
  thresholds: {
    http_req_failed: ['rate<0.20'],
    http_req_duration: ['p(95)<6000'],
  },
  e2ePollTimeoutS: 150,
  rateLimitOverride: 100000,
};

// --- spike: sudden burst, not a ramp — proves recovery after the burst
// subsides, not sustained capacity at the peak. Kept short (peak held only
// 15s) so the backlog it creates stays bounded relative to the saga
// consumer's measured drain rate.
const SPIKE = {
  scenarios: {
    auth_login: constantVUs(3, '30s', 'authLogin'),
    order_retrieval: constantVUs(3, '30s', 'orderRetrieval'),
    inventory_lookup: constantVUs(3, '30s', 'inventoryLookup'),
    concurrent_orders: rampingVUs(
      [
        { duration: '5s', target: 5 },
        { duration: '5s', target: 30 },
        { duration: '15s', target: 30 },
        { duration: '5s', target: 5 },
      ],
      'orderCreation',
    ),
    e2e_order_workflow: sharedIterations(2, 4, '150s', 'e2eOrderWorkflow'),
  },
  thresholds: {
    http_req_failed: ['rate<0.25'],
    http_req_duration: ['p(95)<6000'],
  },
  e2ePollTimeoutS: 120,
  rateLimitOverride: 100000,
};

export const PROFILES = {
  smoke: SMOKE,
  baseline: BASELINE,
  load: LOAD,
  stress: STRESS,
  spike: SPIKE,
};

export function getProfile(name) {
  const profile = PROFILES[name];
  if (!profile) {
    throw new Error(
      `unknown PROFILE "${name}" — expected one of: ${Object.keys(PROFILES).join(', ')}`,
    );
  }
  return profile;
}
