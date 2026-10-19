"""Unit tests for the pure business-rule functions (no HTTP)."""
from datetime import datetime, timezone

from app.models import build_borrow_request, build_item, build_transaction, build_user
from app.services.lending_service import assess_return
from app.services.trust_service import compute_trust_profile

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


def _fixture(deposit=100):
    ts = "2026-01-01T10:00:00Z"
    lender = build_user(user_id="USR-1", name="Len Der", email="l@x.com", password_hash="x", role="lender", created_at=ts)
    borrower = build_user(user_id="USR-2", name="Bo Rower", email="b@x.com", password_hash="x", role="borrower", created_at=ts)
    item = build_item(item_id="ITM-1", owner_id="USR-1", name="Drill", category="tools", description="A drill",
                      condition="good", deposit=deposit, created_at=ts, late_fee_per_day=5)
    req = build_borrow_request(request_id="REQ-1", item=item, borrower=borrower, owner=lender,
                               start_date="2026-05-20", return_date="2026-05-25", created_at=ts, duration_days=5)
    txn = build_transaction(transaction_id="TXN-1", request=req, item=item, lender=lender, borrower=borrower,
                            borrowed_at="2026-05-20T10:00:00Z", created_at="2026-05-20T10:00:00Z")
    return item, txn, borrower


def test_on_time_return_full_refund():
    item, txn, _ = _fixture()
    returned = datetime(2026, 5, 25, 18, 0, tzinfo=timezone.utc)
    done, item_set, _ = assess_return(txn, item, returned, "good")
    assert done["return_assessment"]["on_time"] is True
    assert done["payment"]["deposit"]["status"] == "refunded"
    assert done["payment"]["deposit"]["refunded_amount"] == 100
    assert item_set["availability"] is True


def test_late_return_fee_and_cap():
    item, txn, _ = _fixture()
    returned = datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc)  # ~3 days after the deadline
    done, _, _ = assess_return(txn, item, returned, "good")
    assert done["return_assessment"]["days_late"] == 3
    assert done["payment"]["late_fee"]["amount"] == 15
    assert done["payment"]["deposit"]["status"] == "partially_refunded"

    very_late = datetime(2026, 6, 30, tzinfo=timezone.utc)
    done, _, _ = assess_return(txn, item, very_late, "good")
    assert done["payment"]["late_fee"]["amount"] == 50  # capped at 50% of the deposit


def test_major_damage_forfeits_deposit():
    item, txn, _ = _fixture()
    returned = datetime(2026, 5, 25, 12, tzinfo=timezone.utc)
    done, _, _ = assess_return(txn, item, returned, "poor")
    assert done["return_assessment"]["damage"]["severity"] == "major"
    assert done["payment"]["deposit"]["status"] == "forfeited"


def test_trust_rewards_good_history_and_penalises_bad():
    item, txn, borrower = _fixture()
    good, _, _ = assess_return(txn, item, datetime(2026, 5, 25, 12, tzinfo=timezone.utc), "good")
    bad, _, _ = assess_return(txn, item, datetime(2026, 6, 3, 12, tzinfo=timezone.utc), "poor")
    reviews_good = [{"rating": 5}] * 5
    reviews_bad = [{"rating": 1}] * 5
    new = compute_trust_profile(borrower, borrowed=[], lent=[], reviews_received=[], now=NOW)
    great = compute_trust_profile(borrower, borrowed=[good] * 8, lent=[], reviews_received=reviews_good, now=NOW)
    poor = compute_trust_profile(borrower, borrowed=[bad] * 8, lent=[], reviews_received=reviews_bad, now=NOW)
    assert new["tier"] == "new"
    assert great["score"] > new["score"] > poor["score"]
    assert poor["tier"] in ("at_risk", "bronze")
    assert 0 <= poor["score"] <= 100 and 0 <= great["score"] <= 100
    assert round(sum(c["points"] for c in great["breakdown"].values()), 1) == great["score"]


def test_suspended_users_are_capped():
    _, _, borrower = _fixture()
    borrower["account"]["status"] = "suspended"
    profile = compute_trust_profile(borrower, borrowed=[], lent=[], reviews_received=[{"rating": 5}] * 10, now=NOW)
    assert profile["score"] <= 40
