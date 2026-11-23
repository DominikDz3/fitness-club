from urllib.error import HTTPError, URLError

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from tests.conftest import FakeEurekaClient, MemoryRedis

NEW_CLASS = {"name": "Joga", "trainer_id": "T-001", "capacity": 15,
             "starts_at": "2026-11-21T09:00:00", "ends_at": "2026-11-21T10:00:00"}


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def post_class(db_url, fake, body=NEW_CLASS):
    app = create_app(database_url=db_url, redis_client=MemoryRedis(), eureka_client=fake)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/classes", json=body)
            classes = (await client.get("/classes")).json()
            health = await client.get("/health")
    return response, classes, health


@pytest.mark.anyio
async def test_class_checks_trainer_by_logical_name(db_url):
    fake = FakeEurekaClient()
    response, classes, _ = await post_class(db_url, fake)

    assert response.status_code == 201
    assert response.json()["id"] == "C-003"
    assert response.json()["trainer_id"] == "T-001"
    assert fake.calls == [("TRAINER-SERVICE", "/trainers/T-001", "json", 3)]
    assert [c["id"] for c in classes] == ["C-001", "C-002", "C-003"]
    assert fake.starts == fake.stops == 1


@pytest.mark.anyio
async def test_unknown_trainer_returns_404_and_no_class(db_url):
    fake = FakeEurekaClient()
    response, classes, _ = await post_class(db_url, fake, {**NEW_CLASS, "trainer_id": "T-999"})

    assert response.status_code == 404
    assert response.json() == {"detail": "Trainer not found"}
    assert fake.calls == [("TRAINER-SERVICE", "/trainers/T-999", "json", 3)]
    assert [c["id"] for c in classes] == ["C-001", "C-002"]


@pytest.mark.anyio
async def test_inactive_trainer_returns_409_and_no_class(db_url):
    response, classes, _ = await post_class(db_url, FakeEurekaClient(), {**NEW_CLASS, "trainer_id": "T-002"})

    assert response.status_code == 409
    assert response.json() == {"detail": "Trainer is not active (status 'inactive')"}
    assert [c["id"] for c in classes] == ["C-001", "C-002"]


@pytest.mark.anyio
@pytest.mark.parametrize("error", [URLError("connection refused"), TimeoutError("timed out")])
async def test_trainer_service_unavailable_returns_503(db_url, error):
    fake = FakeEurekaClient(error=error)
    response, classes, health = await post_class(db_url, fake)

    assert response.status_code == 503
    assert response.json() == {"detail": "Trainer Service is unavailable"}
    assert health.status_code == 200
    assert [c["id"] for c in classes] == ["C-001", "C-002"]
    assert fake.starts == fake.stops == 1


@pytest.mark.anyio
async def test_trainer_service_http_error_returns_502(db_url):
    error = HTTPError("http://trainer/trainers/T-001", 500, "Internal Server Error", {}, None)
    response, classes, _ = await post_class(db_url, FakeEurekaClient(error=error))

    assert response.status_code == 502
    assert response.json() == {"detail": "Trainer Service returned an HTTP error"}
    assert [c["id"] for c in classes] == ["C-001", "C-002"]


@pytest.mark.anyio
async def test_invalid_trainer_response_returns_502(db_url):
    response, classes, _ = await post_class(db_url, FakeEurekaClient(response={"unexpected": True}))

    assert response.status_code == 502
    assert response.json() == {"detail": "Trainer Service returned an invalid response"}
    assert [c["id"] for c in classes] == ["C-001", "C-002"]


@pytest.mark.anyio
async def test_invalid_trainer_id_is_rejected_without_calling_trainer_service(db_url):
    fake = FakeEurekaClient()
    response, _, _ = await post_class(db_url, fake, {**NEW_CLASS, "trainer_id": "X-1"})

    assert response.status_code == 422
    assert fake.calls == []


@pytest.mark.anyio
async def test_active_trainer_does_not_bypass_local_overlap_rule(db_url):
    fake = FakeEurekaClient()
    response, classes, _ = await post_class(db_url, fake, {**NEW_CLASS, "starts_at": "2026-11-20T18:30:00",
                                                           "ends_at": "2026-11-20T19:30:00"})

    assert response.status_code == 409
    assert response.json() == {"detail": "Trainer already has a class at this time"}
    assert len(fake.calls) == 1
    assert [c["id"] for c in classes] == ["C-001", "C-002"]