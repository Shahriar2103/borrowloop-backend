from datetime import date, timedelta


def test_admin_requires_admin_role(client, make_user):
    _, headers = make_user()
    for path in ("/api/admin/users", "/api/admin/items", "/api/admin/transactions", "/api/admin/reports",
                 "/api/admin/analytics"):
        assert client.get(path, headers=headers).status_code == 403


def test_admin_lists(client, admin_headers):
    users = client.get("/api/admin/users?role=lender&sort=-trust_score", headers=admin_headers).json
    scores = [u["trust_score"] for u in users["data"]]
    assert scores == sorted(scores, reverse=True)
    assert users["data"][0]["email"]  # admins see private fields

    assert client.get("/api/admin/items?flagged=true", headers=admin_headers).json["meta"]["total"] >= 1
    overdue = client.get("/api/admin/transactions?overdue=true", headers=admin_headers).json["data"]
    assert all(t["is_overdue"] for t in overdue)
    open_reports = client.get("/api/admin/reports?status=open", headers=admin_headers).json["data"]
    assert all(r["status"] == "open" for r in open_reports)


def test_analytics(client, admin_headers):
    data = client.get("/api/admin/analytics", headers=admin_headers).json["data"]
    for key in ("users", "items", "borrow_requests", "transactions", "reviews", "reports", "borrowing_activity"):
        assert key in data
    assert len(data["borrowing_activity"]["monthly"]) == 12
    assert data["transactions"]["completed"] > 100
    assert data["items"]["by_category"]["electronics"]["total"] > 0


def test_report_and_resolve_with_warning(client, make_user, admin_headers):
    reporter, reporter_h = make_user()
    target, target_h = make_user()
    res = client.post("/api/reports", headers=reporter_h, json={
        "target_type": "user", "target_id": target["user_id"], "category": "conduct",
        "subcategory": "rude_communication", "description": "Was very rude in messages."})
    assert res.status_code == 201
    report = res.json["data"]
    assert report["sla"]["escalation"]["policy"]["hours"]["first_response"] == 24
    assert client.post("/api/reports", headers=reporter_h, json={
        "target_type": "user", "target_id": target["user_id"], "category": "conduct",
        "description": "Again, very rude."}).status_code == 409
    assert client.get("/api/reports/mine", headers=reporter_h).json["meta"]["total"] == 1

    rid = report["report_id"]
    assert client.put(f"/api/admin/reports/{rid}", headers=admin_headers, json={"status": "resolved"}).status_code == 422
    res = client.put(f"/api/admin/reports/{rid}", headers=admin_headers, json={"status": "under_review", "note": "Checking"})
    assert res.json["data"]["assigned_to"] == "USR-00001"
    res = client.put(f"/api/admin/reports/{rid}", headers=admin_headers,
                     json={"resolution": {"action": "warning", "notes": "First warning"}})
    assert res.status_code == 200
    resolved = res.json["data"]
    assert resolved["status"] == "resolved"
    assert resolved["resolution"]["effects"]["trust"]["penalty_applied"]["points"] > 0
    assert len(resolved["activity_log"]) == 3

    me = client.get("/api/auth/me", headers=target_h).json["data"]
    assert me["account"]["moderation"]["warnings"][0]["report_id"] == rid


def test_suspension_blocks_login(client, make_user, admin_headers):
    reporter, reporter_h = make_user()
    target, target_h = make_user()
    rid = client.post("/api/reports", headers=reporter_h, json={
        "target_type": "user", "target_id": target["user_id"], "category": "fraud",
        "subcategory": "deposit_scam", "description": "Asked me to pay the deposit outside the app."}).json["data"]["report_id"]
    client.put(f"/api/admin/reports/{rid}", headers=admin_headers,
               json={"resolution": {"action": "suspend_user", "suspension_days": 7}})
    assert client.get("/api/auth/me", headers=target_h).status_code == 403
    trust = client.get(f"/api/users/{target['user_id']}/trust-score", headers=admin_headers).json["data"]
    assert trust["trust_score"] <= 40 and trust["tier"] in ("at_risk", "new")


def test_admin_remove_item_and_delete_user(client, make_user, admin_headers, item_payload):
    lender, lender_h = make_user("lender")
    borrower, borrower_h = make_user()
    item = client.post("/api/items", headers=lender_h, json=item_payload).json["data"]
    start = (date.today() + timedelta(days=3)).isoformat()
    end = (date.today() + timedelta(days=5)).isoformat()
    client.post("/api/borrow-requests", headers=borrower_h,
                json={"item_id": item["item_id"], "start_date": start, "return_date": end})

    res = client.delete(f"/api/admin/items/{item['item_id']}", headers=admin_headers, json={"reason": "prohibited"})
    assert res.status_code == 200 and res.json["data"]["requests_cancelled"] == 1
    assert client.get(f"/api/items/{item['item_id']}").status_code == 404

    assert client.delete("/api/admin/users/USR-00001", headers=admin_headers).status_code == 422  # self
    assert client.delete(f"/api/admin/users/{borrower['user_id']}", headers=admin_headers).status_code == 200
    assert client.get(f"/api/users/{borrower['user_id']}", headers=admin_headers).status_code == 404
    assert client.get("/api/auth/me", headers=borrower_h).status_code == 401
