"""Kafka topics owned by the failure lab itself — distinct from the real
11-topic domain event catalog (event_contracts.EventType /
infra/docker/redpanda/create-topics.sh). Nothing in order-service,
inventory-service, or fulfillment-orchestrator subscribes to these, by
design: the poison-message-dlq scenario needs a consumer that can be made to
fail deterministically without any risk of ever crashing or dead-lettering
a real business consumer. See docs/phase-8-failure-laboratory.md
"Isolation of chaos topics".
"""

POISON_TOPIC = "failure-lab.poison"
