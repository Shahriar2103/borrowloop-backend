"""Administrator endpoints: users, items, transactions, reports and analytics."""
from collections import Counter, defaultdict
from datetime import timedelta

from flask import Blueprint, g, request

from ..constants import (ACCOUNT_STATUSES, CATEGORIES, REPORT_PRIORITIES, REPORT_STATUSES,
                         RESOLUTION_ACTIONS, ROLES, TRANSACTION_STATUSES)
from ..database import ITEMS, REPORTS, REQUESTS, REVIEWS, TRANSACTIONS, USERS, get_db
from ..services.lending_service import due_deadline
from ..services.stats_service import refresh_user_stats
from ..services.trust_service import recalculate_trust
from ..utils import validation as v
from ..utils.decorators import admin_required
from ..utils.helpers import (arg_bool, clean, clean_user, iso, now_iso, paginate, parse_dt, parse_sort,
                             regex_contains, utcnow)
from ..utils.responses import ApiError, success
from .items import item_summary
from .transactions import with_overdue

bp = Blueprint("admin", __name__, url_prefix="/api/admin")


# ------------------------------------------------------------------ users
@bp.get("/users")
@admin_required
def list_users():
    query = {}
    if request.args.get("role"):
        query["role"] = v.choice(dict(request.args), "role", ROLES)
    if request.args.get("status"):
        query["account.status"] = v.choice(dict(request.args), "status", ACCOUNT_STATUSES)
    if request.args.get("q"):
        query["$or"] = [{"name": regex_contains(request.args["q"])}, {"email": regex_contains(request.args["q"])}]
    if request.args.get("tier"):
        query["trust_profile.tier"] = request.args["tier"]
    if request.args.get("neighbourhood"):
        query["profile.location.community.neighbourhood"] = regex_contains(request.args["neighbourhood"])
    sort = parse_sort({"created_at": "created_at", "name": "name", "trust_score": "trust_score",
                       "last_login": "account.last_login_at"}, [("created_at", -1)])
    items, meta = paginate(get_db()[USERS], query, sort=sort, serializer=lambda d: clean_user(d, private=True))
    return success(items, meta=meta)


@bp.delete("/users/<user_id>")
@admin_required
def delete_user(user_id):
    db = get_db()
    user = db[USERS].find_one({"user_id": user_id})
    if not user:
        raise ApiError(f"User '{user_id}' not found.", 404)
    if user_id == g.user["user_id"]:
        raise ApiError("You cannot delete your own admin account.", 422)
    active = db[TRANSACTIONS].count_documents({"status": "active", "$or": [{"borrower_id": user_id}, {"lender_id": user_id}]})
    if active and not arg_bool("force", False):
        raise ApiError(f"User has {active} active transaction(s). Resolve them first or pass ?force=true.", 409)

    now = now_iso()
    open_reqs = list(db[REQUESTS].find({"status": {"$in": ["pending", "accepted"]},
                                        "$or": [{"borrower_id": user_id}, {"owner_id": user_id}]}))
    for r in open_reqs:
        db[REQUESTS].update_one({"request_id": r["request_id"]}, {
            "$set": {"status": "cancelled", "updated_at": now,
                     "cancellation": {"by": g.user["user_id"], "role": "admin", "at": now,
                                      "reason": "Account removed by administrator", "after_acceptance": False}},
            "$push": {"status_history": {"status": "cancelled", "at": now,
                                         "by": {"user_id": g.user["user_id"], "role": "admin"},
                                         "note": "Account removed"}}})
        db[ITEMS].update_one({"item_id": r["item_id"]},
                             {"$pull": {"availability_details.calendar.booked": {"request_id": r["request_id"]}}})
    items = db[ITEMS].update_many({"owner_id": user_id, "status": {"$ne": "removed"}}, {"$set": {
        "status": "removed", "availability": False, "availability_details.status": "unavailable",
        "moderation.status": "removed", "moderation.review": {"by": g.user["user_id"], "at": now,
                                                              "decision": "owner_account_deleted"}}})
    db[USERS].delete_one({"user_id": user_id})
    for other in {r["owner_id"] for r in open_reqs} | {r["borrower_id"] for r in open_reqs}:
        if other != user_id:
            refresh_user_stats(db, other)
    return success({"user_id": user_id, "items_removed": items.modified_count,
                    "requests_cancelled": len(open_reqs)}, message="User removed.")


