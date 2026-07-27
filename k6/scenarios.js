// OmniFlow Phase 10 load test — k6.
//
// Every request in every scenario below goes through the real api-gateway
// container (BASE_URL), the same process every other phase's traffic goes
// through — never a direct call to order-service/inventory-service for
// anything that's actually measured. Authentication is the real
// POST /auth/login flow (bcrypt-verified credentials, a real signed JWT),
// never a stubbed/forged token.
//
// setup() does three things that are deliberately NOT part of the measured
// traffic: (1) logging in once for ops/viewer tokens reused by scenarios
// that aren't themselves measuring login, (2) looking up the fixed
// load-test fulfillment node's id directly against inventory-service (the
// same "read-only lookup, not part of the workload" precedent
// scripts/compose_smoke_test.sh already uses for its own seeding step), and
// (3) creating a small, fixed pool of real orders through the gateway for
// order_retrieval to read back repeatedly. None of this counts toward this
// run's http_req_duration/http_req_failed thresholds — k6 only applies
// thresholds to the default/scenario functions' own samples, not setup().
//
// Usage: PROFILE=<smoke|baseline|load|stress|spike> k6 run scenarios.js
// (see Makefile's load-* targets, which set PROFILE and every other env var).
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Rate } from 'k6/metrics';

import {
  BASE_URL,
  INVENTORY_URL,
  RUN_ID,
  OPS_EMAIL,
  OPS_PASSWORD,
  VIEWER_EMAIL,
  VIEWER_PASSWORD,
  NODE_NAME,
  authHeaders,
  skuPool,
  randomSku,
} from './lib/config.js';
import { login } from './lib/auth.js';
import { uuidv4, uniqueToken } from './lib/ids.js';
import { getProfile } from './lib/profiles.js';

const PROFILE_NAME = __ENV.PROFILE || 'smoke';
const PROFILE = getProfile(PROFILE_NAME);

const ORDER_POOL_SIZE = parseInt(__ENV.LOAD_ORDER_POOL_SIZE || '10', 10);
// Per-profile default (see lib/profiles.js's e2ePollTimeoutS — calibrated
// against this session's own measured saga-completion throughput), still
// overridable directly for ad hoc runs.
const E2E_POLL_TIMEOUT_S = parseInt(
  __ENV.LOAD_E2E_POLL_TIMEOUT_S || String(PROFILE.e2ePollTimeoutS || 30),
  10,
);

export const e2eWorkflowDuration = new Trend('e2e_workflow_duration_s', true);
export const e2eWorkflowSuccess = new Rate('e2e_workflow_success');

