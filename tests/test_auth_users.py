from conftest import auth


def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json["data"]["database"]["collections"]["users"] >= 60


def test_register_login_me(client):
    payload = {"name": "Alex Doe", "email": "Alex.Doe@Example.org", "password": "Passw0rdX"}
    res = client.post("/api/auth/register", json=payload)
    assert res.status_code == 201
    user = res.json["data"]["user"]
    assert user["email"] == "alex.doe@example.org"
    assert "password_hash" not in user
    assert user["trust_score"] is not None and user["trust_profile"]["tier"] == "new"
    assert user["profile"]["location"]["community"]["zone"]["code"]  # 5-level nesting

    assert client.post("/api/auth/register", json=payload).status_code == 409

    res = client.post("/api/auth/login", json={"email": "alex.doe@example.org", "password": "Passw0rdX"})
    assert res.status_code == 200
    token = res.json["data"]["access_token"]
    me = client.get("/api/auth/me", headers=auth(token)).json["data"]
    assert me["account"]["login_history"][-1]["device"]["browser"]["name"]


def test_auth_errors(client):
    assert client.post("/api/auth/login", json={"email": "admin@borrowloop.com", "password": "nope"}).status_code == 401
    assert client.post("/api/auth/register", json={"name": "X Y", "email": "bad", "password": "Secret123"}).status_code == 422
    assert client.post("/api/auth/register", json={"name": "X Y", "email": "a@b.co", "password": "short"}).status_code == 422
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers=auth("garbage")).status_code == 401
    assert client.post("/api/auth/login", data="not json").status_code == 400


def test_profile_privacy_and_update(client, make_user):
    alice, alice_h = make_user("lender")
    bob, bob_h = make_user("borrower")
    public = client.get(f"/api/users/{alice['user_id']}", headers=bob_h).json["data"]
    assert "email" not in public and "preferences" not in public
    private = client.get(f"/api/users/{alice['user_id']}", headers=alice_h).json["data"]
    assert private["email"]

    assert client.put(f"/api/users/{alice['user_id']}", headers=bob_h, json={"bio": "hacked"}).status_code == 403
    res = client.put(f"/api/users/{alice['user_id']}", headers=alice_h, json={
        "bio": "I lend tools", "neighbourhood": "Peckham",
        "preferences": {"notifications": {"events": {"return_reminders": {"schedule": {"days_before_due": 3}}}}},
    })
    assert res.status_code == 200
    data = res.json["data"]
    assert data["profile"]["location"]["community"]["neighbourhood"] == "Peckham"
    assert data["preferences"]["notifications"]["events"]["return_reminders"]["schedule"]["days_before_due"] == 3
    # sibling settings preserved by the nested merge
    assert data["preferences"]["notifications"]["events"]["return_reminders"]["schedule"]["time_of_day"] == "09:00"
    # non-admins cannot change their own role
    assert client.put(f"/api/users/{alice['user_id']}", headers=alice_h, json={"role": "admin"}).status_code == 403


def test_trust_score_endpoint(client, make_user):
    user, headers = make_user()
    res = client.get(f"/api/users/{user['user_id']}/trust-score", headers=headers)
    assert res.status_code == 200
    body = res.json["data"]
    assert set(body["breakdown"]) == {"return_reliability", "review_rating", "account_standing",
                                      "lending_reliability", "experience", "conduct_penalty"}
    assert abs(sum(c["points"] for c in body["breakdown"].values()) - body["trust_score"]) < 0.2


def test_seeded_demo_accounts(client):
    for email, pw in (("lender@borrowloop.com", "Password@123"), ("borrower@borrowloop.com", "Password@123"),
                      ("moderator@borrowloop.com", "Admin@123")):
        assert client.post("/api/auth/login", json={"email": email, "password": pw}).status_code == 200
