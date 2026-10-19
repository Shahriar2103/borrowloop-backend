"""End-to-end: list -> request -> accept -> collect -> return -> review -> trust score."""
from datetime import date, timedelta


def d(offset):
    return (date.today() + timedelta(days=offset)).isoformat()


def test_full_borrowing_lifecycle(client, make_user, item_payload):
    lender, lender_h = make_user("lender")
    borrower, borrower_h = make_user("borrower")
    rival, rival_h = make_user("borrower")

    item = client.post("/api/items", headers=lender_h, json=item_payload).json["data"]
    item_id = item["item_id"]

    # ---- request validation
    base = {"item_id": item_id, "start_date": d(1), "return_date": d(4), "message": "Weekend DIY"}
    assert client.post("/api/borrow-requests", headers=lender_h, json=base).status_code == 422  # own item
    assert client.post("/api/borrow-requests", headers=borrower_h, json=dict(base, start_date=d(-2))).status_code == 422
    assert client.post("/api/borrow-requests", headers=borrower_h, json=dict(base, return_date=d(30))).status_code == 422
    assert client.post("/api/borrow-requests", headers=borrower_h,
                       json=dict(base, pickup_method="delivery")).status_code == 422

    res = client.post("/api/borrow-requests", headers=borrower_h, json=base)
    assert res.status_code == 201, res.json
    req = res.json["data"]
    assert req["status"] == "pending" and req["duration_days"] == 3
    assert req["logistics"]["pickup"]["location"]["community"]["zone"]["code"]
    request_id = req["request_id"]
    assert client.post("/api/borrow-requests", headers=borrower_h, json=base).status_code == 409  # duplicate

    rival_req = client.post("/api/borrow-requests", headers=rival_h,
                            json=dict(base, start_date=d(2), return_date=d(5))).json["data"]

    # ---- borrower edits dates (counter-proposal) while pending
    res = client.put(f"/api/borrow-requests/{request_id}", headers=borrower_h,
                     json={"start_date": d(1), "return_date": d(3), "message": "Actually just 2 days"})
    assert res.status_code == 200
    assert res.json["data"]["negotiation"]["rounds"] == 2

    # ---- decisions
    assert client.put(f"/api/borrow-requests/{request_id}", headers=borrower_h,
                      json={"status": "accepted"}).status_code == 403
    res = client.put(f"/api/borrow-requests/{request_id}", headers=lender_h, json={"status": "accepted"})
    assert res.status_code == 200
    assert rival_req["request_id"] in res.json["data"]["auto_rejected_requests"]
    rival_after = client.get(f"/api/borrow-requests/{rival_req['request_id']}", headers=rival_h).json["data"]
    assert rival_after["status"] == "rejected" and rival_after["decision"]["auto"]["triggered"] is True

    # overlapping request after acceptance is blocked
    res = client.post("/api/borrow-requests", headers=rival_h, json=dict(base, start_date=d(2), return_date=d(3)))
    assert res.status_code == 409

    lender_view = client.get("/api/borrow-requests?role=lender&status=accepted", headers=lender_h).json["data"]
    assert [r["request_id"] for r in lender_view] == [request_id]

    # ---- collection
    res = client.post("/api/transactions", headers=lender_h, json={"request_id": request_id, "condition": "good"})
    assert res.status_code == 201, res.json
    txn = res.json["data"]
    txn_id = txn["transaction_id"]
    assert txn["status"] == "active" and txn["payment"]["deposit"]["status"] == "held"
    assert txn["handover"]["pickup"]["condition_check"]["checklist"]["cosmetic"]["score"] == 4
    assert client.post("/api/transactions", headers=lender_h, json={"request_id": request_id}).status_code == 409
    assert client.get(f"/api/items/{item_id}").json["data"]["availability"] is False
    active = client.get("/api/transactions?role=borrower", headers=borrower_h).json["data"]
    assert [t["transaction_id"] for t in active] == [txn_id]

    # cannot review or cancel while active
    assert client.post("/api/reviews", headers=borrower_h, json={"transaction_id": txn_id, "rating": 5}).status_code == 409
    assert client.delete(f"/api/borrow-requests/{request_id}", headers=borrower_h).status_code == 409

    # ---- return (only the lender confirms it)
    assert client.put(f"/api/transactions/{txn_id}", headers=borrower_h,
                      json={"return_condition": "good"}).status_code == 403
    res = client.put(f"/api/transactions/{txn_id}", headers=lender_h,
                     json={"return_condition": "fair", "notes": "Small scratch on the casing"})
    assert res.status_code == 200, res.json
    done = res.json["data"]
    assert done["status"] == "completed" and done["return_condition"] == "fair"
    assert done["return_assessment"]["on_time"] is True
    assert done["return_assessment"]["damage"]["severity"] == "minor"
    assert done["payment"]["deposit"]["status"] == "partially_refunded"
    assert done["payment"]["deposit"]["deductions"]["damage_fee"] == 10.0
    assert client.put(f"/api/transactions/{txn_id}", headers=lender_h,
                      json={"return_condition": "fair"}).status_code == 409

    item_after = client.get(f"/api/items/{item_id}").json["data"]
    assert item_after["availability"] is True and item_after["condition"] == "fair"
    assert item_after["stats"]["times_borrowed"] == 1

    history = client.get("/api/transactions/history", headers=borrower_h).json["data"]
    assert history[0]["transaction_id"] == txn_id

    # ---- reviews both ways
    res = client.post("/api/reviews", headers=borrower_h, json={
        "transaction_id": txn_id, "rating": 5, "comment": "Great lender!",
        "aspects": {"communication": 5, "item_accuracy": 4}})
    assert res.status_code == 201
    review = res.json["data"]
    assert review["reviewed_user_id"] == lender["user_id"] and review["direction"] == "borrower_to_lender"
    assert review["ratings"]["aspects"]["item_accuracy"]["score"] == 4
    assert client.post("/api/reviews", headers=borrower_h, json={"transaction_id": txn_id, "rating": 4}).status_code == 409
    assert client.post("/api/reviews", headers=rival_h, json={"transaction_id": txn_id, "rating": 1}).status_code == 403
    assert client.post("/api/reviews", headers=lender_h, json={"transaction_id": txn_id, "rating": 4}).status_code == 201

    reviews = client.get(f"/api/reviews/{lender['user_id']}", headers=borrower_h).json
    assert reviews["meta"]["total"] == 1 and reviews["meta"]["summary"]["average"] == 5.0

    # response + helpful vote
    rid = review["review_id"]
    assert client.post(f"/api/reviews/{rid}/response", headers=lender_h, json={"comment": "Thanks!"}).status_code == 200
    assert client.post(f"/api/reviews/{rid}/helpful", headers=rival_h).status_code == 200
    assert client.post(f"/api/reviews/{rid}/helpful", headers=rival_h).status_code == 409

    # ---- trust score moved off the 'new' tier and history recorded the change
    trust = client.get(f"/api/users/{lender['user_id']}/trust-score", headers=lender_h).json["data"]
    assert trust["tier"] != "new"
    assert trust["breakdown"]["review_rating"]["details"]["reviews"] == 1
    assert any(h["reason"].startswith("review_received") for h in trust["history"])