export const options = {
  scenarios: PROFILE.scenarios,
  thresholds: PROFILE.thresholds,
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

// `vuLabel`/`iterLabel` default to k6's own __VU/__ITER globals, which only
// exist inside a VU-context exec function — setup()/teardown() run outside
// any VU, so they pass their own explicit labels instead (see setup() below).
function createOrder(token, skus, vuLabel, iterLabel) {
  const sku = randomSku(skus);
  const customerId = uuidv4();
  const email = `${uniqueToken('loadtest', RUN_ID, vuLabel, iterLabel)}@example.com`;
  const idempotencyKey = uniqueToken('idem', RUN_ID, vuLabel, iterLabel);
  const body = JSON.stringify({
    customer_id: customerId,
    customer_email: email,
    customer_display_name: 'Load Test Customer',
    items: [{ sku, qty: 1, unit_price: 9.99 }],
  });
  const headers = authHeaders(token);
  headers['Idempotency-Key'] = idempotencyKey;
  const res = http.post(`${BASE_URL}/api/orders`, body, { headers, tags: { name: 'order_creation' } });
  return res;
}

// --- setup(): one-time, not part of the measured workload (see header note).
export function setup() {
  const opsLogin = login(OPS_EMAIL, OPS_PASSWORD);
  if (!opsLogin.ok) {
    throw new Error(
      'setup: could not log in as the seeded ops account — is the stack up and ' +
        'GATEWAY_SEED_DEMO_USERS enabled? (make load-setup / make demo)',
    );
  }
  const viewerLogin = login(VIEWER_EMAIL, VIEWER_PASSWORD);
  if (!viewerLogin.ok) {
    throw new Error('setup: could not log in as the seeded viewer account.');
  }

  const nodesRes = http.get(`${INVENTORY_URL}/fulfillment-nodes`);
  if (nodesRes.status !== 200) {
    throw new Error(`setup: GET /fulfillment-nodes failed with status ${nodesRes.status}`);
  }
  const nodes = nodesRes.json();
  const node = nodes.find((n) => n.name === NODE_NAME);
  if (!node) {
    throw new Error(
      `setup: no fulfillment node named "${NODE_NAME}" found — run ` +
        '`make load-setup` first to seed load-test data.',
    );
  }

  const skus = skuPool();

  const orderPool = [];
  for (let i = 0; i < ORDER_POOL_SIZE; i++) {
    const res = createOrder(opsLogin.token, skus, 'setup', i);
    if (res.status !== 201) {
      throw new Error(
        `setup: seed order ${i} failed with status ${res.status}: ${res.body}`,
      );
    }
    orderPool.push(res.json('id'));
  }

  return {
    opsToken: opsLogin.token,
    viewerToken: viewerLogin.token,
    nodeId: node.id,
    skus,
    orderPool,
  };
}

// --- Scenario: repeated real login (ADR 0009's POST /auth/login).
export function authLogin() {
  const account = Math.random() < 0.5 ? [OPS_EMAIL, OPS_PASSWORD] : [VIEWER_EMAIL, VIEWER_PASSWORD];
  login(account[0], account[1]);
  sleep(1);
}

// --- Scenario: order creation (also reused, at a different executor scale,
// as the "concurrent_orders" scenario — see lib/profiles.js).
export function orderCreation(data) {
  const res = createOrder(data.opsToken, data.skus, __VU, __ITER);
  check(res, {
    'order_creation: status 201': (r) => r.status === 201,
    'order_creation: has id': (r) => {
      try {
        return !!r.json('id');
      } catch (_e) {
        return false;
      }
    },
  });
  sleep(1);
}

// --- Scenario: order retrieval against the fixed order pool created in setup().
export function orderRetrieval(data) {
  const orderId = data.orderPool[Math.floor(Math.random() * data.orderPool.length)];
  const res = http.get(`${BASE_URL}/api/orders/${orderId}`, {
    headers: authHeaders(data.viewerToken),
    tags: { name: 'order_retrieval' },
  });
  check(res, { 'order_retrieval: status 200': (r) => r.status === 200 });
  sleep(1);
}

// --- Scenario: inventory stock lookup.
export function inventoryLookup(data) {
  const sku = randomSku(data.skus);
  const res = http.get(`${BASE_URL}/api/inventory/stock/${sku}/${data.nodeId}`, {
    headers: authHeaders(data.viewerToken),
    tags: { name: 'inventory_lookup' },
  });
  check(res, { 'inventory_lookup: status 200': (r) => r.status === 200 });
  sleep(1);
}

// --- Scenario: full order -> fulfillment saga workflow, create then poll to
// a terminal status through the real gateway. Deliberately run at a much
// lower iteration count than the other scenarios (see lib/profiles.js) —
// each iteration holds a polling loop open for up to E2E_POLL_TIMEOUT_S
// seconds, which is expensive relative to a single fire-and-check request.
export function e2eOrderWorkflow(data) {
  const createRes = createOrder(data.opsToken, data.skus, __VU, __ITER);
  const created = check(createRes, { 'e2e: order created (201)': (r) => r.status === 201 });
  if (!created) {
    e2eWorkflowSuccess.add(false);
    return;
  }
  const orderId = createRes.json('id');
  const start = Date.now();
  let finalStatus = null;
  const deadline = start + E2E_POLL_TIMEOUT_S * 1000;
  while (Date.now() < deadline) {
    const res = http.get(`${BASE_URL}/api/orders/${orderId}`, {
      headers: authHeaders(data.viewerToken),
      tags: { name: 'e2e_order_workflow_poll' },
    });
    if (res.status === 200) {
      const status = res.json('status');
      if (status === 'SHIPPED' || status === 'FAILED') {
        finalStatus = status;
        break;
      }
    }
    sleep(1);
  }
  const durationS = (Date.now() - start) / 1000;
  e2eWorkflowDuration.add(durationS);
  e2eWorkflowSuccess.add(finalStatus === 'SHIPPED');
  check(
    { finalStatus },
    { 'e2e: reached SHIPPED within timeout': (r) => r.finalStatus === 'SHIPPED' },
  );
}
