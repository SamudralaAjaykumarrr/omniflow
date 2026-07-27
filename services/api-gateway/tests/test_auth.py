"""api-gateway's own Phase 9 (JWT/RBAC, ADR 0009) surface: login against the
real `users` table (bcrypt-hashed passwords), `/auth/me`, and the 401/403
boundary on protected routes against a real Postgres-backed dependency
chain (event_contracts.auth's own dependency unit tests already cover the
JWT mechanics in isolation — this file proves the gateway's own wiring of
it end to end: real DB lookup, real bcrypt verify, real dependency-injected
route protection)."""

import jwt as pyjwt

from app.config import get_settings
from app.security import hash_password, verify_password


class TestPasswordHashing:
    def test_hash_is_not_the_plaintext_password(self):
        assert hash_password("correct-horse-battery-staple") != "correct-horse-battery-staple"

    def test_correct_password_verifies(self):
        hashed = hash_password("correct-horse-battery-staple")
        assert verify_password("correct-horse-battery-staple", hashed) is True

    def test_wrong_password_does_not_verify(self):
        hashed = hash_password("correct-horse-battery-staple")
        assert verify_password("wrong-password", hashed) is False

    def test_same_password_hashes_differently_each_time(self):
        # bcrypt salts per-hash — two hashes of the same password must differ.
        assert hash_password("same-password") != hash_password("same-password")


class TestLogin:
    def test_valid_credentials_return_a_token(self, client, make_user):
        make_user(email="viewer@example.com", password="viewer-password", role="viewer")
        resp = client.post(
            "/auth/login", json={"email": "viewer@example.com", "password": "viewer-password"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["token_type"] == "bearer"
        assert body["role"] == "viewer"
        assert body["expires_in"] > 0
        assert body["access_token"]

    def test_wrong_password_is_401(self, client, make_user):
        make_user(email="ops@example.com", password="correct-password", role="ops")
        resp = client.post(
            "/auth/login", json={"email": "ops@example.com", "password": "wrong-password"}
        )
        assert resp.status_code == 401

    def test_unknown_email_is_401(self, client):
        resp = client.post(
            "/auth/login", json={"email": "nobody@example.com", "password": "whatever"}
        )
        assert resp.status_code == 401

    def test_inactive_user_is_401_even_with_correct_password(self, client, make_user):
        make_user(email="disabled@example.com", password="correct-password", is_active=False)
        resp = client.post(
            "/auth/login", json={"email": "disabled@example.com", "password": "correct-password"}
        )
        assert resp.status_code == 401

    def test_issued_token_carries_the_users_real_role(self, client, make_user):
        make_user(email="admin@example.com", password="admin-password", role="admin")
        resp = client.post(
            "/auth/login", json={"email": "admin@example.com", "password": "admin-password"}
        )
        assert resp.json()["role"] == "admin"


class TestMe:
    def test_me_returns_the_authenticated_users_identity(self, client, make_token):
        token = make_token(user_id="user-99", email="someone@example.com", role="ops")
        resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"id": "user-99", "email": "someone@example.com", "role": "ops"}

    def test_me_without_token_is_401(self, client):
        resp = client.get("/auth/me")
        assert resp.status_code == 401


class TestProtectedRouteAuthenticationBoundary:
    """Every negative-token case the Phase 9 requirements call out, exercised
    against a real protected gateway route (not just the shared dependency
    unit tests in event-contracts)."""

    def test_missing_token_on_mutating_route_is_401(self, client):
        resp = client.post("/api/orders", json={}, headers={"Idempotency-Key": "k"})
        assert resp.status_code == 401

    def test_malformed_token_is_401(self, client):
        resp = client.get(
            "/api/orders/11111111-1111-1111-1111-111111111111",
            headers={"Authorization": "Bearer not-a-real-jwt"},
        )
        assert resp.status_code == 401

    def test_expired_token_is_401(self, client, make_token):
        token = make_token(role="viewer", expires_minutes=-5)
        resp = client.get(
            "/api/orders/11111111-1111-1111-1111-111111111111",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401

    def test_wrong_signature_token_is_401(self, client, make_token):
        token = make_token(role="viewer", secret="an-attacker-guessed-this-secret")
        resp = client.get(
            "/api/orders/11111111-1111-1111-1111-111111111111",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401

    def test_wrong_audience_token_is_401(self, client, make_token):
        token = make_token(role="viewer", audience="some-other-service")
        resp = client.get(
            "/api/orders/11111111-1111-1111-1111-111111111111",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401

    def test_wrong_issuer_token_is_401(self, client, make_token):
        token = make_token(role="viewer", issuer="some-other-issuer")
        resp = client.get(
            "/api/orders/11111111-1111-1111-1111-111111111111",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401

    def test_token_with_unknown_role_is_401(self, client):
        settings = get_settings()
        bad_token = pyjwt.encode(
            {
                "sub": "user-1",
                "email": "x@example.com",
                "role": "superuser",
                "iss": settings.jwt_issuer,
                "aud": settings.jwt_audience,
                "iat": 0,
                "exp": 9999999999,
                "jti": "x",
            },
            settings.jwt_secret_key,
            algorithm="HS256",
        )
        resp = client.get(
            "/api/orders/11111111-1111-1111-1111-111111111111",
            headers={"Authorization": f"Bearer {bad_token}"},
        )
        assert resp.status_code == 401


class TestProtectedRouteAuthorizationBoundary:
    def test_viewer_cannot_create_order_403(self, client, make_token):
        token = make_token(role="viewer")
        resp = client.post(
            "/api/orders",
            json={},
            headers={"Idempotency-Key": "k", "Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    def test_viewer_cannot_cancel_order_403(self, client, make_token):
        token = make_token(role="viewer")
        resp = client.post(
            "/api/orders/11111111-1111-1111-1111-111111111111/cancel",
            json={"reason": "test"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    def test_viewer_can_read_orders_200_boundary_reached(self, client, make_token):
        """Viewer is allowed onto the read path at all — the request reaches
        the proxy layer (a real connect error to the unreachable test host,
        not a 401/403), proving viewer isn't blocked from reads."""
        token = make_token(role="viewer")
        resp = client.get(
            "/api/orders/11111111-1111-1111-1111-111111111111",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code not in (401, 403)
