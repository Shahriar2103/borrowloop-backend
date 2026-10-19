"""Borrow requests: submit, list, accept / reject / modify, cancel."""
from flask import Blueprint, g, request

from ..constants import PICKUP_METHODS, REQUEST_STATUSES
from ..database import ITEMS, REQUESTS, USERS, get_db
from ..models import build_borrow_request, money
from ..services.lending_service import find_overlaps, validate_request_dates
from ..services.stats_service import refresh_user_stats
from ..services.trust_service import recalculate_trust
from ..utils import validation as v
from ..utils.decorators import auth_required, is_admin
from ..utils.helpers import clean, next_id, now_iso, paginate, parse_sort, utcnow
from ..utils.responses import ApiError, success

bp = Blueprint("borrow_requests", __name__, url_prefix="/api/borrow-requests")

SORTABLE = {"created_at": "created_at", "start_date": "start_date", "status": "status"}


def get_request_or_404(request_id):
    req = get_db()[REQUESTS].find_one({"request_id": request_id})
    if not req:
        raise ApiError(f"Borrow request '{request_id}' not found.", 404)
    return req


def _party_role(req, user):
    if user["user_id"] == req["borrower_id"]:
        return "borrower"
    if user["user_id"] == req["owner_id"]:
        return "lender"
    if is_admin(user):
        return "admin"
    return None


def _history(status, user_id, role, note):
    return {"status": status, "at": now_iso(), "by": {"user_id": user_id, "role": role}, "note": note}


def _calendar_add(db, req):
    db[ITEMS].update_one({"item_id": req["item_id"]}, {"$push": {"availability_details.calendar.booked": {
        "request_id": req["request_id"], "from": req["start_date"], "to": req["return_date"], "status": "accepted"}}})


def _calendar_remove(db, req):
    db[ITEMS].update_one({"item_id": req["item_id"]},
                         {"$pull": {"availability_details.calendar.booked": {"request_id": req["request_id"]}}})


@bp.post("")
@auth_required
def create_request():
    db = get_db()
    data = v.get_json()
    v.require_fields(data, "item_id", "start_date", "return_date")
    item = db[ITEMS].find_one({"item_id": data["item_id"]})
    if not item or item.get("status") != "active":
        raise ApiError("Item not found or not currently listed.", 404)
    borrower = g.user
    if item["owner_id"] == borrower["user_id"]:
        raise ApiError("You cannot borrow your own item.", 422)

    start, end, duration = validate_request_dates(data["start_date"], data["return_date"], item, utcnow())
    rules = item.get("lending_rules", {})
    trust = borrower.get("trust_score") or 0
    if trust < (rules.get("min_trust_score") or 0):
        raise ApiError("Your Trust Score is below the minimum the owner requires for this item.", 403,
                       "trust_too_low", details={"your_score": trust, "required": rules["min_trust_score"]})
    if rules.get("requires_id_verification") and borrower["verification"]["identity"]["status"] != "verified":
        raise ApiError("This item requires a verified identity.", 403, "verification_required")
    if find_overlaps(db, item["item_id"], start, end):
        raise ApiError("The item is already booked for some of those dates.", 409, "dates_unavailable",
                       details={"booked": [{"from": b["from"], "to": b["to"]} for b in
                                           item["availability_details"]["calendar"]["booked"]]})
    if db[REQUESTS].find_one({"item_id": item["item_id"], "borrower_id": borrower["user_id"], "status": "pending",
                              "start_date": {"$lte": end}, "return_date": {"$gte": start}}):
        raise ApiError("You already have a pending request for this item on overlapping dates.", 409)

    pickup_method = v.choice(data, "pickup_method", PICKUP_METHODS, default=item["pickup"]["methods"][0])
    if pickup_method not in item["pickup"]["methods"]:
        raise ApiError("The owner does not offer that pickup method.", 422, details={"allowed": item["pickup"]["methods"]})

    owner = db[USERS].find_one({"user_id": item["owner_id"]})
    now = now_iso()
    req = build_borrow_request(
        request_id=next_id(db, "request"), item=item, borrower=borrower, owner=owner,
        start_date=start, return_date=end, created_at=now, duration_days=duration,
        message=v.string(data, "message", max_len=1000), pickup_method=pickup_method,
    )

    # owner preference: automatically decline low-trust borrowers
    threshold = owner.get("preferences", {}).get("lending", {}).get("auto_decline_below_trust")
    if threshold and trust < threshold:
        req["status"] = "rejected"
        req["decision"] = {"by": "system", "at": now, "reason": "Below owner's trust threshold",
                           "auto": {"triggered": True, "rule": "auto_decline_below_trust", "threshold": threshold}}
        req["status_history"].append(_history("rejected", "system", "system", "Automatically declined"))

    db[REQUESTS].insert_one(req)
    refresh_user_stats(db, borrower["user_id"])
    refresh_user_stats(db, item["owner_id"])
    msg = "Borrow request sent." if req["status"] == "pending" else "Request was automatically declined."
    return success(clean(db[REQUESTS].find_one({"request_id": req["request_id"]})), 201, message=msg)


