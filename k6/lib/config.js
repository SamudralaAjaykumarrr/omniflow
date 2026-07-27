// Shared configuration for every k6 scenario, driven entirely by env vars so
// the same scripts run unchanged across profiles/environments. Defaults
// point at the real api-gateway container's in-network hostname/port (the
// same address every other service in docker-compose.yml uses to reach it),
// not localhost:8080 — running inside the compose network is what lets this
// suite avoid publishing extra ports or assuming the host machine's network
// stack, while still exercising the real gateway process end to end.
export const BASE_URL = __ENV.K6_BASE_URL || 'http://api-gateway:8000';
export const INVENTORY_URL = __ENV.K6_INVENTORY_URL || 'http://inventory-service:8000';

// A run identifier that's unique per invocation, so customer/email/
// idempotency-key values never collide between separate load-test runs
// against the same persistent dev Postgres volume (same class of problem
// RISKS.md already solved for scripts/compose_smoke_test.sh).
export const RUN_ID = __ENV.LOAD_RUN_ID || `${Date.now()}`;

// Real seeded demo accounts (services/api-gateway/app/seed.py) — login goes
// through the actual bcrypt-verified POST /auth/login, not a bypass. ops can
// create/cancel orders; viewer is read-only, matching the RBAC boundary
// ADR 0009 actually enforces.
export const OPS_EMAIL = __ENV.LOAD_OPS_EMAIL || 'ops@omniflow.local';
export const OPS_PASSWORD =
  __ENV.LOAD_OPS_PASSWORD || __ENV.GATEWAY_SEED_OPS_PASSWORD || 'ops_dev_only';
export const VIEWER_EMAIL = __ENV.LOAD_VIEWER_EMAIL || 'viewer@omniflow.local';
export const VIEWER_PASSWORD =
  __ENV.LOAD_VIEWER_PASSWORD || __ENV.GATEWAY_SEED_VIEWER_PASSWORD || 'viewer_dev_only';

// Must match scripts/load_test_setup.sh's seeded node name / SKU naming
// exactly — the setup script and this suite are two halves of the same
// fixed, deterministic dataset.
export const NODE_NAME = __ENV.LOAD_NODE_NAME || 'load-test-node-1';
export const SKU_PREFIX = __ENV.LOAD_SKU_PREFIX || 'SKU-LOAD';
// Must match scripts/load_test_setup.sh's own default exactly — see that
// script's comment on why 100, not a smaller pool (row-lock contention).
export const SKU_COUNT = parseInt(__ENV.LOAD_SKU_COUNT || '100', 10);

export const JSON_HEADERS = { 'Content-Type': 'application/json' };

export function authHeaders(token) {
  return { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` };
}

export function skuPool() {
  const skus = [];
  for (let i = 1; i <= SKU_COUNT; i++) {
    skus.push(`${SKU_PREFIX}-${String(i).padStart(4, '0')}`);
  }
  return skus;
}

export function randomSku(skus) {
  return skus[Math.floor(Math.random() * skus.length)];
}
