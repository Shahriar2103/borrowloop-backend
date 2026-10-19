"""Transactions: record collection, list active/history, record return."""
from datetime import timedelta

from flask import Blueprint, g, request

from ..constants import CONDITIONS, DAMAGE_SEVERITIES
from ..database import ITEMS, REQUESTS, TRANSACTIONS, USERS, get_db
from ..models import build_transaction
from ..services.lending_service import assess_return, due_deadline
from ..services.stats_service import refresh_item_stats, refresh_user_stats
from ..services.trust_service import recalculate_trust
from ..utils import validation as v
from ..utils.decorators import auth_required, is_admin
from ..utils.helpers import clean, iso, next_id, paginate, parse_dt, parse_sort, utcnow
from ..utils.responses import ApiError, success

bp = Blueprint("transactions", __name__, url_prefix="/api/transactions")

SORTABLE = {"borrowed_at": "borrowed_at", "returned_at": "returned_at", "due_date": "due_date",
            "created_at": "created_at"}


def with_overdue(doc):
    out = clean(doc)
    if doc["status"] == "active":
        overdue = (utcnow() - due_deadline(doc["due_date"])).total_seconds()
        out["is_overdue"] = overdue > 0
        out["days_overdue"] = max(0, int(-(-overdue // 86400))) if overdue > 0 else 0
    else:
        out["is_overdue"] = False
        out["days_overdue"] = 0
    return out


def _role_query(uid):
    role = request.args.get("role", "all")
    if role == "borrower":
        return {"borrower_id": uid}
    if role == "lender":
        return {"lender_id": uid}
    if role == "all":
        return {"$or": [{"borrower_id": uid}, {"lender_id": uid}]}
    raise ApiError("'role' must be borrower, lender or all.", 422)


def get_txn_or_404(transaction_id):
    txn = get_db()[TRANSACTIONS].find_one({"transaction_id": transaction_id})
    if not txn:
        raise ApiError(f"Transaction '{transaction_id}' not found.", 404)
    return txn


@bp.post("")
@auth_required
def create_transaction():
    db = get_db()
    data = v.get_json()
    v.require_fields(data, "request_id")
    req = db[REQUESTS].find_one({"request_id": data["request_id"]})
    if not req:
        raise ApiError("Borrow request not found.", 404)
    uid = g.user["user_id"]
    if uid not in (req["owner_id"], req["borrower_id"]) and not is_admin(g.user):
        raise ApiError("Only the lender or borrower can record a collection.", 403)
    if req["status"] != "accepted":
        raise ApiError(f"Only accepted requests can start a transaction (current: {req['status']}).", 409)
    if req.get("transaction_id") or db[TRANSACTIONS].find_one({"request_id": req["request_id"]}):
        raise ApiError("A transaction already exists for this request.", 409)

    now = utcnow()
    start = parse_dt(req["start_date"])
    if now < start - timedelta(days=1):
        raise ApiError("The item can be collected from one day before the start date.", 409,
                       details={"start_date": req["start_date"]})
    if now > due_deadline(req["return_date"]):
        raise ApiError("The borrowing period for this request has already ended.", 409)
    item = db[ITEMS].find_one({"item_id": req["item_id"]})
    if not item or item.get("status") == "removed":
        raise ApiError("The item is no longer listed.", 409)
    if db[TRANSACTIONS].find_one({"item_id": item["item_id"], "status": "active"}):
        raise ApiError("This item is still on loan from a previous transaction.", 409)

    grade = v.choice(data, "condition", CONDITIONS, default=item["condition"])
    lender = db[USERS].find_one({"user_id": req["owner_id"]})
    borrower = db[USERS].find_one({"user_id": req["borrower_id"]})
    now_s = iso(now)
    txn = build_transaction(transaction_id=next_id(db, "transaction"), request=req, item=item, lender=lender,
                            borrower=borrower, borrowed_at=now_s, created_at=now_s, pickup_grade=grade,
                            pickup_notes=v.string(data, "notes", max_len=1000))
    txn["reminders"][0]["scheduled_for"] = iso(parse_dt(req["return_date"]) - timedelta(days=1))
    db[TRANSACTIONS].insert_one(txn)
    db[REQUESTS].update_one({"request_id": req["request_id"]}, {
        "$set": {"transaction_id": txn["transaction_id"], "updated_at": now_s},
        "$push": {"status_history": {"status": "accepted", "at": now_s,
                                     "by": {"user_id": uid, "role": "lender" if uid == req["owner_id"] else "borrower"},
                                     "note": f"Item collected - transaction {txn['transaction_id']}"}}})
    db[ITEMS].update_one({"item_id": item["item_id"]}, {
        "$set": {"availability": False, "availability_details.status": "on_loan",
                 "availability_details.current_transaction_id": txn["transaction_id"],
                 "availability_details.next_available_from": req["return_date"], "updated_at": now_s},
        "$pull": {"availability_details.calendar.booked": {"request_id": req["request_id"]}}})
    db[ITEMS].update_one({"item_id": item["item_id"]}, {"$push": {"availability_details.calendar.booked": {
        "request_id": req["request_id"], "from": req["start_date"], "to": req["return_date"], "status": "on_loan"}}})
    for user_id in (req["owner_id"], req["borrower_id"]):
        refresh_user_stats(db, user_id)
    refresh_item_stats(db, item["item_id"])
    return success(with_overdue(db[TRANSACTIONS].find_one({"transaction_id": txn["transaction_id"]})), 201,
                   message="Collection recorded. Transaction is active.")


@bp.get("")
@auth_required
def active_transactions():
    query = _role_query(g.user["user_id"])
    query["status"] = "active"
    sort = parse_sort(SORTABLE, [("due_date", 1)])
    items, meta = paginate(get_db()[TRANSACTIONS], query, sort=sort, serializer=with_overdue)
    return success(items, meta=meta)


@bp.get("/history")
@auth_required
def transaction_history():
    query = _role_query(g.user["user_id"])
    query["status"] = "completed"
    sort = parse_sort(SORTABLE, [("returned_at", -1)])
    items, meta = paginate(get_db()[TRANSACTIONS], query, sort=sort, serializer=with_overdue)
    return success(items, meta=meta)


@bp.get("/<transaction_id>")
@auth_required
def get_transaction(transaction_id):
    txn = get_txn_or_404(transaction_id)
    if g.user["user_id"] not in (txn["lender_id"], txn["borrower_id"]) and not is_admin(g.user):
        raise ApiError("You are not part of this transaction.", 403)
    return success(with_overdue(txn))


@bp.put("/<transaction_id>")
@auth_required
def record_return(transaction_id):
    db = get_db()
    txn = get_txn_or_404(transaction_id)
    uid = g.user["user_id"]
    if uid != txn["lender_id"] and not is_admin(g.user):
        raise ApiError("Only the lender confirms a return (they inspect the item).", 403)
    if txn["status"] != "active":
        raise ApiError("This transaction is already completed.", 409)
    data = v.get_json()
    return_condition = v.choice(data, "return_condition", CONDITIONS, required=True)
    severity = v.choice(data, "damage_severity", DAMAGE_SEVERITIES)
    notes = v.string(data, "notes", max_len=1000)
    now = utcnow()
    returned_at = now
    if data.get("returned_at"):
        returned_at = parse_dt(data["returned_at"], "returned_at")
        if returned_at > now or returned_at < parse_dt(txn["borrowed_at"]):
            raise ApiError("'returned_at' must be between the collection time and now.", 422)

    item = db[ITEMS].find_one({"item_id": txn["item_id"]})
    updated, item_set, inspection = assess_return(txn, item, returned_at, return_condition,
                                                  damage_severity=severity, notes=notes, actor_id=uid, now=now)
    db[TRANSACTIONS].replace_one({"transaction_id": transaction_id}, updated)
    db[ITEMS].update_one({"item_id": item["item_id"]}, {
        "$set": item_set,
        "$push": {"condition_report.inspections": inspection},
        "$pull": {"availability_details.calendar.booked": {"request_id": txn["request_id"]}}})
    refresh_item_stats(db, item["item_id"])
    for user_id in (txn["lender_id"], txn["borrower_id"]):
        refresh_user_stats(db, user_id)
        recalculate_trust(db, user_id, reason=f"transaction_completed:{transaction_id}")
    return success(with_overdue(db[TRANSACTIONS].find_one({"transaction_id": transaction_id})),
                   message="Return recorded. Transaction completed.")
