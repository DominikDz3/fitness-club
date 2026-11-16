from urllib.error import HTTPError, URLError

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from tests.conftest import MEMBERSHIPS, FakeEurekaClient, MemoryRedis

SESSION = {"trainer_id": "T-001", "membership_id": "M-001",
           "starts_at": "2026-11-16T10:00:00", "ends_at": "2026-11-16T11:00:00"}


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def post_session(db_url, fake, body=SESSION):
    """Uruchamia aplikację z atrapą Eureki, wysyła POST /sessions i zwraca odpowiedź oraz listę sesji."""
    app = create_app(database_url=db_url, redis_client=MemoryRedis(), eureka_client=fake)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/sessions", json=body)
            sessions = (await client.get("/sessions")).json()
            health = await client.get("/health")
    return response, sessions, health


@pytest.mark.anyio
async def test_session_checks_membership_by_logical_name(db_url):
    fake = FakeEurekaClient()
    response, sessions, _ = await post_session(db_url, fake)

    assert response.status_code == 201
    assert response.json()["id"] == "S-002"
    assert response.json()["membership_id"] == "M-001"
    assert fake.calls == [("MEMBERSHIP-SERVICE", "/memberships/M-001", "json", 3)]
    assert [s["id"] for s in sessions] == ["S-001", "S-002"]
    assert fake.starts == fake.stops == 1


@pytest.mark.anyio
async def test_unknown_membership_returns_404_and_no_session(db_url):
    fake = FakeEurekaClient()
    response, sessions, _ = await post_session(db_url, fake, {**SESSION, "membership_id": "M-999"})

    assert response.status_code == 404
    assert response.json() == {"detail": "Membership not found"}
    assert fake.calls == [("MEMBERSHIP-SERVICE", "/memberships/M-999", "json", 3)]
    assert [s["id"] for s in sessions] == ["S-001"]


@pytest.mark.anyio
async def test_suspended_membership_returns_409_and_no_session(db_url):
    response, sessions, _ = await post_session(db_url, FakeEurekaClient(), {**SESSION, "membership_id": "M-002"})

    assert response.status_code == 409
    assert response.json() == {"detail": "Membership is not active (status 'suspended')"}
    assert [s["id"] for s in sessions] == ["S-001"]


@pytest.mark.anyio
async def test_membership_not_valid_on_session_date_returns_409(db_url):
    ended = {**MEMBERSHIPS["M-001"], "id": "M-003", "valid_to": "2026-11-15"}
    fake = FakeEurekaClient(memberships={"M-003": ended})
    response, sessions, _ = await post_session(db_url, fake, {**SESSION, "membership_id": "M-003"})

    assert response.status_code == 409
    assert response.json() == {"detail": "Membership is not valid on the session date"}
    assert [s["id"] for s in sessions] == ["S-001"]


@pytest.mark.anyio
@pytest.mark.parametrize("error", [URLError("connection refused"), TimeoutError("timed out")])
async def test_membership_service_unavailable_returns_503(db_url, error):
    fake = FakeEurekaClient(error=error)
    response, sessions, health = await post_session(db_url, fake)

    assert response.status_code == 503
    assert response.json() == {"detail": "Membership Service is unavailable"}
    assert health.status_code == 200
    assert [s["id"] for s in sessions] == ["S-001"]
    assert fake.starts == fake.stops == 1


@pytest.mark.anyio
async def test_membership_service_http_error_returns_502(db_url):
    error = HTTPError("http://membership/memberships/M-001", 500, "Internal Server Error", {}, None)
    response, sessions, _ = await post_session(db_url, FakeEurekaClient(error=error))

    assert response.status_code == 502
    assert response.json() == {"detail": "Membership Service returned an HTTP error"}
    assert [s["id"] for s in sessions] == ["S-001"]


@pytest.mark.anyio
async def test_invalid_membership_response_returns_502(db_url):
    response, sessions, _ = await post_session(db_url, FakeEurekaClient(response={"unexpected": True}))

    assert response.status_code == 502
    assert response.json() == {"detail": "Membership Service returned an invalid response"}
    assert [s["id"] for s in sessions] == ["S-001"]


@pytest.mark.anyio
async def test_invalid_membership_id_is_rejected_without_calling_membership_service(db_url):
    fake = FakeEurekaClient()
    response, _, _ = await post_session(db_url, fake, {**SESSION, "membership_id": "U-100"})

    assert response.status_code == 422
    assert fake.calls == []


@pytest.mark.anyio
async def test_active_membership_does_not_bypass_local_rules(db_url):
    # Karnet jest w porządku, ale termin koliduje z S-001 (9:00–10:00) — decyduje reguła Trainer Service.
    fake = FakeEurekaClient()
    response, sessions, _ = await post_session(db_url, fake, {**SESSION, "starts_at": "2026-11-16T09:30:00",
                                                              "ends_at": "2026-11-16T10:30:00"})

    assert response.status_code == 409
    assert response.json() == {"detail": "Trainer already has a session at this time"}
    assert len(fake.calls) == 1
    assert [s["id"] for s in sessions] == ["S-001"]