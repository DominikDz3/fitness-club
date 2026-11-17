import pytest
from urllib.error import HTTPError
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError

from app.main import create_app


CACHE_PREFIX = "lab2:test:class-service"


class MemoryRedis:

    def __init__(self):
        self.values = {}
        self.expirations = {}
        self.down = False

    def check(self):
        if self.down:
            raise ConnectionError("Simulated outage")

    def get(self, key):
        self.check()
        return self.values.get(key)

    def set(self, key, value, ex):
        self.check()
        self.values[key] = value
        self.expirations[key] = ex

    def delete(self, key):
        self.check()
        self.values.pop(key, None)
        self.expirations.pop(key, None)

    def ping(self):
        self.check()
        return True

    def close(self):
        pass


TRAINERS = {
    "T-001": {"id": "T-001", "name": "Anna Nowak", "specialization": "strength", "status": "active"},
    "T-002": {"id": "T-002", "name": "Piotr Kowalski", "specialization": "yoga", "status": "inactive"},
}


class FakeEurekaClient:

    def __init__(self, trainers=None, error=None, response=None):
        self.trainers = TRAINERS if trainers is None else trainers
        self.error = error
        self.response = response
        self.calls = []
        self.starts = 0
        self.stops = 0

    async def start(self):
        self.starts += 1

    async def stop(self):
        self.stops += 1

    async def do_service(self, app_name, service, return_type=None, timeout=None):
        self.calls.append((app_name, service, return_type, timeout))
        if self.error is not None:
            raise self.error
        if self.response is not None:
            return self.response
        trainer_id = service.rsplit("/", 1)[-1]
        if app_name == "TRAINER-SERVICE" and trainer_id in self.trainers:
            return dict(self.trainers[trainer_id])
        raise HTTPError(f"http://trainer{service}", 404, "Not Found", {}, None)


@pytest.fixture
def fake_eureka():
    return FakeEurekaClient()



@pytest.fixture(autouse=True)
def cache_env(monkeypatch):
    monkeypatch.setenv("CACHE_PREFIX", CACHE_PREFIX)
    monkeypatch.setenv("CACHE_TTL_SECONDS", "60")


@pytest.fixture
def db_url(tmp_path):
    return "sqlite:///" + (tmp_path / "test.db").as_posix()


@pytest.fixture
def fake_redis():
    return MemoryRedis()


@pytest.fixture
def client(db_url, fake_redis, fake_eureka):
    app = create_app(database_url=db_url, redis_client=fake_redis, eureka_client=fake_eureka)
    with TestClient(app) as test_client:
        yield test_client