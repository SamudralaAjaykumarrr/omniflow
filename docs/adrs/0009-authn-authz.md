# ADR 0009: Authentication and Authorization — JWT + RBAC

## Status
Accepted

## Context
The API Gateway and dashboard need real authentication (not a placeholder) to
demonstrate the security practices the spec asks for: JWT auth, role-based
authorization, secure password hashing, audit events for sensitive operations
— without adding an external identity provider dependency to the local,
no-paid-services demo.

## Decision
Self-contained JWT auth: `users` table with `email`, `password_hash` (bcrypt
via `passlib`), `role` (`admin`, `ops`, `viewer`). Login issues a short-lived
JWT (signed with a secret from environment configuration, never committed)
carrying `sub` (user id) and `role`. The API Gateway verifies the JWT on every
protected route and enforces role checks via a FastAPI dependency (e.g.
cancelling an order or triggering a failure-lab scenario requires `ops` or
`admin`; read-only dashboard views accept `viewer`). Sensitive actions
(cancellation, failure-lab triggers, replay of dead-lettered events) write an
`audit_log` row: actor, action, target, timestamp.

## Consequences
- No external IdP/OAuth provider needed for local evaluation, matching the
  "no paid cloud services" constraint.
- Password hashing, JWT verification, and RBAC are all testable in-process
  (unit + API integration tests) without network calls to a third party.
- This is deliberately not a full OAuth2/OIDC implementation (no refresh-token
  rotation, no external SSO) — named explicitly as the simplification made and
  the natural upgrade path for real enterprise use in `docs/security.md` and
  the interview guide.

## Alternatives considered
- **Session cookies + server-side session store**: viable, but JWT better
  demonstrates stateless verification across multiple services (API Gateway,
  and any service that needs to check a caller's role directly) without a
  shared session store becoming another dependency; chosen for that reason.
- **Third-party auth provider (Auth0/Cognito)**: real production systems
  often do this, but it requires an external paid/managed service account,
  which conflicts with the local, no-paid-services requirement; named as the
  production upgrade path instead.
