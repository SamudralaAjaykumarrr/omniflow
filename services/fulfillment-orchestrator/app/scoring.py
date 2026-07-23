"""Fulfillment-node scoring — see
docs/adrs/0010-node-scoring-and-saga-orchestration.md for the formula and
its tradeoffs.

Stock sufficiency is a hard gate applied by the caller (via
`app.stock_check`, which calls Inventory Service's `/stock/check`) before a
node is passed in here as a candidate — this module ranks among nodes that
CAN fulfill the order; it does not itself check stock.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field

EARTH_RADIUS_KM = 6371.0
GROUND_SHIPPING_KM_PER_DAY = 500.0
BASE_PROCESSING_DAYS = 1.0

WEIGHT_DISTANCE = 0.35
WEIGHT_DELIVERY = 0.25
WEIGHT_BACKLOG = 0.20
WEIGHT_CAPACITY = 0.20


@dataclass
class NodeCandidate:
    node_id: str
    latitude: float
    longitude: float
    capacity_per_day: int
    current_backlog: int


@dataclass
class NodeScore:
    node_id: str
    score: float
    breakdown: dict = field(default_factory=dict)
    estimated_ship_date_days: float = 0.0


def simulated_customer_location(customer_id: str) -> tuple[float, float]:
    """Deterministic pseudo-location derived from a hash of `customer_id`.

    There is no real customer geolocation in this system's schema; this is
    the documented "simulated distance" input — stable per customer, never
    random per request, so the same customer always scores nodes the same
    way for the same catalog of candidates.
    """
    digest = hashlib.sha256(customer_id.encode("utf-8")).hexdigest()
    lat = (int(digest[:8], 16) / 0xFFFFFFFF) * 180 - 90
    lon = (int(digest[8:16], 16) / 0xFFFFFFFF) * 360 - 180
    return lat, lon


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def score_candidates(customer_id: str, candidates: list[NodeCandidate]) -> list[NodeScore]:
    """Rank `candidates` best-first. Each component is normalized to [0, 1]
    within this candidate set (1 = best among them, not an absolute scale),
    so scores are only comparable within one scoring call, never across
    orders with different candidate sets.
    """
    if not candidates:
        return []

    cust_lat, cust_lon = simulated_customer_location(customer_id)
    distances = {
        c.node_id: haversine_km(cust_lat, cust_lon, c.latitude, c.longitude) for c in candidates
    }
    delivery_days = {
        node_id: BASE_PROCESSING_DAYS + dist_km / GROUND_SHIPPING_KM_PER_DAY
        for node_id, dist_km in distances.items()
    }
    max_capacity = max((c.capacity_per_day for c in candidates), default=1) or 1

    def _min_max_normalize_best_at_one(values: dict[str, float], key: str) -> float:
        # 1.0 = best (smallest) among the candidate set, 0.0 = worst
        # (largest). When every candidate ties (including the common
        # single-candidate case, range == 0), there is nothing to
        # differentiate on, so every candidate gets full credit rather than
        # the degenerate `value / value == 1 -> score 0` a naive
        # divide-by-max would produce.
        lo, hi = min(values.values()), max(values.values())
        if hi == lo:
            return 1.0
        return 1 - (values[key] - lo) / (hi - lo)

    scores = []
    for c in candidates:
        distance_score = _min_max_normalize_best_at_one(distances, c.node_id)
        delivery_score = _min_max_normalize_best_at_one(delivery_days, c.node_id)
        backlog_score = (
            max(0.0, 1 - (c.current_backlog / c.capacity_per_day)) if c.capacity_per_day else 0.0
        )
        capacity_score = c.capacity_per_day / max_capacity

        total = (
            WEIGHT_DISTANCE * distance_score
            + WEIGHT_DELIVERY * delivery_score
            + WEIGHT_BACKLOG * backlog_score
            + WEIGHT_CAPACITY * capacity_score
        )
        scores.append(
            NodeScore(
                node_id=c.node_id,
                score=round(total, 4),
                breakdown={
                    "stock": 1.0,
                    "distance": round(distance_score, 4),
                    "capacity": round(capacity_score, 4),
                    "delivery_estimate": round(delivery_score, 4),
                    "backlog": round(backlog_score, 4),
                },
                estimated_ship_date_days=round(delivery_days[c.node_id], 2),
            )
        )
    return sorted(scores, key=lambda s: s.score, reverse=True)
