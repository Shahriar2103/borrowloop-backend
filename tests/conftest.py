import itertools
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app  # noqa: E402

_counter = itertools.count(1)


@pytest.fixture(scope="session")
def app():
    # in-memory database seeded from data/seed - nothing touches a real MongoDB
    return create_app("testing")


@pytest.fixture(scope="session")
def client(app):
    return app.test_client()


def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def make_user(client):
    """Register a fresh user and return (user, headers)."""

    def _make(role="borrower", name=None):
        n = next(_counter)
        res = client.post("/api/auth/register", json={
            "name": name or f"Test {role.title()} {n}", "email": f"{role}{n}@test.borrowloop.com",
            "password": "Secret123", "role": role, "neighbourhood": "Hackney Central",
        })
        assert res.status_code == 201, res.json
        data = res.json["data"]
        return data["user"], auth(data["access_token"])

    return _make


@pytest.fixture
def admin_headers(client):
    res = client.post("/api/auth/login", json={"email": "admin@borrowloop.com", "password": "Admin@123"})
    assert res.status_code == 200
    return auth(res.json["data"]["access_token"])


@pytest.fixture
def item_payload():
    return {
        "name": "Test Cordless Drill",
        "category": "tools",
        "subcategory": "power_tools",
        "description": "A reliable drill for testing purposes.",
        "condition": "good",
        "deposit": 40,
        "tags": ["drill", "diy"],
        "lending_rules": {"min_days": 1, "max_days": 7},
        "pickup_methods": ["collection", "meetup"],
        "specifications": {"technical": {"motor": {"voltage_v": 18}}},
    }
