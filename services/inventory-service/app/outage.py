"""In-process simulated-outage fault injection for Phase 8's
downstream-outage scenario. Deliberately not a Docker-level stop/start of
the container: flipping this in-process flag is instant, safe, and fully
reversible without touching shared infrastructure other work in the dev
stack might depend on concurrently, and it self-clears on a bound even if
the scenario is interrupted before calling `disable()` — see
docs/phase-8-failure-laboratory.md "Why not actually stop the container".

Single-process module state (no lock): FastAPI/uvicorn runs this service as
one process with one asyncio event loop, so there is no real concurrent
mutation hazard here — the same assumption api-gateway's own in-process
`RateLimitMiddleware` counter (services/api-gateway/app/middleware.py)
already makes elsewhere in this codebase.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


class OutageState:
    def __init__(self) -> None:
        self._until: datetime | None = None

    def enable(self, duration_seconds: float) -> None:
        self._until = datetime.now(UTC) + timedelta(seconds=duration_seconds)

    def disable(self) -> None:
        self._until = None

    @property
    def active(self) -> bool:
        if self._until is None:
            return False
        if datetime.now(UTC) >= self._until:
            self._until = None  # self-heal: never rely on someone calling disable()
            return False
        return True

    @property
    def until(self) -> datetime | None:
        return self._until


_state = OutageState()


def get_outage_state() -> OutageState:
    return _state
