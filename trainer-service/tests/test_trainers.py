def test_list_and_details(client):
    r = client.get("/trainers")
    assert r.status_code == 200
    assert [t["id"] for t in r.json()] == ["T-001", "T-002"]

    r = client.get("/trainers/T-001")
    assert r.status_code == 200
    assert r.json() == {"id": "T-001", "name": "Anna Nowak",
                        "specialization": "strength", "status": "active"}


def test_unknown_trainer_returns_404(client):
    r = client.get("/trainers/T-999")
    assert r.status_code == 404
    assert r.json()["detail"] == "Trainer not found"


def test_create_trainer_then_read(client):
    r = client.post("/trainers", json={"name": "Ewa Zielinska", "specialization": "pilates"})
    assert r.status_code == 201
    created = r.json()
    assert created["id"] == "T-003"
    assert created["status"] == "active"

    r = client.get("/trainers/T-003")
    assert r.status_code == 200
    assert r.json()["name"] == "Ewa Zielinska"


def test_create_trainer_with_empty_name_returns_422_and_keeps_state(client):
    r = client.post("/trainers", json={"name": "", "specialization": "yoga"})
    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"] == ["body", "name"]
    assert len(client.get("/trainers").json()) == 2


def test_activate_inactive_trainer(client):
    r = client.patch("/trainers/T-002/status", json={"status": "active"})
    assert r.status_code == 200
    assert client.get("/trainers/T-002").json()["status"] == "active"


def test_unknown_status_returns_422(client):
    r = client.patch("/trainers/T-001/status", json={"status": "on_holiday"})
    assert r.status_code == 422
    assert client.get("/trainers/T-001").json()["status"] == "active"


def test_deactivate_trainer_with_scheduled_session_returns_409_and_keeps_state(client):
    r = client.patch("/trainers/T-001/status", json={"status": "inactive"})
    assert r.status_code == 409
    assert "scheduled sessions" in r.json()["detail"]
    assert client.get("/trainers/T-001").json()["status"] == "active"


def test_deactivate_after_cancelling_sessions(client):
    assert client.patch("/sessions/S-001/cancel").status_code == 200
    r = client.patch("/trainers/T-001/status", json={"status": "inactive"})
    assert r.status_code == 200
    assert r.json()["status"] == "inactive"