@bp.get("")
@auth_required
def list_requests():
    uid = g.user["user_id"]
    role = request.args.get("role", "all")
    if role == "borrower":
        query = {"borrower_id": uid}
    elif role == "lender":
        query = {"owner_id": uid}
    elif role == "all":
        query = {"$or": [{"borrower_id": uid}, {"owner_id": uid}]}
    else:
        raise ApiError("'role' must be borrower, lender or all.", 422)
    if request.args.get("status"):
        statuses = request.args["status"].split(",")
        bad = [s for s in statuses if s not in REQUEST_STATUSES]
        if bad:
            raise ApiError("Unknown status.", 422, details={"allowed": REQUEST_STATUSES})
        query["status"] = {"$in": statuses}
    if request.args.get("item_id"):
        query["item_id"] = request.args["item_id"]
    sort = parse_sort(SORTABLE, [("created_at", -1)])
    items, meta = paginate(get_db()[REQUESTS], query, sort=sort)
    return success(items, meta=meta)


@bp.get("/<request_id>")
@auth_required
def get_request(request_id):
    req = get_request_or_404(request_id)
    if not _party_role(req, g.user):
        raise ApiError("You are not part of this request.", 403)
    return success(clean(req))


@bp.put("/<request_id>")
@auth_required
def update_request(request_id):
    db = get_db()
    req = get_request_or_404(request_id)
    role = _party_role(req, g.user)
    if not role:
        raise ApiError("You are not part of this request.", 403)
    data = v.get_json()
    new_status = v.choice(data, "status", REQUEST_STATUSES)
    reason = v.string(data, "reason", max_len=500)
    uid = g.user["user_id"]
    now = now_iso()
    item = db[ITEMS].find_one({"item_id": req["item_id"]})

    # ----- lender decisions
    if new_status in ("accepted", "rejected"):
        if role not in ("lender", "admin"):
            raise ApiError("Only the item owner can accept or reject a request.", 403)
        if req["status"] != "pending":
            raise ApiError(f"Only pending requests can be {new_status} (current: {req['status']}).", 409)
        updates = {"status": new_status, "updated_at": now,
                   "decision": {"by": uid, "at": now, "reason": reason, "auto": {"triggered": False, "rule": None}}}
        auto_rejected = []
        if new_status == "accepted":
            if not item or item.get("status") != "active":
                raise ApiError("This item is no longer listed.", 409)
            if find_overlaps(db, req["item_id"], req["start_date"], req["return_date"], exclude_request_id=request_id):
                raise ApiError("Another accepted booking already covers these dates.", 409, "dates_unavailable")
        db[REQUESTS].update_one({"request_id": request_id}, {
            "$set": updates, "$push": {"status_history": _history(new_status, uid, role, reason or f"Request {new_status}")}})
        if new_status == "accepted":
            _calendar_add(db, req)
            # decline other pending requests that clash with the accepted dates
            for other in find_overlaps(db, req["item_id"], req["start_date"], req["return_date"],
                                       statuses=("pending",), exclude_request_id=request_id):
                db[REQUESTS].update_one({"request_id": other["request_id"]}, {
                    "$set": {"status": "rejected", "updated_at": now,
                             "decision": {"by": "system", "at": now, "reason": "Dates taken by another booking",
                                          "auto": {"triggered": True, "rule": "overlap_with_accepted",
                                                   "conflicting_request_id": request_id}}},
                    "$push": {"status_history": _history("rejected", "system", "system", "Overlaps an accepted booking")}})
                auto_rejected.append(other["request_id"])
        refresh_user_stats(db, req["owner_id"])
        out = clean(db[REQUESTS].find_one({"request_id": request_id}))
        if auto_rejected:
            out["auto_rejected_requests"] = auto_rejected
        return success(out, message=f"Request {new_status}.")

    # ----- cancellation (borrower or lender)
    if new_status == "cancelled":
        return _cancel(db, req, role, reason)

    # ----- borrower modifies a pending request (counter-proposal)
    if new_status not in (None, "pending"):
        raise ApiError("Unsupported status change.", 422)
    if role != "borrower":
        raise ApiError("Only the borrower can change the requested dates or message.", 403)
    if req["status"] != "pending":
        raise ApiError("Only pending requests can be modified.", 409)
    start, end, duration = validate_request_dates(data.get("start_date", req["start_date"]),
                                                  data.get("return_date", req["return_date"]), item, utcnow())
    if find_overlaps(db, req["item_id"], start, end, exclude_request_id=request_id):
        raise ApiError("The item is already booked for some of those dates.", 409, "dates_unavailable")
    message = v.string(data, "message", max_len=1000, default=req.get("message"))
    rounds = req["negotiation"]["rounds"] + 1
    entry = {
        "message_id": f"{request_id}-M{rounds}", "sender_id": uid, "sent_at": now, "body": message,
        "proposal": {"start_date": start, "return_date": end,
                     "terms": {"deposit": money(item["deposit"]),
                               "pickup": {"method": req["logistics"]["pickup"]["method"],
                                          "window": req["logistics"]["pickup"]["scheduled"]["window"]}}},
    }
    db[REQUESTS].update_one({"request_id": request_id}, {
        "$set": {"start_date": start, "return_date": end, "duration_days": duration, "message": message,
                 "updated_at": now, "negotiation.rounds": rounds,
                 "logistics.pickup.scheduled.date": start, "logistics.return.scheduled.date": end},
        "$push": {"negotiation.thread": entry,
                  "status_history": _history("pending", uid, "borrower", "Borrower updated the request")}})
    return success(clean(db[REQUESTS].find_one({"request_id": request_id})), message="Request updated.")


