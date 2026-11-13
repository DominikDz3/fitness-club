def test_list_and_details(client):
    r = client.get("/memberships")
    assert r.status_code == 200
    assert len(r.json()) == 2

    r = client.get("/memberships/M-001")
    assert r.status_code == 200
    assert r.json()["member_id"] == "U-100"
    assert r.json()["status"] == "active"


def test_unknown_membership_returns_404(client):
    r = client.get("/memberships/M-999")
    assert r.status_code == 404
    assert r.json()["detail"] == "Membership not found"


def test_create_then_read(client):
    body = {"member_id": "U-300", "type": "gym_only",
            "valid_from": "2026-11-01", "valid_to": "2027-01-31"}
    r = client.post("/memberships", json=body)
    assert r.status_code == 201
    created = r.json()
    assert created["status"] == "active"

    r = client.get(f"/memberships/{created['id']}")
    assert r.status_code == 200
    assert r.json()["member_id"] == "U-300"


def test_invalid_dates_return_422_and_do_not_change_store(client):
    body = {"member_id": "U-300", "type": "open",
            "valid_from": "2026-12-01", "valid_to": "2026-11-01"}
    r = client.post("/memberships", json=body)
    assert r.status_code == 422
    assert len(client.get("/memberships").json()) == 2


def test_duplicate_current_membership_returns_409(client):
    body = {"member_id": "U-100", "type": "open",
            "valid_from": "2027-01-01", "valid_to": "2027-03-31"}
    r = client.post("/memberships", json=body)
    assert r.status_code == 409
    assert "current membership" in r.json()["detail"]
    assert len(client.get("/memberships").json()) == 2


def test_suspend_active_membership_extends_validity(client):
    r = client.patch("/memberships/M-001/suspend", json={"days": 14})
    assert r.status_code == 200

    r = client.get("/memberships/M-001")
    assert r.json()["status"] == "suspended"
    assert r.json()["valid_to"] == "2027-01-14"


def test_suspend_too_long_returns_422_and_keeps_state(client):
    r = client.patch("/memberships/M-001/suspend", json={"days": 45})
    assert r.status_code == 422

    m = client.get("/memberships/M-001").json()
    assert m["status"] == "active"
    assert m["valid_to"] == "2026-12-31"


def test_suspend_already_suspended_returns_409_and_keeps_state(client):
    before = client.get("/memberships/M-002").json()
    r = client.patch("/memberships/M-002/suspend", json={"days": 5})
    assert r.status_code == 409
    assert client.get("/memberships/M-002").json() == before