def test_public_listing_and_search(client):
    res = client.get("/api/items")
    assert res.status_code == 200
    assert res.json["meta"]["total"] > 50
    assert all(i["availability"] for i in res.json["data"])

    res = client.get("/api/items/search?category=electronics&available=all&per_page=100")
    assert res.status_code == 200
    assert res.json["data"] and all(i["category"] == "electronics" for i in res.json["data"])

    res = client.get("/api/items/search?name=calculator&available=all")
    assert any("Calculator" in i["name"] for i in res.json["data"])

    assert client.get("/api/items/search?category=spaceships").status_code == 422
    assert client.get("/api/items?sort=-deposit").status_code == 200
    assert client.get("/api/items?sort=password").status_code == 422


def test_item_detail_is_deeply_nested(client):
    item_id = client.get("/api/items").json["data"][0]["item_id"]
    item = client.get(f"/api/items/{item_id}").json["data"]
    assert item["pickup"]["location"]["community"]["zone"]["code"]
    assert "major" in item["pricing"]["deposit"]["refund_policy"]["deductions"]["damage"]
    assert item["owner"]["trust"]["score"] is not None


def test_item_crud(client, make_user, item_payload):
    owner, owner_h = make_user("lender")
    other, other_h = make_user("borrower")

    assert client.post("/api/items", json=item_payload).status_code == 401
    bad = dict(item_payload, category="weapons")
    assert client.post("/api/items", headers=owner_h, json=bad).status_code == 422
    assert client.post("/api/items", headers=owner_h, json={"name": "x"}).status_code == 422

    res = client.post("/api/items", headers=owner_h, json=item_payload)
    assert res.status_code == 201
    item = res.json["data"]
    assert item["owner_id"] == owner["user_id"] and item["availability"] is True
    assert item["pickup"]["location"]["community"]["neighbourhood"] == "Hackney Central"
    item_id = item["item_id"]

    assert client.put(f"/api/items/{item_id}", headers=other_h, json={"deposit": 1}).status_code == 403
    res = client.put(f"/api/items/{item_id}", headers=owner_h, json={"deposit": 60, "status": "paused"})
    assert res.status_code == 200
    updated = res.json["data"]
    assert updated["pricing"]["deposit"]["refund_policy"]["deductions"]["damage"]["major"] == 60
    assert updated["availability"] is False
    assert client.get(f"/api/items/{item_id}").status_code == 404  # paused items are hidden from guests

    assert client.delete(f"/api/items/{item_id}", headers=other_h).status_code == 403
    assert client.delete(f"/api/items/{item_id}", headers=owner_h).status_code == 200
    assert client.get(f"/api/items/{item_id}").status_code == 404


def test_borrower_listing_becomes_lender(client, make_user, item_payload):
    user, headers = make_user("borrower")
    assert client.post("/api/items", headers=headers, json=item_payload).status_code == 201
    assert client.get("/api/auth/me", headers=headers).json["data"]["role"] == "lender"
