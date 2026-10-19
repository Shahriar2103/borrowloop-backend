"""Members report users, items, transactions or reviews to administrators."""
from flask import Blueprint, g

from ..constants import REPORT_CATEGORIES, REPORT_TARGET_TYPES
from ..database import ITEMS, REPORTS, REVIEWS, TRANSACTIONS, USERS, get_db
from ..models import build_report
from ..utils import validation as v
from ..utils.decorators import auth_required
from ..utils.helpers import clean, next_id, now_iso, paginate
from ..utils.responses import ApiError, success

bp = Blueprint("reports", __name__, url_prefix="/api/reports")


def target_snapshot(db, target_type, target_id):
    """Find the reported record and store a small snapshot of it (or raise 404)."""
    if target_type == "user":
        doc = db[USERS].find_one({"user_id": target_id})
        snap = doc and {"name": doc["name"], "role": doc["role"], "trust_score": doc.get("trust_score")}
    elif target_type == "item":
        doc = db[ITEMS].find_one({"item_id": target_id})
        snap = doc and {"name": doc["name"], "category": doc["category"], "owner_id": doc["owner_id"]}
    elif target_type == "transaction":
        doc = db[TRANSACTIONS].find_one({"transaction_id": target_id})
        snap = doc and {"item": doc["item_snapshot"]["name"], "lender_id": doc["lender_id"],
                        "borrower_id": doc["borrower_id"], "status": doc["status"]}
    else:
        doc = db[REVIEWS].find_one({"review_id": target_id})
        snap = doc and {"reviewer_id": doc["reviewer_id"], "reviewed_user_id": doc["reviewed_user_id"],
                        "rating": doc["rating"], "comment": doc["comment"]}
    if not doc:
        raise ApiError(f"{target_type.capitalize()} '{target_id}' not found.", 404)
    return doc, snap


@bp.post("")
@auth_required
def create_report():
    db = get_db()
    data = v.get_json()
    target_type = v.choice(data, "target_type", REPORT_TARGET_TYPES, required=True)
    target_id = v.string(data, "target_id", required=True, max_len=40)
    category = v.choice(data, "category", tuple(REPORT_CATEGORIES), required=True)
    subcategory = v.choice(data, "subcategory", tuple(REPORT_CATEGORIES[category]),
                           default=REPORT_CATEGORIES[category][0])
    description = v.string(data, "description", required=True, min_len=10, max_len=2000)
    if target_type == "user" and target_id == g.user["user_id"]:
        raise ApiError("You cannot report yourself.", 422)
    doc, snapshot = target_snapshot(db, target_type, target_id)
    if db[REPORTS].find_one({"reporter_id": g.user["user_id"], "target.id": target_id,
                             "status": {"$in": ["open", "under_review"]}}):
        raise ApiError("You already have an open report about this.", 409)
    priority = "high" if category in ("safety", "fraud") else "medium"
    related = {}
    if target_type == "transaction":
        related = {"transaction_id": target_id, "request_id": doc["request_id"]}
    report = build_report(report_id=next_id(db, "report"), reporter=g.user, target_type=target_type,
                          target_id=target_id, target_snapshot=snapshot, category=category,
                          subcategory=subcategory, description=description, created_at=now_iso(),
                          attachments=v.string_list(data, "attachments", max_items=5, max_len=500),
                          related=related, priority=priority)
    db[REPORTS].insert_one(report)
    if target_type == "item":
        db[ITEMS].update_one({"item_id": target_id}, {"$push": {"moderation.flags": {
            "report_id": report["report_id"], "reason": subcategory, "at": report["created_at"]}}})
    if target_type == "transaction":
        db[TRANSACTIONS].update_one({"transaction_id": target_id},
                                    {"$set": {"dispute": {"open": True, "report_id": report["report_id"]}}})
    return success(clean(report), 201, message="Report submitted. Our team will review it.")


@bp.get("/mine")
@auth_required
def my_reports():
    items, meta = paginate(get_db()[REPORTS], {"reporter_id": g.user["user_id"]}, sort=[("created_at", -1)])
    return success(items, meta=meta)
