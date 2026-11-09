import pytest
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError

from app.main import create_app

CACHE_PREFIX = "lab2:test:trainer-service"


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
def client(db_url, fake_redis):
    app = create_app(database_url=db_url, redis_client=fake_redis)
    with TestClient(app) as test_client:
        yield test_client
