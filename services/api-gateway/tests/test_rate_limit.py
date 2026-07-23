from app.config import get_settings
from app.main import app


def test_requests_beyond_the_per_minute_limit_are_rejected(client):
    """Resets the shared rate-limit hit counter before running its scenario.

    That counter lives on `app.state` (see app.main / app.middleware) for the
    whole test session, shared with every other gateway test via the `client`
    fixture's TestClient — without the reset, hits from tests that ran first
    would already be sitting in the same bucket and trip the lowered limit on
    this test's very first request, independent of what this test itself does.
    """
    app.state.rate_limit_hits.clear()
    settings = get_settings()
    original_limit = settings.rate_limit_per_minute
    settings.rate_limit_per_minute = 3
    try:
        for _ in range(3):
            resp = client.get("/healthz")
            assert resp.status_code == 200

        blocked = client.get("/healthz")
        assert blocked.status_code == 429
        assert blocked.json()["error_code"] == "rate_limited"
    finally:
        settings.rate_limit_per_minute = original_limit
