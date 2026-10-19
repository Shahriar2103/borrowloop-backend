"""Item listings: public browsing/search and owner management."""
from flask import Blueprint, g, request

from ..constants import CATEGORIES, CONDITIONS, MAX_LOAN_DAYS, PICKUP_METHODS
from ..database import ITEMS, REQUESTS, TRANSACTIONS, USERS, get_db
from ..models import build_item
from ..models.common import build_location, community_only, resolve_zone
from ..services.stats_service import refresh_user_stats
from ..utils import validation as v
from ..utils.decorators import auth_optional, auth_required, is_admin
from ..utils.helpers import (arg_bool, clean, next_id, now_iso, paginate, parse_sort, public_user_summary,
                             regex_contains)
from ..utils.responses import ApiError, success

bp = Blueprint("items", __name__, url_prefix="/api/items")

SORTABLE = {"created_at": "created_at", "name": "name", "deposit": "deposit",
            "rating": "stats.rating.average", "popularity": "stats.times_borrowed", "condition": "condition"}


def item_summary(doc):
    images = doc.get("media", {}).get("images", [])
    cover = images[doc.get("media", {}).get("cover_index", 0)] if images else None
    return {
        "item_id": doc["item_id"],
        "owner_id": doc["owner_id"],
        "name": doc["name"],
        "category": doc["category"],
        "subcategory": doc.get("taxonomy", {}).get("subcategory", {}).get("key"),
        "condition": doc["condition"],
        "availability": doc["availability"],
        "deposit": doc["deposit"],
        "status": doc.get("status"),
        "tags": doc.get("taxonomy", {}).get("tags", []),
        "cover_image": cover["variants"]["thumb"]["url"] if cover else None,
        "rating": doc.get("stats", {}).get("rating", {}).get("average"),
        "times_borrowed": doc.get("stats", {}).get("times_borrowed", 0),
        "community": doc.get("pickup", {}).get("location", {}).get("community"),
        "created_at": doc["created_at"],
    }


def _serializer():
    return clean if request.args.get("view") == "full" else item_summary


def get_item_or_404(item_id, include_removed=False):
    item = get_db()[ITEMS].find_one({"item_id": item_id})
    if not item or (item.get("status") == "removed" and not include_removed):
        raise ApiError(f"Item '{item_id}' not found.", 404)
    return item


def build_search_query(default_available=True):
    query = {"status": "active"}
    available = arg_bool("available", default_available)
    if available is not None:
        query["availability"] = available
    name = request.args.get("name") or request.args.get("q")
    if name:
        query["$or"] = [{"name": regex_contains(name)}, {"description": regex_contains(name)},
                        {"taxonomy.tags": regex_contains(name)}, {"details.brand": regex_contains(name)}]
    category = request.args.get("category")
    if category:
        cats = [c.strip() for c in category.split(",") if c.strip()]
        bad = [c for c in cats if c not in CATEGORIES]
        if bad:
            raise ApiError("Unknown category.", 422, details={"unknown": bad, "allowed": list(CATEGORIES)})
        query["category"] = {"$in": cats}
    if request.args.get("subcategory"):
        query["taxonomy.subcategory.key"] = request.args["subcategory"]
    if request.args.get("condition"):
        conds = [c for c in request.args["condition"].split(",") if c]
        query["condition"] = {"$in": conds}
    deposit = {}
    for arg, op in (("min_deposit", "$gte"), ("max_deposit", "$lte")):
        if request.args.get(arg):
            try:
                deposit[op] = float(request.args[arg])
            except ValueError as exc:
                raise ApiError(f"'{arg}' must be a number.", 422) from exc
    if deposit:
        query["deposit"] = deposit
    if request.args.get("neighbourhood"):
        query["pickup.location.community.neighbourhood"] = regex_contains(request.args["neighbourhood"])
    if request.args.get("zone"):
        query["pickup.location.community.zone.code"] = request.args["zone"]
    if request.args.get("owner_id"):
        query["owner_id"] = request.args["owner_id"]
    if request.args.get("max_trust_required"):
        query["lending_rules.min_trust_score"] = {"$lte": float(request.args["max_trust_required"])}
    return query


@bp.get("")
def list_items():
    query = build_search_query(default_available=True)
    sort = parse_sort(SORTABLE, [("created_at", -1)])
    items, meta = paginate(get_db()[ITEMS], query, sort=sort, serializer=_serializer())
    return success(items, meta=meta)


@bp.get("/search")
def search_items():
    query = build_search_query(default_available=None)
    sort = parse_sort(SORTABLE, [("created_at", -1)])
    items, meta = paginate(get_db()[ITEMS], query, sort=sort, serializer=_serializer())
    meta["filters"] = {k: v_ for k, v_ in request.args.items() if k not in ("page", "per_page")}
    return success(items, meta=meta)