# ------------------------------------------------------------------ items
@bp.get("/items")
@admin_required
def list_items():
    query = {}
    if request.args.get("status"):
        query["status"] = request.args["status"]
    if request.args.get("category"):
        query["category"] = request.args["category"]
    if request.args.get("owner_id"):
        query["owner_id"] = request.args["owner_id"]
    if request.args.get("q"):
        query["name"] = regex_contains(request.args["q"])
    flagged = arg_bool("flagged")
    if flagged is True:
        query["moderation.flags.0"] = {"$exists": True}
    available = arg_bool("available")
    if available is not None:
        query["availability"] = available
    serializer = clean if request.args.get("view") == "full" else (
        lambda d: item_summary(d) | {"moderation": d.get("moderation")})
    sort = parse_sort({"created_at": "created_at", "name": "name", "deposit": "deposit",
                       "popularity": "stats.times_borrowed"}, [("created_at", -1)])
    items, meta = paginate(get_db()[ITEMS], query, sort=sort, serializer=serializer)
    return success(items, meta=meta)


@bp.delete("/items/<item_id>")
@admin_required
def remove_item(item_id):
    db = get_db()
    item = db[ITEMS].find_one({"item_id": item_id})
    if not item:
        raise ApiError(f"Item '{item_id}' not found.", 404)
    if db[TRANSACTIONS].count_documents({"item_id": item_id, "status": "active"}) and not arg_bool("force", False):
        raise ApiError("Item is on loan. Pass ?force=true to remove it anyway.", 409)
    body = request.get_json(silent=True) or {}
    reason = body.get("reason") if isinstance(body, dict) else None
    now = now_iso()
    if arg_bool("hard", False):
        db[ITEMS].delete_one({"item_id": item_id})
        return success({"item_id": item_id, "deleted": "permanently"}, message="Item permanently deleted.")
    pending = db[REQUESTS].update_many({"item_id": item_id, "status": {"$in": ["pending", "accepted"]},
                                        "transaction_id": None}, {
        "$set": {"status": "cancelled", "updated_at": now,
                 "cancellation": {"by": g.user["user_id"], "role": "admin", "at": now,
                                  "reason": "Listing removed by administrator", "after_acceptance": False}}})
    db[ITEMS].update_one({"item_id": item_id}, {"$set": {
        "status": "removed", "availability": False, "availability_details.status": "unavailable",
        "availability_details.calendar.booked": [], "updated_at": now,
        "moderation.status": "removed",
        "moderation.review": {"by": g.user["user_id"], "at": now, "decision": reason or "removed_by_admin"}}})
    refresh_user_stats(db, item["owner_id"])
    return success({"item_id": item_id, "requests_cancelled": pending.modified_count}, message="Item removed.")


# ------------------------------------------------------------------ transactions
@bp.get("/transactions")
@admin_required
def list_transactions():
    query = {}
    if request.args.get("status"):
        query["status"] = v.choice(dict(request.args), "status", TRANSACTION_STATUSES)
    if request.args.get("user_id"):
        uid = request.args["user_id"]
        query["$or"] = [{"borrower_id": uid}, {"lender_id": uid}]
    if request.args.get("item_id"):
        query["item_id"] = request.args["item_id"]
    if arg_bool("overdue") is True:
        query["status"] = "active"
        query["due_date"] = {"$lt": utcnow().date().isoformat()}  # due_date is a calendar day
    if arg_bool("late") is True:
        query["return_assessment.days_late"] = {"$gt": 0}
    if arg_bool("disputed") is True:
        query["dispute.open"] = True
    sort = parse_sort({"borrowed_at": "borrowed_at", "returned_at": "returned_at", "due_date": "due_date"},
                      [("borrowed_at", -1)])
    items, meta = paginate(get_db()[TRANSACTIONS], query, sort=sort, serializer=with_overdue)
    return success(items, meta=meta)


# ------------------------------------------------------------------ reports
@bp.get("/reports")
@admin_required
def list_reports():
    query = {}
    for arg, field, options in (("status", "status", REPORT_STATUSES), ("priority", "priority", REPORT_PRIORITIES)):
        if request.args.get(arg):
            values = request.args[arg].split(",")
            bad = [x for x in values if x not in options]
            if bad:
                raise ApiError(f"Unknown {arg}.", 422, details={"allowed": options})
            query[field] = {"$in": values}
    if request.args.get("target_type"):
        query["target.type"] = request.args["target_type"]
    if request.args.get("category"):
        query["reason.category"] = request.args["category"]
    sort = parse_sort({"created_at": "created_at", "priority": "priority", "status": "status"}, [("created_at", -1)])
    items, meta = paginate(get_db()[REPORTS], query, sort=sort)
    return success(items, meta=meta)


