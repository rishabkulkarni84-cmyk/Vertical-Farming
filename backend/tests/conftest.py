import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="verdant-test-")
os.environ.update({
    "DATABASE_URL": os.environ.get("TEST_DATABASE_URL", f"sqlite:///{_tmp}/test.db"),
    "ENVIRONMENT": "test",
    "SIMULATOR_ENABLED": "false",
    "STORAGE_DIR": f"{_tmp}/storage",
    "SECRET_KEY": "test-secret-key-for-pytest-only-0123456789",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

H = {"X-Requested-With": "verdant"}


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


_n = [0]


def new_user(client: TestClient) -> TestClient:
    _n[0] += 1
    c = TestClient(app)
    r = c.post("/api/auth/signup", json={"email": f"u{_n[0]}@example.com", "name": f"User {_n[0]}", "password": "password123"}, headers=H)
    assert r.status_code == 201, r.text
    c.headers.update(H)
    return c


@pytest.fixture
def user(client):
    return new_user(client)


@pytest.fixture
def farm(user):
    """10 ft × 8 ft × 9 ft room, 1 ft grid, door on the north wall."""
    f = user.post("/api/farms", json={"name": "Test farm", "budget": 3000, "currency": "USD", "preferred_crop": "leaf-lettuce"}).json()
    r = user.put(f"/api/farms/{f['id']}/room", json={"length": 10, "width": 8, "height": 9, "unit": "ft", "grid_cell": 1,
                                                     "grid_cell_unit": "ft", "temperature_c": 21, "humidity_pct": 60})
    assert r.status_code == 200, r.text
    r = user.post(f"/api/farms/{f['id']}/obstacles", json={"kind": "DOOR", "label": "Door", "x": 1.2, "y": 0, "w": 0.8, "d": 0.05,
                                                           "clearance_m": 0.8})
    assert r.status_code == 201
    return user, f["id"]
