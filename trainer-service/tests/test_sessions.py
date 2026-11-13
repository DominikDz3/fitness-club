def session(start, end, trainer="T-001", membership="M-002"):
    return {"trainer_id": trainer, "membership_id": membership,
            "starts_at": f"2026-11-16T{start}:00", "ends_at": f"2026-11-16T{end}:00"}


def test_list_and_details(client):
    r = client.get("/sessions")
    assert r.status_code == 200
    assert [s["id"] for s in r.json()] == ["S-001"]

    r = client.get("/sessions/S-001")
    assert r.status_code == 200
    assert r.json()["membership_id"] == "M-001"
    assert r.json()["status"] == "scheduled"


def test_unknown_session_returns_404(client):
    r = client.get("/sessions/S-999")
    assert r.status_code == 404
    assert r.json()["detail"] == "Session not found"


def test_book_session_inside_availability_then_read(client):
    r = client.post("/sessions", json=session("10:00", "11:00"))
    assert r.status_code == 201
    assert r.json()["id"] == "S-002"

    r = client.get("/sessions/S-002")
    assert r.status_code == 200
    assert r.json()["starts_at"] == "2026-11-16T10:00:00"
    assert r.json()["status"] == "scheduled"


def test_session_outside_availability_returns_409_and_keeps_state(client):
    r = client.post("/sessions", json=session("11:30", "12:30"))
    assert r.status_code == 409
    assert r.json()["detail"] == "Session is outside trainer availability"
    assert len(client.get("/sessions").json()) == 1


def test_session_overlapping_another_returns_409_and_keeps_state(client):
    r = client.post("/sessions", json=session("09:30", "10:30"))
    assert r.status_code == 409
    assert r.json()["detail"] == "Trainer already has a session at this time"
    assert len(client.get("/sessions").json()) == 1


def test_too_short_session_returns_422_and_keeps_state(client):
    r = client.post("/sessions", json=session("10:00", "10:15"))
    assert r.status_code == 422
    assert "30 to 120 minutes" in r.json()["detail"][0]["msg"]
    assert len(client.get("/sessions").json()) == 1


def test_invalid_membership_id_returns_422(client):
    r = client.post("/sessions", json=session("10:00", "11:00", membership="U-100"))
    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"] == ["body", "membership_id"]


def test_session_with_unknown_trainer_returns_404(client):
    r = client.post("/sessions", json=session("10:00", "11:00", trainer="T-999"))
    assert r.status_code == 404
    assert r.json()["detail"] == "Trainer not found"


def test_session_with_inactive_trainer_returns_409(client):
    r = client.post("/sessions", json=session("10:00", "11:00", trainer="T-002"))
    assert r.status_code == 409
    assert r.json()["detail"] == "Trainer is inactive"


def test_cancel_session_frees_the_slot(client):
    r = client.patch("/sessions/S-001/cancel")
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"

    assert client.get("/sessions/S-001").json()["status"] == "cancelled"
    assert client.post("/sessions", json=session("09:00", "10:00")).status_code == 201


def test_cancel_cancelled_session_returns_409_and_keeps_state(client):
    assert client.patch("/sessions/S-001/cancel").status_code == 200
    r = client.patch("/sessions/S-001/cancel")
    assert r.status_code == 409
    assert r.json()["detail"] == "Cannot cancel session with status 'cancelled'"
    assert client.get("/sessions/S-001").json()["status"] == "cancelled"