@bp.get("/<item_id>")
@auth_optional
def get_item(item_id):
    db = get_db()
    owner_view = g.user and (is_admin(g.user))
    item = db[ITEMS].find_one({"item_id": item_id})
    if g.user and item and item["owner_id"] == g.user["user_id"]:
        owner_view = True
    if not item or (item.get("status") == "removed" and not owner_view):
        raise ApiError(f"Item '{item_id}' not found.", 404)
    if item.get("status") == "paused" and not owner_view:
        raise ApiError(f"Item '{item_id}' is not currently listed.", 404)
    db[ITEMS].update_one({"item_id": item_id}, {"$inc": {"stats.views": 1}})
    item["stats"]["views"] = item["stats"].get("views", 0) + 1
    owner = db[USERS].find_one({"user_id": item["owner_id"]})
    out = clean(item)
    out["owner"] = public_user_summary(owner)
    if not owner_view:
        out["availability_details"]["calendar"]["booked"] = [
            {"from": b["from"], "to": b["to"]} for b in item["availability_details"]["calendar"]["booked"]]
    return success(out)


def _item_fields(data, partial):
    """Validate the writable item fields. Returns (top_level, nested $set fields)."""
    fields = {}
    nested = {}
    if not partial or "name" in data:
        fields["name"] = v.string(data, "name", required=True, min_len=2, max_len=120)
    if not partial or "description" in data:
        fields["description"] = v.string(data, "description", required=True, min_len=10, max_len=2000)
    if not partial or "category" in data:
        fields["category"] = v.choice(data, "category", tuple(CATEGORIES), required=True)
    if not partial or "condition" in data:
        fields["condition"] = v.choice(data, "condition", CONDITIONS, required=True)
    if not partial or "deposit" in data:
        fields["deposit"] = v.number(data, "deposit", minimum=0, maximum=5000, default=0.0)
    category = fields.get("category") or data.get("_existing_category")
    if "subcategory" in data:
        subs = CATEGORIES[category]["subcategories"]
        fields["subcategory"] = v.choice(data, "subcategory", tuple(subs), required=True)
    rules = v.obj(data, "lending_rules")
    if rules is not None:
        min_days = v.number(rules, "min_days", minimum=1, maximum=MAX_LOAN_DAYS, integer=True, default=None)
        max_days = v.number(rules, "max_days", minimum=1, maximum=MAX_LOAN_DAYS, integer=True, default=None)
        if min_days and max_days and min_days > max_days:
            raise ApiError("'lending_rules.min_days' cannot exceed 'max_days'.", 422)
        trust = v.number(rules, "min_trust_score", minimum=0, maximum=100, default=None)
        for key, val in (("min_days", min_days), ("max_days", max_days), ("min_trust_score", trust)):
            if val is not None:
                nested[f"lending_rules.{key}"] = val
        if "requires_id_verification" in rules:
            nested["lending_rules.requires_id_verification"] = v.boolean(rules, "requires_id_verification")
    if "tags" in data:
        nested["taxonomy.tags"] = v.string_list(data, "tags") or []
    for key in ("brand", "model"):
        if key in data:
            nested[f"details.{key}"] = v.string(data, key, max_len=80)
    if "specifications" in data:
        nested["details.specifications"] = v.obj(data, "specifications") or {}
    if "pickup_methods" in data:
        methods = v.string_list(data, "pickup_methods") or []
        bad = [m for m in methods if m not in PICKUP_METHODS]
        if bad or not methods:
            raise ApiError("Invalid pickup methods.", 422, details={"allowed": PICKUP_METHODS})
        nested["pickup.methods"] = methods
    if "images" in data:
        images = v.string_list(data, "images", max_items=8, max_len=500) or []
        nested["_images"] = images
    if "late_fee_per_day" in data:
        nested["pricing.late_fee.per_day"] = v.number(data, "late_fee_per_day", minimum=0, maximum=500)
    return fields, nested


@bp.post("")
@auth_required
def create_item():
    data = v.get_json()
    fields, nested = _item_fields(data, partial=False)
    db = get_db()
    user = g.user
    if user.get("role") == "borrower":
        # a borrower who lists an item becomes a lender
        db[USERS].update_one({"user_id": user["user_id"]}, {"$set": {"role": "lender"}})
    zone = resolve_zone(data.get("neighbourhood") or
                        user.get("profile", {}).get("location", {}).get("community", {}).get("zone", {}).get("code"))
    now = now_iso()
    rules = data.get("lending_rules") or {}
    item = build_item(
        item_id=next_id(db, "item"), owner_id=user["user_id"], name=fields["name"],
        category=fields["category"], description=fields["description"], condition=fields["condition"],
        deposit=fields["deposit"], created_at=now, subcategory=fields.get("subcategory"),
        item_type=v.string(data, "type", max_len=40), tags=nested.get("taxonomy.tags"),
        brand=nested.get("details.brand"), model=nested.get("details.model"),
        specifications=nested.get("details.specifications"), images=nested.get("_images"),
        min_days=rules.get("min_days", 1), max_days=rules.get("max_days", 14),
        min_trust_score=rules.get("min_trust_score", 0),
        requires_id_verification=bool(rules.get("requires_id_verification", False)),
        late_fee_per_day=nested.get("pricing.late_fee.per_day"),
        pickup_methods=nested.get("pickup.methods"), owner_location=build_location(zone),
    )
    db[ITEMS].insert_one(item)
    refresh_user_stats(db, user["user_id"])
    return success(clean(db[ITEMS].find_one({"item_id": item["item_id"]})), 201, message="Item listed.")


