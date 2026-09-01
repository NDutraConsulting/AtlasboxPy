import pytest

from atlasboxpy_db import ShardRouter


def test_single_shard_router_routes_every_key_to_the_one_shard():
    router = ShardRouter(name="kanban", shards=["only-shard"])
    assert router.shard_for("") == "only-shard"
    assert router.shard_for("anything") == "only-shard"
    assert router.shard_for("board-123") == "only-shard"


def test_shard_count_and_all_shards():
    router = ShardRouter(name="multi", shards=["a", "b", "c"])
    assert router.shard_count == 3
    assert router.all_shards() == ("a", "b", "c")


def test_routing_is_deterministic_across_calls():
    router = ShardRouter(name="multi", shards=["a", "b", "c", "d"])
    first = router.shard_for("board-123")
    for _ in range(20):
        assert router.shard_for("board-123") == first


def test_routing_is_deterministic_across_router_instances():
    """The hash must be stable across processes/instances, not Python's
    randomized-per-process built-in hash() — otherwise the same key
    could route to a different shard after a restart."""
    router_a = ShardRouter(name="multi", shards=["a", "b", "c", "d"])
    router_b = ShardRouter(name="multi", shards=["a", "b", "c", "d"])
    for key in ["board-1", "board-2", "tenant-x", ""]:
        assert router_a.shard_for(key) == router_b.shard_for(key)


def test_different_keys_can_land_on_different_shards():
    router = ShardRouter(name="multi", shards=["a", "b", "c", "d"])
    results = {router.shard_for(f"key-{i}") for i in range(50)}
    # Not a strict guarantee for any single key, but 50 distinct keys
    # landing on only one shard would indicate a broken/degenerate hash.
    assert len(results) > 1


def test_empty_shards_list_is_rejected():
    with pytest.raises(ValueError, match="needs at least one shard"):
        ShardRouter(name="empty", shards=[])
