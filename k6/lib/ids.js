// Deterministic-enough unique-identifier helpers for load-test data.
// Not cryptographically secure — this is test-data uniqueness, not security
// — but sufficient to guarantee no two VUs/iterations/profile runs ever
// submit the same customer_id, email, or Idempotency-Key, which would
// otherwise make order creation idempotently return a *cached* order
// instead of exercising a real fresh insert.

// RFC4122-shaped v4 UUID string — order-service's CreateOrderRequest
// validates customer_id as a real uuid.UUID (pydantic), so this must be
// well-formed, not just unique text.
export function uuidv4() {
  let seed = Date.now() + Math.random() * 1e9;
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (seed + Math.random() * 16) % 16 | 0;
    seed = Math.floor(seed / 16);
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

// A plain unique string (no format constraint) for Idempotency-Key headers
// and customer emails — scoped by RUN_ID + VU + iteration + a random
// tie-breaker so concurrent VUs across the same iteration count never
// collide either.
export function uniqueToken(prefix, runId, vu, iter) {
  return `${prefix}-${runId}-${vu}-${iter}-${Math.floor(Math.random() * 1e6)}`;
}
