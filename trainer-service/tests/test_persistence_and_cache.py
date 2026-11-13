from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import CACHE_PREFIX, MemoryRedis

T001_KEY = f"{CACHE_PREFIX}:trainer:T-001"
SESSION = {"trainer_id": "T-001", "membership_id": "M-002",
           "starts_at": "2026-11-16T10:00:00", "ends_at": "2026-11-16T11:00:00"}


def test_changes_survive_new_app_instance(db_url):
    with TestClient(create_app(database_url=db_url, redis_client=MemoryRedis())) as first:
        assert first.post("/trainers", json={"name": "Ewa Zielinska",
                                             "specialization": "pilates"}).status_code == 201
        assert first.post("/sessions", json=SESSION).status_code == 201
        assert first.patch("/trainers/T-002/status", json={"status": "active"}).status_code == 200

    with TestClient(create_app(database_url=db_url, redis_client=MemoryRedis())) as second:
        r = second.get("/trainers/T-003")
        assert r.status_code == 200
        assert r.headers["X-Cache"] == "MISS"
        assert r.json()["name"] == "Ewa Zielinska"

        assert second.get("/trainers/T-002").json()["status"] == "active"
        assert second.get("/sessions/S-002").json()["starts_at"] == "2026-11-16T10:00:00"
        assert len(second.get("/trainers").json()) == 3  # seed() nie dodał danych drugi raz


def test_miss_then_hit_reads_database_once(client, fake_redis, monkeypatch):
    repository = client.app.state.repository
    reads = []
    original = repository.get_trainer

    def counted(trainer_id):
        reads.append(trainer_id)
        return original(trainer_id)

    monkeypatch.setattr(repository, "get_trainer", counted)

    first = client.get("/trainers/T-001")
    assert first.status_code == 200
    assert first.headers["X-Cache"] == "MISS"
    assert fake_redis.expirations[T001_KEY] == 60

    second = client.get("/trainers/T-001")
    assert second.headers["X-Cache"] == "HIT"
    assert second.json() == first.json()
    assert reads == ["T-001"]


def test_missing_trainer_is_not_cached(client, fake_redis):
    assert client.get("/trainers/T-999").status_code == 404
    assert f"{CACHE_PREFIX}:trainer:T-999" not in fake_redis.values


def test_status_change_invalidates_cache(client, fake_redis):
    client.get("/trainers/T-002")
    assert client.get("/trainers/T-002").headers["X-Cache"] == "HIT"

    assert client.patch("/trainers/T-002/status", json={"status": "active"}).status_code == 200
    assert f"{CACHE_PREFIX}:trainer:T-002" not in fake_redis.values

    after = client.get("/trainers/T-002")
    assert after.headers["X-Cache"] == "MISS"
    assert after.json()["status"] == "active"


def test_redis_outage_does_not_block_read_or_write(client, fake_redis):
    fake_redis.down = True

    r = client.get("/trainers/T-002")
    assert r.status_code == 200
    assert r.headers["X-Cache"] == "BYPASS"

    assert client.patch("/trainers/T-002/status", json={"status": "active"}).status_code == 200
    assert client.post("/sessions", json=SESSION).status_code == 201

    fake_redis.down = False
    after = client.get("/trainers/T-002")
    assert after.headers["X-Cache"] == "MISS"
    assert after.json()["status"] == "active"
    assert len(client.get("/sessions").json()) == 2


def test_failed_invalidation_can_leave_stale_value(client, fake_redis):
    client.get("/trainers/T-002")  # T-002 inactive trafia do cache
    fake_redis.down = True
    assert client.patch("/trainers/T-002/status", json={"status": "active"}).status_code == 200
    fake_redis.down = False

    stale = client.get("/trainers/T-002")
    assert stale.headers["X-Cache"] == "HIT"
    assert stale.json()["status"] == "inactive"
    assert client.app.state.repository.get_trainer("T-002").status == "active"


def test_rejected_deactivation_rolls_back_and_keeps_database_state(client):
    before = client.app.state.repository.get_trainer("T-001")
    assert client.patch("/trainers/T-001/status", json={"status": "inactive"}).status_code == 409
    assert client.app.state.repository.get_trainer("T-001") == before
