from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import CACHE_PREFIX, MemoryRedis
from redis.exceptions import ConnectionError

C001_KEY = f"{CACHE_PREFIX}:class:C-001"
NEW_CLASS = {"name": "Joga", "trainer_id": "T-001", "capacity": 15,
             "starts_at": "2026-11-21T09:00:00", "ends_at": "2026-11-21T10:00:00"}


def test_changes_survive_new_app_instance(db_url):
    with TestClient(create_app(database_url=db_url, redis_client=MemoryRedis())) as first:
        assert first.post("/classes", json=NEW_CLASS).status_code == 201
        assert first.patch("/classes/C-001/cancel").status_code == 200

    with TestClient(create_app(database_url=db_url, redis_client=MemoryRedis())) as second:
        r = second.get("/classes/C-003")
        assert r.status_code == 200
        assert r.headers["X-Cache"] == "MISS"
        assert r.json()["name"] == "Joga"

        assert second.get("/classes/C-001").json()["status"] == "cancelled"
        assert len(second.get("/classes").json()) == 3


def test_miss_then_hit_reads_database_once(client, fake_redis, monkeypatch):
    repository = client.app.state.repository
    reads = []
    original = repository.get_class

    def counted(class_id):
        reads.append(class_id)
        return original(class_id)

    monkeypatch.setattr(repository, "get_class", counted)

    first = client.get("/classes/C-001")
    assert first.status_code == 200
    assert first.headers["X-Cache"] == "MISS"
    assert fake_redis.expirations[C001_KEY] == 60

    second = client.get("/classes/C-001")
    assert second.headers["X-Cache"] == "HIT"
    assert second.json() == first.json()
    assert reads == ["C-001"]


def test_status_change_invalidates_cache(client, fake_redis):
    client.get("/classes/C-001")
    assert client.get("/classes/C-001").headers["X-Cache"] == "HIT"

    assert client.patch("/classes/C-001/cancel").status_code == 200
    assert C001_KEY not in fake_redis.values

    after = client.get("/classes/C-001")
    assert after.headers["X-Cache"] == "MISS"
    assert after.json()["status"] == "cancelled"


def test_redis_outage_does_not_block_read_or_write(client, fake_redis):
    fake_redis.down = True

    r = client.get("/classes/C-001")
    assert r.status_code == 200
    assert r.headers["X-Cache"] == "BYPASS"

    assert client.patch("/classes/C-001/finish").status_code == 200
    assert client.post("/classes", json=NEW_CLASS).status_code == 201

    fake_redis.down = False
    after = client.get("/classes/C-001")
    assert after.headers["X-Cache"] == "MISS"
    assert after.json()["status"] == "finished"
    assert len(client.get("/classes").json()) == 3


def test_failed_invalidation_can_leave_stale_value(client, fake_redis):
    client.get("/classes/C-001")
    fake_redis.down = True
    assert client.patch("/classes/C-001/cancel").status_code == 200
    fake_redis.down = False

    stale = client.get("/classes/C-001")
    assert stale.headers["X-Cache"] == "HIT"
    assert stale.json()["status"] == "scheduled"
    assert client.app.state.repository.get_class("C-001").status == "cancelled"


def test_rejected_status_change_rolls_back_and_keeps_database_state(client):
    before = client.app.state.repository.get_class("C-002")
    assert client.patch("/classes/C-002/finish").status_code == 409
    assert client.app.state.repository.get_class("C-002") == before



def test_missing_class_is_not_cached(client, fake_redis):
    assert client.get("/classes/C-999").status_code == 404
    assert f"{CACHE_PREFIX}:class:C-999" not in fake_redis.values


def test_cache_set_failure_returns_database_value_as_bypass(client, fake_redis, monkeypatch):
    def failing_set(key, value, ex):
        raise ConnectionError("SET failed")

    monkeypatch.setattr(fake_redis, "set", failing_set)

    r = client.get("/classes/C-001")
    assert r.status_code == 200
    assert r.headers["X-Cache"] == "BYPASS"
    assert r.json()["name"] == "Trening obwodowy"
    assert C001_KEY not in fake_redis.values