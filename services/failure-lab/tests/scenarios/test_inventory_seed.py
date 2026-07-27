from app.scenarios.inventory_seed import ABUNDANT_QTY, SHARED_NODE_NAME, ensure_marker_stock
from tests.fakes import FakeInventoryServiceClient


def test_ensure_marker_stock_creates_the_shared_node_and_seeds_abundant_stock(make_ctx):
    inventory = FakeInventoryServiceClient()
    ctx = make_ctx(inventory=inventory)

    node_id = ensure_marker_stock(ctx, "SKU-TEST")

    node = inventory.nodes[node_id]
    assert node["name"] == SHARED_NODE_NAME
    assert inventory.stock[("SKU-TEST", node_id)]["available_qty"] == ABUNDANT_QTY


def test_ensure_marker_stock_reuses_the_same_node_across_calls_and_skus(make_ctx):
    inventory = FakeInventoryServiceClient()
    ctx = make_ctx(inventory=inventory)

    node_id_1 = ensure_marker_stock(ctx, "SKU-A")
    node_id_2 = ensure_marker_stock(ctx, "SKU-B")

    assert node_id_1 == node_id_2
    assert len(inventory.nodes) == 1
    assert ("SKU-A", node_id_1) in inventory.stock
    assert ("SKU-B", node_id_1) in inventory.stock


def test_ensure_marker_stock_is_safe_to_call_repeatedly_for_the_same_sku(make_ctx):
    inventory = FakeInventoryServiceClient()
    ctx = make_ctx(inventory=inventory)

    ensure_marker_stock(ctx, "SKU-A")
    node_id = ensure_marker_stock(ctx, "SKU-A")

    assert inventory.stock[("SKU-A", node_id)]["available_qty"] == ABUNDANT_QTY
