import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from tests.conftest import FakeEurekaClient, MemoryRedis


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_eureka_client_starts_and_stops_with_the_app(db_url):
    fake = FakeEurekaClient()
    app = create_app(database_url=db_url, redis_client=MemoryRedis(), eureka_client=fake)

    async with app.router.lifespan_context(app):
        assert fake.starts == 1 and fake.stops == 0
        assert app.state.eureka_client is fake
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/memberships/M-001")

    assert response.status_code == 200
    assert response.json()["status"] == "active"
    assert fake.starts == fake.stops == 1