def test_cancel_after_acceptance_hits_trust(client, make_user, item_payload):
    lender, lender_h = make_user("lender")
    borrower, borrower_h = make_user("borrower")
    item = client.post("/api/items", headers=lender_h, json=item_payload).json["data"]
    req = client.post("/api/borrow-requests", headers=borrower_h,
                      json={"item_id": item["item_id"], "start_date": d(5), "return_date": d(7)}).json["data"]
    client.put(f"/api/borrow-requests/{req['request_id']}", headers=lender_h, json={"status": "accepted"})
    before = client.get(f"/api/users/{borrower['user_id']}/trust-score", headers=borrower_h).json["data"]["trust_score"]
    res = client.delete(f"/api/borrow-requests/{req['request_id']}", headers=borrower_h, json={"reason": "Plans changed"})
    assert res.status_code == 200
    cancelled = res.json["data"]
    assert cancelled["status"] == "cancelled" and cancelled["cancellation"]["after_acceptance"] is True
    after = client.get(f"/api/users/{borrower['user_id']}/trust-score", headers=borrower_h).json["data"]["trust_score"]
    assert after < before
    # the dates are free again
    item_now = client.get(f"/api/items/{item['item_id']}").json["data"]
    assert item_now["availability_details"]["calendar"]["booked"] == []


def test_min_trust_score_rule(client, make_user, item_payload):
    lender, lender_h = make_user("lender")
    borrower, borrower_h = make_user("borrower")
    payload = dict(item_payload, lending_rules={"min_days": 1, "max_days": 7, "min_trust_score": 95})
    item = client.post("/api/items", headers=lender_h, json=payload).json["data"]
    res = client.post("/api/borrow-requests", headers=borrower_h,
                      json={"item_id": item["item_id"], "start_date": d(2), "return_date": d(4)})
    assert res.status_code == 403 and res.json["error"]["code"] == "trust_too_low"
