import uuid

from app.models import ProcessedEvent


def test_processed_event_status_is_false_for_an_unseen_event(client):
    event_id = uuid.uuid4()
    resp = client.get(f"/internal/failure-lab/processed-events/{event_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["processed"] is False
    assert body["processed_at"] is None
    assert body["consumer_name"] == "order-service-validator"


def test_processed_event_status_reflects_a_recorded_event(client, db_session):
    event_id = uuid.uuid4()
    db_session.add(ProcessedEvent(consumer_name="order-service-validator", event_id=event_id))
    db_session.commit()

    resp = client.get(f"/internal/failure-lab/processed-events/{event_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["processed"] is True
    assert body["processed_at"] is not None


def test_processed_event_status_honors_a_custom_consumer_name(client, db_session):
    event_id = uuid.uuid4()
    db_session.add(ProcessedEvent(consumer_name="some-other-consumer", event_id=event_id))
    db_session.commit()

    default_consumer_resp = client.get(f"/internal/failure-lab/processed-events/{event_id}")
    assert default_consumer_resp.json()["processed"] is False

    custom_resp = client.get(
        f"/internal/failure-lab/processed-events/{event_id}",
        params={"consumer_name": "some-other-consumer"},
    )
    assert custom_resp.json()["processed"] is True
