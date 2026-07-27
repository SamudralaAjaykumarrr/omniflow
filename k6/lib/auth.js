import http from 'k6/http';
import { check } from 'k6';
import { BASE_URL, JSON_HEADERS } from './config.js';

// Real login against the real api-gateway (bcrypt-verified credentials, a
// real Postgres `users` table, a real signed JWT) — never a stubbed token.
// Used both by setup() (to fetch reusable tokens for scenarios that aren't
// specifically measuring login) and by the auth_login scenario itself
// (which calls this on every iteration, since login latency/throughput is
// exactly what that scenario measures).
export function login(email, password) {
  const res = http.post(
    `${BASE_URL}/auth/login`,
    JSON.stringify({ email, password }),
    { headers: JSON_HEADERS, tags: { name: 'auth_login' } },
  );
  const ok = check(res, {
    'login: status 200': (r) => r.status === 200,
    'login: has access_token': (r) => {
      try {
        return !!r.json('access_token');
      } catch (_e) {
        return false;
      }
    },
  });
  return { res, ok, token: ok ? res.json('access_token') : null };
}
