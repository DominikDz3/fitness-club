BLOCK = {"starts_at": "2026-11-17T08:00:00", "ends_at": "2026-11-17T14:00:00"}


def test_list_availability_of_trainer(client):
    r = client.get("/trainers/T-001/availability")
    assert r.status_code == 200
    assert [b["id"] for b in r.json()] == ["A-001", "A-002"]


def test_trainer_without_blocks_returns_empty_list(client):
    r = client.get("/trainers/T-002/availability")
    assert r.status_code == 200
    assert r.json() == []


def test_availability_of_unknown_trainer_returns_404(client):
    assert client.get("/trainers/T-999/availability").status_code == 404
    assert client.post("/trainers/T-999/availability", json=BLOCK).status_code == 404


def test_add_block_then_read(client):
    r = client.post("/trainers/T-001/availability", json=BLOCK)
    assert r.status_code == 201
    assert r.json()["id"] == "A-003"

    blocks = client.get("/trainers/T-001/availability").json()
    assert blocks[-1] == {"id": "A-003", "trainer_id": "T-001", **BLOCK}


def test_block_touching_existing_one_is_allowed(client):
    body = {"starts_at": "2026-11-16T12:00:00", "ends_at": "2026-11-16T14:00:00"}
    assert client.post("/trainers/T-001/availability", json=body).status_code == 201


def test_overlapping_block_returns_409_and_keeps_state(client):
    body = {"starts_at": "2026-11-16T11:00:00", "ends_at": "2026-11-16T13:00:00"}
    r = client.post("/trainers/T-001/availability", json=body)
    assert r.status_code == 409
    assert r.json()["detail"] == "Availability block overlaps an existing block"
    assert len(client.get("/trainers/T-001/availability").json()) == 2


def test_block_ending_before_start_returns_422(client):
    body = {"starts_at": "2026-11-17T14:00:00", "ends_at": "2026-11-17T08:00:00"}
    r = client.post("/trainers/T-001/availability", json=body)
    assert r.status_code == 422
    assert "ends_at must be after starts_at" in r.json()["detail"][0]["msg"]
    assert len(client.get("/trainers/T-001/availability").json()) == 2


def test_block_longer_than_12_hours_returns_422(client):
    body = {"starts_at": "2026-11-17T06:00:00", "ends_at": "2026-11-17T20:00:00"}
    assert client.post("/trainers/T-001/availability", json=body).status_code == 422


def test_block_with_timezone_returns_422(client):
    body = {"starts_at": "2026-11-17T08:00:00Z", "ends_at": "2026-11-17T10:00:00Z"}
    assert client.post("/trainers/T-001/availability", json=body).status_code == 422


def test_block_for_inactive_trainer_returns_409(client):
    r = client.post("/trainers/T-002/availability", json=BLOCK)
    assert r.status_code == 409
    assert r.json()["detail"] == "Trainer is inactive"
    assert client.get("/trainers/T-002/availability").json() == []