@bp.get("/reports/<report_id>")
@admin_required
def get_report(report_id):
    report = get_db()[REPORTS].find_one({"report_id": report_id})
    if not report:
        raise ApiError(f"Report '{report_id}' not found.", 404)
    return success(clean(report))


def _subject_user(db, report, explicit_user_id=None):
    target = report["target"]
    if target["type"] == "user":
        return target["id"]
    if target["type"] == "item":
        item = db[ITEMS].find_one({"item_id": target["id"]})
        return item and item["owner_id"]
    if target["type"] == "review":
        review = db[REVIEWS].find_one({"review_id": target["id"]})
        return review and review["reviewer_id"]
    txn = db[TRANSACTIONS].find_one({"transaction_id": target["id"]})
    if explicit_user_id and txn and explicit_user_id in (txn["lender_id"], txn["borrower_id"]):
        return explicit_user_id
    return None


@bp.put("/reports/<report_id>")
@admin_required
def update_report(report_id):
    db = get_db()
    report = db[REPORTS].find_one({"report_id": report_id})
    if not report:
        raise ApiError(f"Report '{report_id}' not found.", 404)
    data = v.get_json()
    status = v.choice(data, "status", REPORT_STATUSES)
    priority = v.choice(data, "priority", REPORT_PRIORITIES)
    note = v.string(data, "note", max_len=1000)
    resolution_in = v.obj(data, "resolution")
    if report["status"] in ("resolved", "dismissed") and (status or resolution_in):
        raise ApiError(f"This report is already {report['status']}.", 409)
    if status == "resolved" and not resolution_in:
        raise ApiError("Resolving a report requires a 'resolution' object with an 'action'.", 422,
                       details={"actions": RESOLUTION_ACTIONS})

    admin_id = g.user["user_id"]
    now = now_iso()
    updates = {"updated_at": now}
    log = {"at": now, "by": {"user_id": admin_id, "role": "admin"}, "action": "updated", "note": note, "changes": {}}
    if status and status != report["status"]:
        updates["status"] = status
        log["changes"]["status"] = {"from": report["status"], "to": status}
        if status == "under_review" and not report.get("assigned_to"):
            updates["assigned_to"] = admin_id
    if priority and priority != report["priority"]:
        updates["priority"] = priority
        log["changes"]["priority"] = {"from": report["priority"], "to": priority}
    if "assigned_to" in data:
        assignee = data["assigned_to"]
        if assignee and not db[USERS].find_one({"user_id": assignee, "role": "admin"}):
            raise ApiError("'assigned_to' must be an admin user_id.", 422)
        updates["assigned_to"] = assignee
        log["changes"]["assigned_to"] = {"from": report.get("assigned_to"), "to": assignee}

    if resolution_in:
        action = v.choice(resolution_in, "action", RESOLUTION_ACTIONS, required=True)
        effects = {"user": None, "item": None, "review": None, "trust": None}
        subject = _subject_user(db, report, resolution_in.get("user_id"))
        before = None
        if action in ("warning", "suspend_user", "ban_user"):
            if not subject:
                raise ApiError("Could not determine which user this action applies to. "
                               "For transaction reports pass resolution.user_id.", 422)
            subject_doc = db[USERS].find_one({"user_id": subject})
            if not subject_doc:
                raise ApiError("The reported user no longer exists.", 409)
            before = subject_doc.get("trust_score")
            if action == "warning":
                db[USERS].update_one({"user_id": subject}, {"$push": {"account.moderation.warnings": {
                    "at": now, "by": admin_id, "report_id": report_id, "reason": report["reason"]["subcategory"]}}})
            else:
                new_status = "suspended" if action == "suspend_user" else "banned"
                days = resolution_in.get("suspension_days", 14)
                db[USERS].update_one({"user_id": subject}, {"$set": {
                    "account.status": new_status,
                    "account.moderation.suspension": {
                        "status": new_status, "at": now, "by": admin_id, "report_id": report_id,
                        "until": iso(utcnow() + timedelta(days=days)) if new_status == "suspended" else None}}})
            effects["user"] = {"user_id": subject, "action": action}
        elif action == "remove_item":
            if report["target"]["type"] != "item":
                raise ApiError("'remove_item' only applies to item reports.", 422)
            db[ITEMS].update_one({"item_id": report["target"]["id"]}, {"$set": {
                "status": "removed", "availability": False, "availability_details.status": "unavailable",
                "moderation.status": "removed",
                "moderation.review": {"by": admin_id, "at": now, "decision": f"report:{report_id}"}}})
            effects["item"] = {"item_id": report["target"]["id"], "action": "removed"}
        elif action == "hide_review":
            if report["target"]["type"] != "review":
                raise ApiError("'hide_review' only applies to review reports.", 422)
            review = db[REVIEWS].find_one({"review_id": report["target"]["id"]})
            db[REVIEWS].update_one({"review_id": report["target"]["id"]}, {"$set": {
                "moderation.status": "hidden",
                "moderation.checks.manual": {"by": admin_id, "at": now, "decision": "hidden"}}})
            effects["review"] = {"review_id": report["target"]["id"], "action": "hidden"}
            if review:
                recalculate_trust(db, review["reviewed_user_id"], reason=f"review_hidden:{review['review_id']}")

        updates["status"] = "resolved"
        log["changes"]["status"] = {"from": report["status"], "to": "resolved"}
        updates["resolution"] = {"action": action, "notes": resolution_in.get("notes"), "by": admin_id, "at": now,
                                 "effects": effects}
        db[REPORTS].update_one({"report_id": report_id}, {"$set": updates})
        if subject and before is not None:
            profile = recalculate_trust(db, subject, reason=f"report_resolved:{report_id}")
            effects["trust"] = {"user_id": subject,
                                "penalty_applied": {"points": round(before - profile["score"], 1),
                                                    "before": before, "after": profile["score"]}}
            updates["resolution"]["effects"] = effects
        if report["target"]["type"] == "transaction":
            db[TRANSACTIONS].update_one({"transaction_id": report["target"]["id"]}, {"$set": {"dispute.open": False}})
        log["action"] = "resolved"
    elif updates.get("status") == "dismissed" and report["target"]["type"] == "transaction":
        db[TRANSACTIONS].update_one({"transaction_id": report["target"]["id"]}, {"$set": {"dispute.open": False}})

    db[REPORTS].update_one({"report_id": report_id}, {"$set": updates, "$push": {"activity_log": log}})
    return success(clean(db[REPORTS].find_one({"report_id": report_id})), message="Report updated.")


