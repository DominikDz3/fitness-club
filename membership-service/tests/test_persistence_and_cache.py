from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import CACHE_PREFIX, MemoryRedis

M001_KEY = f"{CACHE_PREFIX}:membership:M-001"


def test_changes_survive_new_app_instance(db_url):
    body = {"member_id": "U-300", "type": "gym_only",
            "valid_from": "2026-11-01", "valid_to": "2027-01-31"}
    with TestClient(create_app(database_url=db_url, redis_client=MemoryRedis())) as first:
        assert first.post("/memberships", json=body).status_code == 201
        assert first.patch("/memberships/M-001/suspend", json={"days": 14}).status_code == 200

    with TestClient(create_app(database_url=db_url, redis_client=MemoryRedis())) as second:
        r = second.get("/memberships/M-003")
        assert r.status_code == 200
        assert r.headers["X-Cache"] == "MISS"
        assert r.json()["member_id"] == "U-300"

        m001 = second.get("/memberships/M-001").json()
        assert m001["status"] == "suspended"
        assert m001["valid_to"] == "2027-01-14"
        assert len(second.get("/memberships").json()) == 3


def test_miss_then_hit_reads_database_once(client, fake_redis, monkeypatch):
    repository = client.app.state.repository
    reads = []
    original_get = repository.get

    def counted_get(membership_id):
        reads.append(membership_id)
        return original_get(membership_id)

    monkeypatch.setattr(repository, "get", counted_get)

    first = client.get("/memberships/M-001")
    assert first.status_code == 200
    assert first.headers["X-Cache"] == "MISS"
    assert fake_redis.expirations[M001_KEY] == 60

    second = client.get("/memberships/M-001")
    assert second.status_code == 200
    assert second.headers["X-Cache"] == "HIT"
    assert second.json() == first.json()
    assert reads == ["M-001"]


def test_suspend_invalidates_cache(client, fake_redis):
    client.get("/memberships/M-001")
    assert client.get("/memberships/M-001").headers["X-Cache"] == "HIT"

    r = client.patch("/memberships/M-001/suspend", json={"days": 14})
    assert r.status_code == 200
    assert M001_KEY not in fake_redis.values

    after = client.get("/memberships/M-001")
    assert after.headers["X-Cache"] == "MISS"
    assert after.json()["status"] == "suspended"
    assert after.json()["valid_to"] == "2027-01-14"


def test_redis_outage_does_not_block_read_or_write(client, fake_redis):
    fake_redis.down = True

    r = client.get("/memberships/M-001")
    assert r.status_code == 200
    assert r.headers["X-Cache"] == "BYPASS"
    assert r.json()["status"] == "active"

    assert client.patch("/memberships/M-001/suspend", json={"days": 14}).status_code == 200
    body = {"member_id": "U-300", "type": "open",
            "valid_from": "2026-11-01", "valid_to": "2027-01-31"}
    assert client.post("/memberships", json=body).status_code == 201

    fake_redis.down = False
    after = client.get("/memberships/M-001")
    assert after.headers["X-Cache"] == "MISS"
    assert after.json()["status"] == "suspended"
    assert len(client.get("/memberships").json()) == 3


def test_failed_invalidation_can_leave_stale_value(client, fake_redis):
    client.get("/memberships/M-001")  
    fake_redis.down = True
    assert client.patch("/memberships/M-001/suspend", json={"days": 14}).status_code == 200
    fake_redis.down = False

    stale = client.get("/memberships/M-001")
    assert stale.headers["X-Cache"] == "HIT"
    assert stale.json()["status"] == "active"
    assert client.app.state.repository.get("M-001").status == "suspended"


def test_rejected_suspend_rolls_back_and_keeps_database_state(client):
    before = client.app.state.repository.get("M-002")
    r = client.patch("/memberships/M-002/suspend", json={"days": 5})
    assert r.status_code == 409
    assert client.app.state.repository.get("M-002") == before
