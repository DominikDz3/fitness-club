NEW_CLASS = {"name": "Joga", "trainer_id": "T-001", "capacity": 15,
             "starts_at": "2026-11-21T09:00:00", "ends_at": "2026-11-21T10:00:00"}


def test_list_and_details(client):
    r = client.get("/classes")
    assert r.status_code == 200
    assert [c["id"] for c in r.json()] == ["C-001", "C-002"]

    r = client.get("/classes/C-001")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Trening obwodowy"
    assert body["capacity"] == 12
    assert body["status"] == "scheduled"


def test_unknown_class_returns_404(client):
    r = client.get("/classes/C-999")
    assert r.status_code == 404
    assert r.json()["detail"] == "Class not found"


def test_create_then_read(client):
    r = client.post("/classes", json=NEW_CLASS)
    assert r.status_code == 201
    created = r.json()
    assert created["id"] == "C-003"
    assert created["status"] == "scheduled"

    r = client.get("/classes/C-003")
    assert r.status_code == 200
    assert r.json()["name"] == "Joga"
    assert r.json()["starts_at"] == "2026-11-21T09:00:00"


def test_capacity_below_one_returns_422_and_keeps_store(client):
    r = client.post("/classes", json={**NEW_CLASS, "capacity": 0})
    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"] == ["body", "capacity"]
    assert len(client.get("/classes").json()) == 2


def test_too_short_class_returns_422_and_keeps_store(client):
    r = client.post("/classes", json={**NEW_CLASS, "ends_at": "2026-11-21T09:15:00"})
    assert r.status_code == 422
    assert "30 to 120 minutes" in r.json()["detail"][0]["msg"]
    assert len(client.get("/classes").json()) == 2


def test_overlapping_class_of_same_trainer_returns_409_and_keeps_store(client):
    # C-001: T-001, 2026-11-20 18:00–19:00 (scheduled)
    overlapping = {**NEW_CLASS, "starts_at": "2026-11-20T18:30:00", "ends_at": "2026-11-20T19:30:00"}
    r = client.post("/classes", json=overlapping)
    assert r.status_code == 409
    assert r.json()["detail"] == "Trainer already has a class at this time"
    assert len(client.get("/classes").json()) == 2


def test_overlap_with_cancelled_class_or_other_trainer_is_allowed(client):
    # C-002 (T-001, 2026-11-18 17:00–18:00) jest odwołane, więc nie blokuje terminu.
    same_time_as_cancelled = {**NEW_CLASS, "starts_at": "2026-11-18T17:00:00",
                              "ends_at": "2026-11-18T18:00:00"}
    assert client.post("/classes", json=same_time_as_cancelled).status_code == 201

    other_trainer = {**NEW_CLASS, "trainer_id": "T-002", "starts_at": "2026-11-20T18:00:00",
                     "ends_at": "2026-11-20T19:00:00"}
    assert client.post("/classes", json=other_trainer).status_code == 201


def test_finish_scheduled_class(client):
    r = client.patch("/classes/C-001/finish")
    assert r.status_code == 200
    assert r.json()["status"] == "finished"
    assert client.get("/classes/C-001").json()["status"] == "finished"


def test_cancel_scheduled_class(client):
    r = client.patch("/classes/C-001/cancel")
    assert r.status_code == 200
    assert client.get("/classes/C-001").json()["status"] == "cancelled"


def test_cancelled_class_cannot_be_finished_or_cancelled_again(client):
    before = client.get("/classes/C-002").json()

    r = client.patch("/classes/C-002/finish")
    assert r.status_code == 409
    assert r.json()["detail"] == "Cannot change class status from 'cancelled' to 'finished'"

    assert client.patch("/classes/C-002/cancel").status_code == 409
    assert client.get("/classes/C-002").json() == before


def test_finished_class_cannot_be_cancelled(client):
    assert client.patch("/classes/C-001/finish").status_code == 200
    r = client.patch("/classes/C-001/cancel")
    assert r.status_code == 409
    assert client.get("/classes/C-001").json()["status"] == "finished"


def test_status_change_of_unknown_class_returns_404(client):
    assert client.patch("/classes/C-999/cancel").status_code == 404
    assert client.patch("/classes/C-999/finish").status_code == 404