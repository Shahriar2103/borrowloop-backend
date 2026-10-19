"""Denormalised statistics kept on user and item documents."""
from ..utils.helpers import parse_dt


def refresh_user_stats(db, user_id):
    reqs_as_borrower = list(db.borrow_requests.find({"borrower_id": user_id}, {"status": 1, "item_snapshot.category": 1}))
    borrowed = list(db.transactions.find({"borrower_id": user_id}))
    lent = list(db.transactions.find({"lender_id": user_id}))
    reqs_received = list(db.borrow_requests.find({"owner_id": user_id}, {"status": 1}))
    received = list(db.reviews.find({"reviewed_user_id": user_id, "moderation.status": "published"}, {"rating": 1}))
    given = db.reviews.count_documents({"reviewer_id": user_id})

    completed_b = [t for t in borrowed if t["status"] == "completed"]
    late = sum(1 for t in completed_b if ((t.get("return_assessment") or {}).get("days_late") or 0) > 0)
    categories = {}
    for t in borrowed:
        cat = t.get("item_snapshot", {}).get("category")
        if cat:
            categories[cat] = categories.get(cat, 0) + 1

    decided = [r for r in reqs_received if r["status"] in ("accepted", "rejected")]
    accepted = sum(1 for r in decided if r["status"] == "accepted")
    completed_l = [t for t in lent if t["status"] == "completed"]
    days_lent = 0
    for t in completed_l:
        if t.get("returned_at"):
            days_lent += max(1, (parse_dt(t["returned_at"]) - parse_dt(t["borrowed_at"])).days)

    distribution = {str(i): 0 for i in range(1, 6)}
    for r in received:
        distribution[str(r["rating"])] += 1

    stats = {
        "borrowing": {
            "total_requests": len(reqs_as_borrower),
            "completed": len(completed_b),
            "active": sum(1 for t in borrowed if t["status"] == "active"),
            "late_returns": late,
            "on_time_rate": round((len(completed_b) - late) / len(completed_b), 3) if completed_b else None,
            "categories": dict(sorted(categories.items(), key=lambda kv: -kv[1])),
        },
        "lending": {
            "items_listed": db.items.count_documents({"owner_id": user_id, "status": {"$ne": "removed"}}),
            "requests_received": len(reqs_received),
            "completed": len(completed_l),
            "active": sum(1 for t in lent if t["status"] == "active"),
            "acceptance_rate": round(accepted / len(decided), 3) if decided else None,
            "total_days_lent": days_lent,
        },
        "reviews": {
            "received": {
                "count": len(received),
                "average": round(sum(r["rating"] for r in received) / len(received), 2) if received else None,
                "distribution": distribution,
            },
            "given": {"count": given},
        },
    }
    db.users.update_one({"user_id": user_id}, {"$set": {"stats": stats}})
    return stats


def refresh_item_stats(db, item_id):
    txns = list(db.transactions.find({"item_id": item_id}))
    reviews = list(db.reviews.find({"item_id": item_id, "direction": "borrower_to_lender",
                                    "moderation.status": "published"}, {"rating": 1}))
    days = 0
    for t in txns:
        if t.get("returned_at"):
            days += max(1, (parse_dt(t["returned_at"]) - parse_dt(t["borrowed_at"])).days)
    distribution = {str(i): 0 for i in range(1, 6)}
    for r in reviews:
        distribution[str(r["rating"])] += 1
    last = max((t["borrowed_at"] for t in txns), default=None)
    db.items.update_one({"item_id": item_id}, {"$set": {
        "stats.times_borrowed": len(txns),
        "stats.total_days_lent": days,
        "stats.last_borrowed_at": last,
        "stats.rating": {
            "average": round(sum(r["rating"] for r in reviews) / len(reviews), 2) if reviews else None,
            "count": len(reviews),
            "distribution": distribution,
        },
    }})
