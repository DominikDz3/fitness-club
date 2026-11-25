from datetime import date

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import FakeEurekaClient, MemoryRedis


def app_on(db_url, today):
    """Aplikacja z wybraną "dzisiejszą" datą (wstrzyknięty zegar)."""
    return TestClient(create_app(database_url=db_url, redis_client=MemoryRedis(),
                                 eureka_client=FakeEurekaClient(), today=lambda: today))


def test_pause_still_running_keeps_suspended(db_url):
    with app_on(db_url, date(2026, 10, 24)) as client:
        m002 = client.get("/memberships/M-002").json()
    assert m002["status"] == "suspended"
    assert m002["suspended_until"] == "2026-10-25"


def test_membership_becomes_active_when_pause_ends(db_url):
    with app_on(db_url, date(2026, 10, 25)) as client:
        m002 = client.get("/memberships/M-002").json()
    assert m002["status"] == "active"
    assert m002["suspended_until"] is None

    with app_on(db_url, date(2026, 10, 1)) as client:
        assert client.get("/memberships/M-002").json()["status"] == "active"


def test_membership_expires_after_valid_to(db_url):
    with app_on(db_url, date(2027, 1, 1)) as client:
        r = client.get("/memberships")
    statuses = {m["id"]: m["status"] for m in r.json()}
    assert statuses == {"M-001": "expired", "M-002": "expired"}


def test_expired_membership_cannot_be_suspended(db_url):
    with app_on(db_url, date(2027, 1, 1)) as client:
        r = client.patch("/memberships/M-001/suspend", json={"days": 5})
    assert r.status_code == 409
    assert r.json()["detail"] == "Cannot suspend membership with status 'expired'"


def test_expired_membership_does_not_block_new_one(db_url):
    body = {"member_id": "U-100", "type": "open", "valid_from": "2027-01-01", "valid_to": "2027-03-31"}
    with app_on(db_url, date(2027, 1, 1)) as client:
        r = client.post("/memberships", json=body)
    assert r.status_code == 201
    assert r.json()["status"] == "active"


def test_resume_after_pause_ended_returns_409(db_url):
    with app_on(db_url, date(2026, 11, 1)) as client:
        r = client.patch("/memberships/M-002/resume")
    assert r.status_code == 409
    assert r.json()["detail"] == "Cannot resume membership with status 'active'"


def test_suspend_counts_days_from_injected_today(db_url):
    with app_on(db_url, date(2026, 11, 2)) as client:
        r = client.patch("/memberships/M-001/suspend", json={"days": 14})
    assert r.status_code == 200
    assert r.json()["suspended_until"] == "2026-11-16"
    assert r.json()["valid_to"] == "2027-01-14"