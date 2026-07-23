from app.scoring import NodeCandidate, score_candidates, simulated_customer_location


def test_single_candidate_scores_perfectly_on_every_relative_component():
    candidate = NodeCandidate(
        node_id="n1", latitude=47.6, longitude=-122.3, capacity_per_day=100, current_backlog=0
    )
    scores = score_candidates("customer-1", [candidate])

    assert len(scores) == 1
    assert scores[0].node_id == "n1"
    assert scores[0].breakdown["distance"] == 1.0
    assert scores[0].breakdown["delivery_estimate"] == 1.0
    assert scores[0].breakdown["capacity"] == 1.0
    assert scores[0].breakdown["backlog"] == 1.0
    assert scores[0].score == 1.0


def test_closer_node_scores_higher_than_farther_node_for_the_same_customer():
    # Same simulated location as the customer would place them near node "near"
    cust_lat, cust_lon = simulated_customer_location("customer-42")
    near = NodeCandidate(
        node_id="near",
        latitude=cust_lat,
        longitude=cust_lon,
        capacity_per_day=100,
        current_backlog=0,
    )
    far = NodeCandidate(
        node_id="far",
        latitude=cust_lat + 40,
        longitude=cust_lon + 40,
        capacity_per_day=100,
        current_backlog=0,
    )

    ranked = score_candidates("customer-42", [near, far])

    assert ranked[0].node_id == "near"
    assert ranked[0].score > ranked[1].score


def test_higher_backlog_relative_to_capacity_scores_lower():
    cust_lat, cust_lon = simulated_customer_location("customer-7")
    low_backlog = NodeCandidate(
        node_id="low",
        latitude=cust_lat,
        longitude=cust_lon,
        capacity_per_day=100,
        current_backlog=0,
    )
    high_backlog = NodeCandidate(
        node_id="high",
        latitude=cust_lat,
        longitude=cust_lon,
        capacity_per_day=100,
        current_backlog=90,
    )

    ranked = score_candidates("customer-7", [low_backlog, high_backlog])

    assert ranked[0].node_id == "low"
    assert ranked[0].breakdown["backlog"] > ranked[1].breakdown["backlog"]


def test_scoring_is_deterministic_for_the_same_inputs():
    candidates = [
        NodeCandidate(
            node_id="a", latitude=10, longitude=20, capacity_per_day=50, current_backlog=5
        ),
        NodeCandidate(
            node_id="b", latitude=30, longitude=40, capacity_per_day=80, current_backlog=20
        ),
    ]
    first = score_candidates("customer-99", candidates)
    second = score_candidates("customer-99", candidates)

    assert [s.score for s in first] == [s.score for s in second]
    assert [s.node_id for s in first] == [s.node_id for s in second]


def test_empty_candidate_list_returns_empty_scores():
    assert score_candidates("customer-1", []) == []
