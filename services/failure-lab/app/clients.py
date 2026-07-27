"""Thin, synchronous REST clients the failure lab uses to drive real
scenarios against the real services — order-service, inventory-service,
fulfillment-orchestrator, and the API Gateway (the customer-facing entry
point some scenarios deliberately go through, rather than calling
order-service directly, so the scenario exercises the same path a real
customer request would).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx


class RemoteServiceError(Exception):
    """Any non-2xx response not otherwise handled by a more specific error."""

    def __init__(self, method: str, url: str, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"{method} {url} -> {status_code}: {body}")


class NotFoundError(RemoteServiceError):
    pass


class ConflictError(RemoteServiceError):
    pass


def _raise_for_status(method: str, resp: httpx.Response) -> None:
    if resp.status_code == 404:
        raise NotFoundError(method, str(resp.request.url), resp.status_code, resp.text)
    if resp.status_code == 409:
        raise ConflictError(method, str(resp.request.url), resp.status_code, resp.text)
    if resp.status_code >= 400:
        raise RemoteServiceError(method, str(resp.request.url), resp.status_code, resp.text)


class _JsonClient:
    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def _get(self, path: str, **kwargs: Any) -> Any:
        resp = httpx.get(f"{self._base_url}{path}", timeout=self._timeout, **kwargs)
        _raise_for_status("GET", resp)
        return resp.json()

    def _post(
        self, path: str, json: dict | None = None, headers: dict | None = None
    ) -> httpx.Response:
        resp = httpx.post(
            f"{self._base_url}{path}", json=json, headers=headers, timeout=self._timeout
        )
        _raise_for_status("POST", resp)
        return resp


@dataclass
class OrderRef:
    id: str
    status: str
    version: int


class GatewayClient(_JsonClient):
    """Phase 9 (JWT/RBAC, ADR 0009): `POST /api/orders` now requires an
    `ops`/`admin` JWT. This client logs in as the scoped `ops`-role service
    account api-gateway seeds for exactly this purpose (`app.seed`,
    `DECISIONS.md` "Phase 9") and caches the token, refreshing it a
    little before actual expiry rather than on every single call."""

    def __init__(
        self,
        base_url: str,
        *,
        service_email: str | None = None,
        service_password: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        super().__init__(base_url, timeout=timeout)
        self._service_email = service_email
        self._service_password = service_password
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    def _login(self) -> str:
        resp = httpx.post(
            f"{self._base_url}/auth/login",
            json={"email": self._service_email, "password": self._service_password},
            timeout=self._timeout,
        )
        _raise_for_status("POST", resp)
        body = resp.json()
        token: str = body["access_token"]
        self._token = token
        # Refresh a little early so a request in flight right as the token
        # would expire never races a genuinely-expired one.
        self._token_expires_at = time.monotonic() + max(body["expires_in"] - 30, 0)
        return token

    def _auth_headers(self) -> dict[str, str]:
        if self._token is None or time.monotonic() >= self._token_expires_at:
            self._login()
        return {"Authorization": f"Bearer {self._token}"}

    def create_order(self, payload: dict, idempotency_key: str) -> dict:
        headers = {"Idempotency-Key": idempotency_key, **self._auth_headers()}
        return self._post("/api/orders", json=payload, headers=headers).json()

    def readyz(self) -> tuple[int, dict]:
        # /readyz is a platform endpoint, deliberately unauthenticated.
        resp = httpx.get(f"{self._base_url}/readyz", timeout=self._timeout)
        try:
            body = resp.json()
        except ValueError:
            body = {}
        return resp.status_code, body


class OrderServiceClient(_JsonClient):
    def get_order(self, order_id: str) -> dict:
        return self._get(f"/orders/{order_id}")

    def get_history(self, order_id: str) -> list[dict]:
        return self._get(f"/orders/{order_id}/history")

    def processed_event_status(
        self, event_id: str, consumer_name: str = "order-service-validator"
    ) -> dict:
        return self._get(
            f"/internal/failure-lab/processed-events/{event_id}",
            params={"consumer_name": consumer_name},
        )


class InventoryServiceClient(_JsonClient):
    def list_nodes(self) -> list[dict]:
        return self._get("/fulfillment-nodes")

    def get_or_create_node(self, name: str, **fields: Any) -> dict:
        for node in self.list_nodes():
            if node["name"] == name:
                return node
        try:
            return self._post("/fulfillment-nodes", json={"name": name, **fields}).json()
        except ConflictError:
            # Two scenarios racing to create the same shared node — the
            # loser just reads back what the winner created.
            for node in self.list_nodes():
                if node["name"] == name:
                    return node
            raise

    def upsert_stock(
        self, sku: str, node_id: str, available_qty: int, reorder_threshold: int = 0
    ) -> dict:
        return self._post(
            "/stock",
            json={
                "sku": sku,
                "node_id": node_id,
                "available_qty": available_qty,
                "reorder_threshold": reorder_threshold,
            },
        ).json()

    def get_stock(self, sku: str, node_id: str) -> dict:
        return self._get(f"/stock/{sku}/{node_id}")

    def reserve(
        self, order_id: str, sku: str, node_id: str, qty: int, correlation_id: str
    ) -> httpx.Response:
        return self._post(
            "/reservations",
            json={
                "order_id": order_id,
                "sku": sku,
                "node_id": node_id,
                "qty": qty,
                "correlation_id": correlation_id,
            },
        )

    def release(self, reservation_id: str, reason: str) -> None:
        self._post(f"/reservations/{reservation_id}/release", json={"reason": reason})

    def enable_outage(self, duration_seconds: float) -> dict:
        return self._post(
            "/internal/failure-lab/outage/enable", json={"duration_seconds": duration_seconds}
        ).json()

    def disable_outage(self) -> dict:
        return self._post("/internal/failure-lab/outage/disable").json()

    def outage_status(self) -> dict:
        return self._get("/internal/failure-lab/outage/status")


class OrchestratorClient(_JsonClient):
    def get_saga_for_order(self, order_id: str) -> dict | None:
        try:
            return self._get(f"/saga-instances/{order_id}")
        except NotFoundError:
            return None

    def list_dead_letters(self, unreplayed_only: bool = False) -> list[dict]:
        return self._get("/dead-letters", params={"unreplayed_only": unreplayed_only})

    def replay_dead_letter(self, dead_letter_id: str) -> dict:
        return self._post(f"/dead-letters/{dead_letter_id}/replay").json()

    def resume_saga(self, order_id: str) -> dict:
        """Drives one specific order's paused/crashed saga forward via the
        real `advance_saga` — the same recovery mechanism a fresh process
        startup would run for every RUNNING saga (app.saga.resume_incomplete_sagas),
        just targeted at one order on demand."""
        return self._post(f"/internal/failure-lab/saga-crash-resume/{order_id}/resume").json()


def new_customer_payload() -> dict:
    """A fresh, valid customer block for scenarios that create an order —
    a new random customer each time keeps runs independent of each other."""
    suffix = uuid.uuid4().hex[:12]
    return {
        "customer_id": str(uuid.uuid4()),
        "customer_email": f"failure-lab-{suffix}@example.invalid",
        "customer_display_name": f"Failure Lab {suffix}",
    }
