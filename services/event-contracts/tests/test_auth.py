"""Unit + dependency-boundary tests for event_contracts.auth (Phase 9,
ADR 0009). Covers the token lifecycle itself (encode/decode, expiry,
tampering, wrong audience/issuer, malformed input) and the FastAPI
dependency wiring (401 vs 403) against a tiny throwaway app — no real
service's app.main is imported here, this module is service-agnostic.
"""

import time

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from event_contracts.auth import (
    TokenExpiredError,
    TokenInvalidError,
    build_current_user_dependency,
    build_require_role_dependency,
    create_access_token,
    decode_access_token,
)

SECRET = "test-secret-do-not-use-in-real-deployment"
ISSUER = "omniflow-api-gateway"
AUDIENCE = "omniflow-services"


def _token(role: str = "viewer", expires_minutes: int = 30, **overrides) -> str:
    return create_access_token(
        subject=overrides.pop("subject", "user-1"),
        email=overrides.pop("email", "user@example.com"),
        role=role,
        secret=overrides.pop("secret", SECRET),
        issuer=overrides.pop("issuer", ISSUER),
        audience=overrides.pop("audience", AUDIENCE),
        expires_minutes=expires_minutes,
    )


class TestCreateAndDecodeRoundTrip:
    def test_valid_token_round_trips_all_claims(self):
        token = _token(role="ops", subject="user-42", email="ops@example.com")
        payload = decode_access_token(token, secret=SECRET, issuer=ISSUER, audience=AUDIENCE)
        assert payload.sub == "user-42"
        assert payload.email == "ops@example.com"
        assert payload.role == "ops"
        assert payload.jti
        assert payload.exp > payload.iat

    def test_each_token_gets_a_unique_jti(self):
        first = decode_access_token(_token(), secret=SECRET, issuer=ISSUER, audience=AUDIENCE)
        second = decode_access_token(_token(), secret=SECRET, issuer=ISSUER, audience=AUDIENCE)
        assert first.jti != second.jti


class TestNegativeTokenCases:
    def test_expired_token_raises_token_expired_error(self):
        token = _token(expires_minutes=-1)
        with pytest.raises(TokenExpiredError):
            decode_access_token(token, secret=SECRET, issuer=ISSUER, audience=AUDIENCE)

    def test_wrong_signature_raises_token_invalid_error(self):
        token = _token(secret="a-completely-different-secret")
        with pytest.raises(TokenInvalidError):
            decode_access_token(token, secret=SECRET, issuer=ISSUER, audience=AUDIENCE)

    def test_wrong_audience_raises_token_invalid_error(self):
        token = _token(audience="some-other-audience")
        with pytest.raises(TokenInvalidError):
            decode_access_token(token, secret=SECRET, issuer=ISSUER, audience=AUDIENCE)

    def test_wrong_issuer_raises_token_invalid_error(self):
        token = _token(issuer="some-other-issuer")
        with pytest.raises(TokenInvalidError):
            decode_access_token(token, secret=SECRET, issuer=ISSUER, audience=AUDIENCE)

    def test_malformed_token_raises_token_invalid_error(self):
        with pytest.raises(TokenInvalidError):
            decode_access_token("not-a-jwt-at-all", secret=SECRET, issuer=ISSUER, audience=AUDIENCE)

    def test_unknown_role_claim_raises_token_invalid_error(self):
        now = int(time.time())
        token = jwt.encode(
            {
                "sub": "user-1",
                "email": "user@example.com",
                "role": "superuser",
                "iss": ISSUER,
                "aud": AUDIENCE,
                "iat": now,
                "exp": now + 60,
                "jti": "x",
            },
            SECRET,
            algorithm="HS256",
        )
        with pytest.raises(TokenInvalidError, match="unknown role"):
            decode_access_token(token, secret=SECRET, issuer=ISSUER, audience=AUDIENCE)

    def test_missing_required_claim_raises_token_invalid_error(self):
        now = int(time.time())
        token = jwt.encode(
            {"sub": "user-1", "iss": ISSUER, "aud": AUDIENCE, "iat": now, "exp": now + 60},
            SECRET,
            algorithm="HS256",
        )
        with pytest.raises(TokenInvalidError):
            decode_access_token(token, secret=SECRET, issuer=ISSUER, audience=AUDIENCE)


def _build_test_app() -> FastAPI:
    app = FastAPI()
    get_current_user = build_current_user_dependency(
        secret=SECRET, issuer=ISSUER, audience=AUDIENCE
    )
    require_ops = build_require_role_dependency(get_current_user, "ops")
    require_admin = build_require_role_dependency(get_current_user, "admin")

    @app.get("/viewer-ok")
    def viewer_ok(user=Depends(get_current_user)):
        return {"role": user.role}

    @app.get("/ops-only")
    def ops_only(user=Depends(require_ops)):
        return {"role": user.role}

    @app.get("/admin-only")
    def admin_only(user=Depends(require_admin)):
        return {"role": user.role}

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_build_test_app())


class TestDependencyAuthenticationBoundary:
    def test_missing_authorization_header_is_401(self, client: TestClient):
        resp = client.get("/viewer-ok")
        assert resp.status_code == 401

    def test_malformed_bearer_token_is_401(self, client: TestClient):
        resp = client.get("/viewer-ok", headers={"Authorization": "Bearer garbage"})
        assert resp.status_code == 401

    def test_expired_token_is_401(self, client: TestClient):
        token = _token(expires_minutes=-5)
        resp = client.get("/viewer-ok", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401

    def test_wrong_signature_token_is_401(self, client: TestClient):
        token = _token(secret="wrong-secret")
        resp = client.get("/viewer-ok", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401

    def test_wrong_audience_token_is_401(self, client: TestClient):
        token = _token(audience="not-omniflow")
        resp = client.get("/viewer-ok", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401

    def test_valid_viewer_token_reaches_viewer_route(self, client: TestClient):
        token = _token(role="viewer")
        resp = client.get("/viewer-ok", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json() == {"role": "viewer"}


class TestDependencyAuthorizationBoundary:
    def test_viewer_token_on_ops_route_is_403(self, client: TestClient):
        token = _token(role="viewer")
        resp = client.get("/ops-only", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403

    def test_ops_token_on_ops_route_is_200(self, client: TestClient):
        token = _token(role="ops")
        resp = client.get("/ops-only", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_admin_token_on_ops_route_is_200_admin_outranks_ops(self, client: TestClient):
        token = _token(role="admin")
        resp = client.get("/ops-only", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_ops_token_on_admin_route_is_403(self, client: TestClient):
        token = _token(role="ops")
        resp = client.get("/admin-only", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403

    def test_admin_token_on_admin_route_is_200(self, client: TestClient):
        token = _token(role="admin")
        resp = client.get("/admin-only", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_missing_token_on_ops_route_is_401_not_403(self, client: TestClient):
        """An unauthenticated caller must get 401 (who are you?), not 403
        (I know who you are and you're not allowed) — the two must not be
        conflated."""
        resp = client.get("/ops-only")
        assert resp.status_code == 401
