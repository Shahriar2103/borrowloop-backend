"""Date, ID, pagination and serialisation helpers.

All timestamps are stored as ISO-8601 UTC strings ("2026-10-18T14:30:00Z"), which
sort and compare correctly as plain strings in MongoDB.
"""
import copy
import re
from datetime import date, datetime, timedelta, timezone

from flask import current_app, request
from pymongo import ReturnDocument

from ..constants import ID_PREFIXES
from .responses import ApiError

ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"


# ---------------------------------------------------------------- dates
def utcnow():
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt):
    if dt is None:
        return None
    if isinstance(dt, date) and not isinstance(dt, datetime):
        dt = datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime(ISO_FMT)


def now_iso():
    return iso(utcnow())


def parse_dt(value, field="date"):
    """Parse 'YYYY-MM-DD' or a full ISO-8601 string into an aware UTC datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        raise ApiError(f"'{field}' must be a date string (YYYY-MM-DD or ISO-8601).", 422)
    text = value.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ApiError(f"'{field}' is not a valid date: {value}", 422) from exc


def days_between(start, end):
    """Whole days between two datetimes (rounded up, minimum 1)."""
    seconds = (end - start).total_seconds()
    return max(1, int(-(-seconds // 86400)))


def add_days(dt, days):
    return dt + timedelta(days=days)


# ---------------------------------------------------------------- ids
def next_id(db, kind):
    """Atomic, human-readable IDs such as USR-00042 using a counters collection."""
    prefix = ID_PREFIXES[kind]
    counter = db.counters.find_one_and_update(
        {"_id": kind}, {"$inc": {"seq": 1}}, upsert=True, return_document=ReturnDocument.AFTER
    )
    return f"{prefix}-{counter['seq']:05d}"


# ---------------------------------------------------------------- serialisation
PRIVATE_USER_FIELDS = ("password_hash",)


def clean(doc):
    """Return a JSON-safe copy of a Mongo document without the internal _id."""
    if doc is None:
        return None
    out = copy.deepcopy(doc)
    out.pop("_id", None)
    return out


def clean_user(doc, private=False):
    """Serialise a user. `private` shows contact/account detail (self or admin)."""
    if doc is None:
        return None
    out = clean(doc)
    for f in PRIVATE_USER_FIELDS:
        out.pop(f, None)
    if not private:
        out.pop("email", None)
        out.pop("preferences", None)
        account = out.get("account", {})
        out["account"] = {"status": account.get("status"), "badges": account.get("badges", [])}
        profile = out.get("profile", {})
        profile.pop("contact", None)
        location = profile.get("location", {})
        # only expose the neighbourhood-level community info publicly
        profile["location"] = {"community": location.get("community")}
        verification = out.get("verification", {})
        out["verification"] = {"level": verification.get("level")}
    return out


def public_user_summary(doc):
    if not doc:
        return None
    return {
        "user_id": doc["user_id"],
        "name": doc["name"],
        "role": doc.get("role"),
        "trust": {"score": doc.get("trust_score"), "tier": doc.get("trust_profile", {}).get("tier")},
        "community": doc.get("profile", {}).get("location", {}).get("community"),
    }


def deep_merge(base, updates):
    """Recursively merge `updates` into `base` (mutates and returns base)."""
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def flatten_for_set(updates, prefix=""):
    """{'a': {'b': 1}} -> {'a.b': 1} so nested fields can be $set without overwriting siblings."""
    flat = {}
    for key, value in updates.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict) and value:
            flat.update(flatten_for_set(value, path + "."))
        else:
            flat[path] = value
    return flat


# ---------------------------------------------------------------- pagination
def pagination_args():
    cfg = current_app.config
    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = int(request.args.get("per_page", cfg["DEFAULT_PAGE_SIZE"]))
    except ValueError as exc:
        raise ApiError("'page' and 'per_page' must be integers.", 422) from exc
    per_page = min(max(1, per_page), cfg["MAX_PAGE_SIZE"])
    return page, per_page


def paginate(collection, query, sort=None, projection=None, serializer=clean):
    page, per_page = pagination_args()
    total = collection.count_documents(query)
    cursor = collection.find(query, projection)
    if sort:
        cursor = cursor.sort(sort)
    cursor = cursor.skip((page - 1) * per_page).limit(per_page)
    items = [serializer(d) for d in cursor]
    pages = max(1, -(-total // per_page))
    meta = {"page": page, "per_page": per_page, "total": total, "pages": pages,
            "has_next": page < pages, "has_prev": page > 1}
    return items, meta


def parse_sort(allowed, default):
    """?sort=-created_at,name -> [("created_at", -1), ("name", 1)] limited to `allowed`."""
    raw = request.args.get("sort")
    if not raw:
        return default
    result = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        direction = -1 if part.startswith("-") else 1
        field = part.lstrip("-+")
        if field not in allowed:
            raise ApiError(f"Cannot sort by '{field}'. Allowed: {', '.join(sorted(allowed))}", 422)
        result.append((allowed[field], direction))
    return result or default


def arg_bool(name, default=None):
    value = request.args.get(name)
    if value is None or value == "" or value.lower() == "all":
        return default
    if value.lower() in ("true", "1", "yes"):
        return True
    if value.lower() in ("false", "0", "no"):
        return False
    raise ApiError(f"'{name}' must be true, false or all.", 422)


def regex_contains(text):
    return {"$regex": re.escape(text.strip()), "$options": "i"}
