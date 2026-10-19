"""Reviews left after a completed transaction."""
from flask import Blueprint, g, request

from ..database import REVIEWS, TRANSACTIONS, USERS, get_db
from ..models import ASPECTS, build_review
from ..services.stats_service import refresh_item_stats, refresh_user_stats
from ..services.trust_service import recalculate_trust
from ..utils import validation as v
from ..utils.decorators import auth_required, is_admin
from ..utils.helpers import clean, next_id, now_iso, paginate
from ..utils.responses import ApiError, success

bp = Blueprint("reviews", __name__, url_prefix="/api/reviews")

FLAG_WORDS = ("idiot", "stupid", "scam", "hate", "useless")


def _toxicity(text):
    if not text:
        return 0.0
    hits = sum(text.lower().count(w) for w in FLAG_WORDS)
    return round(min(0.95, 0.02 + 0.35 * hits), 2)


@bp.post("")
@auth_required
def create_review():
    db = get_db()
    data = v.get_json()
    v.require_fields(data, "transaction_id", "rating")
    rating = v.number(data, "rating", required=True, minimum=1, maximum=5, integer=True)
    comment = v.string(data, "comment", max_len=1500, default="")
    txn = db[TRANSACTIONS].find_one({"transaction_id": data["transaction_id"]})
    if not txn:
        raise ApiError("Transaction not found.", 404)
    uid = g.user["user_id"]
    if uid == txn["borrower_id"]:
        direction, reviewed_id = "borrower_to_lender", txn["lender_id"]
    elif uid == txn["lender_id"]:
        direction, reviewed_id = "lender_to_borrower", txn["borrower_id"]
    else:
        raise ApiError("Only the borrower or lender of this transaction can review it.", 403)
    if txn["status"] != "completed":
        raise ApiError("You can only review a completed transaction.", 409)
    if db[REVIEWS].find_one({"transaction_id": txn["transaction_id"], "reviewer_id": uid}):
        raise ApiError("You have already reviewed this transaction.", 409)

    aspects_in = v.obj(data, "aspects") or {}
    aspects = {}
    for name in ASPECTS[direction]:
        if name in aspects_in:
            aspects[name] = v.number(aspects_in, name, minimum=1, maximum=5, integer=True)
    unknown = [a for a in aspects_in if a not in ASPECTS[direction]]
    if unknown:
        raise ApiError("Unknown rating aspects.", 422, details={"allowed": ASPECTS[direction]})

    reviewed = db[USERS].find_one({"user_id": reviewed_id})
    toxicity = _toxicity(comment)
    review = build_review(review_id=next_id(db, "review"), reviewer=g.user, reviewed_user=reviewed or {"user_id": reviewed_id},
                          transaction=txn, rating=rating, comment=comment, created_at=now_iso(),
                          direction=direction, aspects=aspects, toxicity_score=toxicity)
    if toxicity >= 0.7:
        review["moderation"]["status"] = "flagged"
        review["moderation"]["flags"].append({"by": "system", "reason": "possible_abusive_language", "at": review["created_at"]})
    db[REVIEWS].insert_one(review)
    refresh_user_stats(db, reviewed_id)
    refresh_user_stats(db, uid)
    refresh_item_stats(db, txn["item_id"])
    recalculate_trust(db, reviewed_id, reason=f"review_received:{review['review_id']}")
    msg = "Review submitted." if review["moderation"]["status"] == "published" else \
        "Review submitted and held for moderation."
    return success(clean(review), 201, message=msg)


@bp.get("/<user_id>")
@auth_required
def reviews_for_user(user_id):
    db = get_db()
    user = db[USERS].find_one({"user_id": user_id})
    if not user:
        raise ApiError(f"User '{user_id}' not found.", 404)
    query = {"reviewed_user_id": user_id}
    if not is_admin(g.user):
        query["moderation.status"] = "published"
    direction = request.args.get("as")
    if direction == "lender":
        query["direction"] = "borrower_to_lender"
    elif direction == "borrower":
        query["direction"] = "lender_to_borrower"
    items, meta = paginate(db[REVIEWS], query, sort=[("created_at", -1)])
    meta["summary"] = user.get("stats", {}).get("reviews", {}).get("received")
    meta["trust"] = {"score": user.get("trust_score"), "tier": user.get("trust_profile", {}).get("tier")}
    return success(items, meta=meta)


@bp.post("/<review_id>/response")
@auth_required
def respond(review_id):
    db = get_db()
    review = db[REVIEWS].find_one({"review_id": review_id})
    if not review:
        raise ApiError("Review not found.", 404)
    if review["reviewed_user_id"] != g.user["user_id"]:
        raise ApiError("Only the reviewed member can respond.", 403)
    if review.get("response"):
        raise ApiError("You have already responded to this review.", 409)
    data = v.get_json()
    comment = v.string(data, "comment", required=True, max_len=1000)
    db[REVIEWS].update_one({"review_id": review_id}, {"$set": {"response": {"comment": comment, "at": now_iso()}}})
    return success(clean(db[REVIEWS].find_one({"review_id": review_id})), message="Response added.")


@bp.post("/<review_id>/helpful")
@auth_required
def mark_helpful(review_id):
    db = get_db()
    review = db[REVIEWS].find_one({"review_id": review_id})
    if not review:
        raise ApiError("Review not found.", 404)
    uid = g.user["user_id"]
    if uid in review["engagement"]["helpful"]["voters"]:
        raise ApiError("You already marked this review as helpful.", 409)
    db[REVIEWS].update_one({"review_id": review_id}, {"$inc": {"engagement.helpful.count": 1},
                                                      "$push": {"engagement.helpful.voters": uid}})
    return success(clean(db[REVIEWS].find_one({"review_id": review_id})))
