"""Borrow request document builder.

Nesting example (5 levels): negotiation.thread[].proposal.terms.pickup.window
                (5 levels): logistics.pickup.location.community.zone
"""
from ..utils.helpers import public_user_summary
from .common import money


def build_borrow_request(*, request_id, item, borrower, owner, start_date, return_date, created_at,
                         duration_days, message=None, pickup_method="collection",
                         pickup_window=None, message_id=None):
    pickup_window = pickup_window or {"from": "18:00", "to": "20:00"}
    item_location = item.get("pickup", {}).get("location", {})
    owner_summary = public_user_summary(owner)
    borrower_summary = public_user_summary(borrower)
    return {
        "request_id": request_id,
        "item_id": item["item_id"],
        "borrower_id": borrower["user_id"],
        "owner_id": item["owner_id"],
        "start_date": start_date,
        "return_date": return_date,
        "status": "pending",
        "created_at": created_at,
        "updated_at": created_at,
        "duration_days": duration_days,
        "message": message,
        "item_snapshot": {
            "name": item["name"],
            "category": item["category"],
            "condition": item["condition"],
            "deposit": money(item.get("deposit", 0)),
            "owner": {"user_id": owner_summary["user_id"], "name": owner_summary["name"],
                      "trust": owner_summary["trust"]},
        },
        "borrower_snapshot": {
            "name": borrower_summary["name"],
            "trust": borrower_summary["trust"],
            "verification": {"level": borrower.get("verification", {}).get("level")},
            "community": borrower_summary["community"],
        },
        "logistics": {
            "pickup": {
                "method": pickup_method,
                "location": item_location,
                "scheduled": {"date": start_date, "window": pickup_window},
            },
            "return": {
                "method": pickup_method,
                "location": item_location,
                "scheduled": {"date": return_date, "window": pickup_window},
            },
        },
        "negotiation": {
            "rounds": 1,
            "thread": [
                {
                    "message_id": message_id or f"{request_id}-M1",
                    "sender_id": borrower["user_id"],
                    "sent_at": created_at,
                    "body": message,
                    "proposal": {
                        "start_date": start_date,
                        "return_date": return_date,
                        "terms": {
                            "deposit": money(item.get("deposit", 0)),
                            "pickup": {"method": pickup_method, "window": pickup_window},
                        },
                    },
                }
            ],
        },
        "status_history": [
            {"status": "pending", "at": created_at,
             "by": {"user_id": borrower["user_id"], "role": "borrower"}, "note": "Request submitted"}
        ],
        "decision": None,
        "cancellation": None,
        "transaction_id": None,
    }