def _require_owner(item):
    if item["owner_id"] != g.user["user_id"] and not is_admin(g.user):
        raise ApiError("You can only manage your own items.", 403)


@bp.put("/<item_id>")
@auth_required
def update_item(item_id):
    item = get_item_or_404(item_id)
    _require_owner(item)
    data = v.get_json()
    data["_existing_category"] = item["category"]
    fields, nested = _item_fields(data, partial=True)
    updates = {}
    on_loan = item.get("availability_details", {}).get("status") == "on_loan"

    for key in ("name", "description", "condition", "deposit", "category"):
        if key in fields:
            updates[key] = fields[key]
    if "category" in fields or "subcategory" in fields:
        cat = fields.get("category", item["category"])
        subs = CATEGORIES[cat]["subcategories"]
        sub = fields.get("subcategory") or next(iter(subs))
        if sub not in subs:
            raise ApiError("Subcategory does not belong to this category.", 422, details={"allowed": list(subs)})
        updates["taxonomy.category"] = {"key": cat, "label": CATEGORIES[cat]["label"]}
        updates["taxonomy.subcategory"] = {"key": sub, "label": subs[sub]["label"]}
    if "condition" in fields:
        updates["condition_report.grade"] = fields["condition"]
    if "deposit" in fields:
        dep = fields["deposit"]
        updates["pricing.deposit.amount"] = dep
        updates["pricing.deposit.refund_policy.deductions.late_return.max_total"] = round(dep * 0.5, 2)
        updates["pricing.deposit.refund_policy.deductions.damage"] = {"minor": round(dep * 0.25, 2), "major": dep}
    images = nested.pop("_images", None)
    if images is not None:
        updates["media.images"] = [{"url": u, "alt": f"{item['name']} photo {i + 1}",
                                    "variants": {"thumb": {"url": u + "?w=200", "width": 200, "height": 150},
                                                 "full": {"url": u + "?w=1200", "width": 1200, "height": 900}},
                                    "uploaded_at": now_iso()} for i, u in enumerate(images)]
        updates["media.cover_index"] = 0
    updates.update(nested)

    if "status" in data:
        status = v.choice(data, "status", ("active", "paused"), required=True)
        updates["status"] = status
        if not on_loan:
            updates["availability"] = status == "active"
            updates["availability_details.status"] = "available" if status == "active" else "unavailable"
    if "availability" in data:
        avail = v.boolean(data, "availability")
        if on_loan and avail:
            raise ApiError("Item is currently on loan; availability will update when it is returned.", 409)
        updates["availability"] = avail and updates.get("status", item.get("status")) == "active"
        if not on_loan:
            updates["availability_details.status"] = "available" if updates["availability"] else "unavailable"
    if "neighbourhood" in data:
        loc = build_location(resolve_zone(data["neighbourhood"]))
        updates["pickup.location"] = community_only(loc) | {"geo": loc["geo"]}

    if not updates:
        raise ApiError("No updatable fields supplied.", 422)
    updates["updated_at"] = now_iso()
    db = get_db()
    db[ITEMS].update_one({"item_id": item_id}, {"$set": updates})
    return success(clean(db[ITEMS].find_one({"item_id": item_id})), message="Item updated.")


@bp.delete("/<item_id>")
@auth_required
def delete_item(item_id):
    db = get_db()
    item = get_item_or_404(item_id)
    _require_owner(item)
    if db[TRANSACTIONS].count_documents({"item_id": item_id, "status": "active"}):
        raise ApiError("This item is currently on loan and cannot be removed until it is returned.", 409)
    now = now_iso()
    # cancel open requests on this item
    open_reqs = list(db[REQUESTS].find({"item_id": item_id, "status": {"$in": ["pending", "accepted"]}}))
    for r in open_reqs:
        db[REQUESTS].update_one({"request_id": r["request_id"]}, {
            "$set": {"status": "cancelled", "updated_at": now,
                     "cancellation": {"by": g.user["user_id"], "role": "lender", "at": now,
                                      "reason": "Item removed by owner",
                                      "after_acceptance": r["status"] == "accepted"}},
            "$push": {"status_history": {"status": "cancelled", "at": now,
                                         "by": {"user_id": g.user["user_id"], "role": "lender"},
                                         "note": "Item removed from BorrowLoop"}}})
    # soft delete keeps history (transactions/reviews) consistent
    db[ITEMS].update_one({"item_id": item_id}, {"$set": {
        "status": "removed", "availability": False, "availability_details.status": "unavailable",
        "availability_details.calendar.booked": [], "updated_at": now}})
    refresh_user_stats(db, item["owner_id"])
    return success({"item_id": item_id, "cancelled_requests": [r["request_id"] for r in open_reqs]},
                   message="Item removed.")
