"""Transaction document builder.

Nesting example (5 levels): handover.pickup.condition_check.checklist.cosmetic.score
                (5 levels): payment.deposit.events[].reference.provider
"""
import hashlib

from .common import build_condition_check, money


def payment_reference(seed):
    return "pi_" + hashlib.sha1(seed.encode()).hexdigest()[:20]


def build_transaction(*, transaction_id, request, item, lender, borrower, borrowed_at, created_at,
                      pickup_grade=None, pickup_notes=None):
    grade = pickup_grade or item["condition"]
    deposit_amount = round(float(request.get("item_snapshot", {}).get("deposit", {}).get("amount", item.get("deposit", 0))), 2)
    late_fee = item.get("pricing", {}).get("late_fee", {}).get("per_day", 1.0)
    pickup_location = request.get("logistics", {}).get("pickup", {}).get("location")
    events = []
    if deposit_amount > 0:
        events.append({"type": "hold", "amount": deposit_amount, "at": borrowed_at,
                       "reference": {"provider": "stripe_test", "id": payment_reference(transaction_id + "hold")}})
    return {
        "transaction_id": transaction_id,
        "request_id": request["request_id"],
        "borrowed_at": borrowed_at,
        "returned_at": None,
        "return_condition": None,
        "status": "active",
        "created_at": created_at,
        "updated_at": created_at,
        "item_id": item["item_id"],
        "lender_id": lender["user_id"],
        "borrower_id": borrower["user_id"],
        "due_date": request["return_date"],
        "parties": {
            "lender": {"user_id": lender["user_id"], "name": lender["name"],
                       "trust_at_start": {"score": lender.get("trust_score"),
                                          "tier": lender.get("trust_profile", {}).get("tier")}},
            "borrower": {"user_id": borrower["user_id"], "name": borrower["name"],
                         "trust_at_start": {"score": borrower.get("trust_score"),
                                            "tier": borrower.get("trust_profile", {}).get("tier")}},
        },
        "item_snapshot": {"name": item["name"], "category": item["category"], "condition_at_pickup": grade},
        "handover": {
            "pickup": {
                "at": borrowed_at,
                "method": request.get("logistics", {}).get("pickup", {}).get("method", "collection"),
                "location": pickup_location,
                "confirmations": {
                    "lender": {"confirmed": True, "at": borrowed_at},
                    "borrower": {"confirmed": True, "at": borrowed_at},
                },
                "condition_check": build_condition_check(grade, notes=pickup_notes),
            },
            "return": None,
        },
        "return_assessment": None,
        "payment": {
            "currency": "GBP",
            "deposit": {
                "amount": deposit_amount,
                "status": "held" if deposit_amount > 0 else "not_required",
                "events": events,
                "deductions": {"late_fee": 0.0, "damage_fee": 0.0, "total": 0.0},
                "refunded_amount": None,
            },
            "late_fee": {"per_day": late_fee, "days": 0, "amount": 0.0},
        },
        "timeline": [
            {"event": "transaction_created", "at": created_at,
             "actor": {"user_id": lender["user_id"], "role": "lender"}, "meta": {"request_id": request["request_id"]}},
            {"event": "item_collected", "at": borrowed_at,
             "actor": {"user_id": borrower["user_id"], "role": "borrower"},
             "meta": {"condition": grade, "deposit": money(deposit_amount)}},
        ],
        "reminders": [
            {"type": "return_due_tomorrow", "channel": "push", "scheduled_for": None, "sent": False},
            {"type": "return_due_today", "channel": "email", "scheduled_for": request["return_date"], "sent": False},
        ],
        "dispute": {"open": False, "report_id": None},
    }