def _cancel(db, req, role, reason):
    if req["status"] not in ("pending", "accepted"):
        raise ApiError(f"A {req['status']} request cannot be cancelled.", 409)
    if req.get("transaction_id"):
        raise ApiError("The item has already been collected; complete the transaction instead.", 409)
    uid = g.user["user_id"]
    now = now_iso()
    after_acceptance = req["status"] == "accepted"
    db[REQUESTS].update_one({"request_id": req["request_id"]}, {
        "$set": {"status": "cancelled", "updated_at": now,
                 "cancellation": {"by": uid, "role": role, "at": now, "reason": reason,
                                  "after_acceptance": after_acceptance}},
        "$push": {"status_history": _history("cancelled", uid, role, reason or "Request cancelled")}})
    if after_acceptance:
        _calendar_remove(db, req)
        # a late cancellation affects the cancelling party's Trust Score
        if role in ("borrower", "lender"):
            affected = req["borrower_id"] if role == "borrower" else req["owner_id"]
            recalculate_trust(db, affected, reason="late_cancellation")
    refresh_user_stats(db, req["borrower_id"])
    refresh_user_stats(db, req["owner_id"])
    return success(clean(db[REQUESTS].find_one({"request_id": req["request_id"]})), message="Request cancelled.")


@bp.delete("/<request_id>")
@auth_required
def cancel_request(request_id):
    db = get_db()
    req = get_request_or_404(request_id)
    role = _party_role(req, g.user)
    if role not in ("borrower", "admin"):
        raise ApiError("Only the borrower can cancel this request (owners can reject it instead).", 403)
    reason = None
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        reason = v.string(body, "reason", max_len=500)
    return _cancel(db, req, role, reason)