# ------------------------------------------------------------------ analytics
def _month_key(ts):
    return ts[:7] if ts else None


@bp.get("/analytics")
@admin_required
def analytics():
    db = get_db()
    now = utcnow()
    users = list(db[USERS].find({}, {"role": 1, "account.status": 1, "created_at": 1, "trust_score": 1,
                                     "trust_profile.tier": 1, "name": 1, "user_id": 1, "stats.lending.completed": 1}))
    items = list(db[ITEMS].find({}, {"item_id": 1, "name": 1, "category": 1, "status": 1, "availability": 1,
                                     "availability_details.status": 1, "stats.times_borrowed": 1, "deposit": 1}))
    requests_ = list(db[REQUESTS].find({}, {"status": 1, "created_at": 1}))
    txns = list(db[TRANSACTIONS].find({}, {"status": 1, "borrowed_at": 1, "returned_at": 1, "due_date": 1,
                                           "return_assessment.days_late": 1, "payment.deposit": 1,
                                           "item_snapshot.category": 1}))
    reviews = list(db[REVIEWS].find({}, {"rating": 1, "moderation.status": 1}))
    reports = list(db[REPORTS].find({}, {"status": 1, "priority": 1, "reason.category": 1}))

    thirty_days_ago = iso(now - timedelta(days=30))
    scores = [u["trust_score"] for u in users if u.get("trust_score") is not None]

    live_items = [i for i in items if i.get("status") != "removed"]
    by_category = {}
    for cat in CATEGORIES:
        cat_items = [i for i in live_items if i["category"] == cat]
        by_category[cat] = {"total": len(cat_items), "available": sum(1 for i in cat_items if i["availability"]),
                            "times_borrowed": sum(i.get("stats", {}).get("times_borrowed", 0) for i in cat_items)}

    req_status = Counter(r["status"] for r in requests_)
    decided = req_status["accepted"] + req_status["rejected"]
    active = [t for t in txns if t["status"] == "active"]
    completed = [t for t in txns if t["status"] == "completed"]
    overdue = [t for t in active if now > due_deadline(t["due_date"])]
    on_time = sum(1 for t in completed if ((t.get("return_assessment") or {}).get("days_late") or 0) == 0)
    durations = [(parse_dt(t["returned_at"]) - parse_dt(t["borrowed_at"])).total_seconds() / 86400
                 for t in completed if t.get("returned_at")]
    deposits = defaultdict(float)
    for t in txns:
        dep = t.get("payment", {}).get("deposit", {})
        if dep.get("status") == "held":
            deposits["currently_held"] += dep.get("amount", 0)
        deposits["refunded"] += dep.get("refunded_amount") or 0
        deposits["deducted"] += dep.get("deductions", {}).get("total", 0)

    # last 12 months of borrowing activity
    months = []
    cursor = now.replace(day=1)
    for _ in range(12):
        months.append(cursor.strftime("%Y-%m"))
        cursor = (cursor - timedelta(days=1)).replace(day=1)
    months.reverse()
    req_by_month = Counter(_month_key(r["created_at"]) for r in requests_)
    start_by_month = Counter(_month_key(t["borrowed_at"]) for t in txns)
    done_by_month = Counter(_month_key(t.get("returned_at")) for t in completed)
    cat_by_month = defaultdict(Counter)
    for t in txns:
        cat_by_month[_month_key(t["borrowed_at"])][t.get("item_snapshot", {}).get("category")] += 1
    monthly = [{"month": m, "requests": req_by_month.get(m, 0), "transactions_started": start_by_month.get(m, 0),
                "transactions_completed": done_by_month.get(m, 0),
                "top_category": (cat_by_month[m].most_common(1)[0][0] if cat_by_month[m] else None)}
               for m in months]

    published = [r for r in reviews if r.get("moderation", {}).get("status") == "published"]
    top_items = sorted(live_items, key=lambda i: -i.get("stats", {}).get("times_borrowed", 0))[:5]
    top_lenders = sorted(users, key=lambda u: -(u.get("stats", {}).get("lending", {}).get("completed") or 0))[:5]

    data = {
        "generated_at": iso(now),
        "users": {
            "total": len(users),
            "by_role": dict(Counter(u["role"] for u in users)),
            "by_status": dict(Counter(u.get("account", {}).get("status", "active") for u in users)),
            "new_last_30_days": sum(1 for u in users if u["created_at"] >= thirty_days_ago),
            "trust": {"average": round(sum(scores) / len(scores), 1) if scores else None,
                      "min": min(scores) if scores else None, "max": max(scores) if scores else None,
                      "tiers": dict(Counter(u.get("trust_profile", {}).get("tier") for u in users))},
        },
        "items": {
            "total_listed": len(live_items),
            "available": sum(1 for i in live_items if i["availability"]),
            "on_loan": sum(1 for i in live_items if i.get("availability_details", {}).get("status") == "on_loan"),
            "paused": sum(1 for i in live_items if i.get("status") == "paused"),
            "removed": len(items) - len(live_items),
            "by_category": by_category,
        },
        "borrow_requests": {
            "total": len(requests_),
            "by_status": {s: req_status.get(s, 0) for s in ("pending", "accepted", "rejected", "cancelled")},
            "acceptance_rate": round(req_status["accepted"] / decided, 3) if decided else None,
        },
        "transactions": {
            "total": len(txns),
            "active": len(active),
            "completed": len(completed),
            "overdue": len(overdue),
            "on_time_return_rate": round(on_time / len(completed), 3) if completed else None,
            "average_loan_days": round(sum(durations) / len(durations), 1) if durations else None,
            "deposits_gbp": {k: round(v_, 2) for k, v_ in deposits.items()},
        },
        "reviews": {
            "total": len(reviews),
            "published": len(published),
            "average_rating": round(sum(r["rating"] for r in published) / len(published), 2) if published else None,
            "distribution": {str(i): sum(1 for r in published if r["rating"] == i) for i in range(1, 6)},
            "flagged_or_hidden": len(reviews) - len(published),
        },
        "reports": {
            "total": len(reports),
            "by_status": dict(Counter(r["status"] for r in reports)),
            "by_priority": dict(Counter(r["priority"] for r in reports)),
            "by_category": dict(Counter(r["reason"]["category"] for r in reports)),
        },
        "borrowing_activity": {"monthly": monthly},
        "leaderboards": {
            "most_borrowed_items": [{"item_id": i["item_id"], "name": i["name"], "category": i["category"],
                                     "times_borrowed": i.get("stats", {}).get("times_borrowed", 0)} for i in top_items],
            "top_lenders": [{"user_id": u["user_id"], "name": u["name"], "trust_score": u.get("trust_score"),
                             "completed_loans": u.get("stats", {}).get("lending", {}).get("completed", 0)}
                            for u in top_lenders],
        },
    }
    return success(data)
