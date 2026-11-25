from datetime import date

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError

from app.main import create_app

CACHE_PREFIX = "lab2:test:membership-service"
# Stała "dzisiejsza" data testów: M-001 aktywny, M-002 w trakcie pauzy (do 2026-10-25).
TODAY = date(2026, 10, 15)


class MemoryRedis:
    """Zamiennik Redis z paczki LAB2 (tests/test_storage.py), nie symuluje upływu TTL."""

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


class FakeEurekaClient:
    """Zamiennik klienta Eureki: nie łączy się z rejestrem, liczy start() i stop()."""

    def __init__(self):
        self.starts = 0
        self.stops = 0

    async def start(self):
        self.starts += 1

    async def stop(self):
        self.stops += 1


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
    app = create_app(database_url=db_url, redis_client=fake_redis, eureka_client=fake_eureka,
                     today=lambda: TODAY)
    with TestClient(app) as test_client:
        yield test_client