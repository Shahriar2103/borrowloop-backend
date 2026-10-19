"""User profiles and Trust Score."""
from flask import Blueprint, g

from ..constants import ACCOUNT_STATUSES, CATEGORIES, ROLES
from ..database import ITEMS, USERS, get_db
from ..models.common import build_location, resolve_zone
from ..services.trust_service import WEIGHTS, recalculate_trust
from ..utils import validation as v
from ..utils.decorators import auth_required, is_admin
from ..utils.helpers import clean, clean_user, flatten_for_set, now_iso, paginate
from ..utils.responses import ApiError, success
from ..utils.security import hash_password, verify_password

bp = Blueprint("users", __name__, url_prefix="/api/users")

PREFERENCE_SECTIONS = ("notifications", "privacy", "lending")


def get_user_or_404(user_id):
    user = get_db()[USERS].find_one({"user_id": user_id})
    if not user:
        raise ApiError(f"User '{user_id}' not found.", 404)
    return user


@bp.get("/<user_id>")
@auth_required
def get_user(user_id):
    user = get_user_or_404(user_id)
    private = g.user["user_id"] == user_id or is_admin(g.user)
    return success(clean_user(user, private=private))


@bp.put("/<user_id>")
@auth_required
def update_user(user_id):
    user = get_user_or_404(user_id)
    admin = is_admin(g.user)
    if g.user["user_id"] != user_id and not admin:
        raise ApiError("You can only update your own profile.", 403)

    data = v.get_json()
    updates = {}
    if "name" in data:
        updates["name"] = v.string(data, "name", required=True, min_len=2, max_len=80)
        updates["profile.display_name"] = updates["name"].split(" ")[0]
    if "bio" in data:
        updates["profile.bio"] = v.string(data, "bio", max_len=500, default="")
    if "phone" in data:
        updates["profile.contact.phone.number"] = v.string(data, "phone", max_len=20)
        updates["profile.contact.phone.verified"] = False
        updates["verification.phone"] = {"verified": False, "verified_at": None}
    if "interests" in data:
        interests = v.string_list(data, "interests") or []
        bad = [i for i in interests if i not in CATEGORIES]
        if bad:
            raise ApiError("Unknown interest categories.", 422, details={"unknown": bad})
        updates["profile.interests"] = interests
    if "neighbourhood" in data or "address_line1" in data:
        current = user.get("profile", {}).get("location", {})
        zone = resolve_zone(data.get("neighbourhood") or current.get("community", {}).get("zone", {}).get("code"))
        updates["profile.location"] = build_location(zone, data.get("address_line1", current.get("address", {}).get("line1")))
    if "preferences" in data:
        prefs = v.obj(data, "preferences") or {}
        bad = [k for k in prefs if k not in PREFERENCE_SECTIONS]
        if bad:
            raise ApiError("Unknown preference sections.", 422, details={"unknown": bad, "allowed": PREFERENCE_SECTIONS})
        updates.update(flatten_for_set(prefs, "preferences."))
    if "new_password" in data:
        if not admin or g.user["user_id"] == user_id:
            if not verify_password(user["password_hash"], str(data.get("current_password", ""))):
                raise ApiError("'current_password' is incorrect.", 403)
        updates["password_hash"] = hash_password(v.password(data["new_password"]))

    # admin-only fields
    admin_fields = {"role", "account_status", "verification"}
    if admin_fields & data.keys():
        if not admin:
            raise ApiError("Only administrators can change role, account status or verification.", 403)
        if "role" in data:
            updates["role"] = v.choice(data, "role", ROLES, required=True)
        if "account_status" in data:
            updates["account.status"] = v.choice(data, "account_status", ACCOUNT_STATUSES, required=True)
        if "verification" in data:
            ver = v.obj(data, "verification") or {}
            now = now_iso()
            for channel in ("email", "phone"):
                if channel in ver:
                    updates[f"verification.{channel}"] = {"verified": bool(ver[channel]),
                                                          "verified_at": now if ver[channel] else None}
            if "identity" in ver:
                updates["verification.identity.status"] = "verified" if ver["identity"] else "rejected"
                updates["verification.identity.document.check"] = {"method": "manual_review",
                                                                   "by": g.user["user_id"], "at": now}

    if not updates:
        raise ApiError("No updatable fields supplied.", 422)
    updates["updated_at"] = now_iso()
    db = get_db()
    db[USERS].update_one({"user_id": user_id}, {"$set": updates})

    fresh = db[USERS].find_one({"user_id": user_id})
    ver = fresh["verification"]
    level = sum([ver["email"]["verified"], ver["phone"]["verified"], ver["identity"]["status"] == "verified"])
    db[USERS].update_one({"user_id": user_id}, {"$set": {"verification.level": ["none", "basic", "standard", "full"][level]}})
    if any(k.startswith(("verification", "account")) for k in updates):
        recalculate_trust(db, user_id, reason="profile_updated")
    return success(clean_user(db[USERS].find_one({"user_id": user_id}), private=True), message="Profile updated.")


@bp.get("/<user_id>/trust-score")
@auth_required
def trust_score(user_id):
    db = get_db()
    get_user_or_404(user_id)
    profile = recalculate_trust(db, user_id, reason="viewed")
    return success({
        "user_id": user_id,
        "trust_score": profile["score"],
        "tier": profile["tier"],
        "breakdown": profile["breakdown"],
        "summary": profile["summary"],
        "history": profile["history"],
        "weights": WEIGHTS,
        "last_calculated": profile["last_calculated"],
    })


@bp.get("/<user_id>/items")
@auth_required
def user_items(user_id):
    get_user_or_404(user_id)
    query = {"owner_id": user_id, "status": {"$ne": "removed"}}
    if g.user["user_id"] != user_id and not is_admin(g.user):
        query["status"] = "active"
    items, meta = paginate(get_db()[ITEMS], query, sort=[("created_at", -1)], serializer=clean)
    return success(items, meta=meta)
