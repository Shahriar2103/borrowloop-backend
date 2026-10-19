"""Health check, endpoint index and reference data."""
from flask import Blueprint, current_app

from ..constants import CATEGORIES, COMMUNITY_ZONES, CONDITIONS
from ..database import ALL_COLLECTIONS, get_db
from ..utils.helpers import now_iso
from ..utils.responses import success

bp = Blueprint("meta", __name__, url_prefix="/api")


@bp.get("/health")
def health():
    db = get_db()
    return success({
        "status": "ok",
        "time": now_iso(),
        "database": {
            "backend": current_app.config.get("DB_BACKEND"),
            "name": db.name,
            "collections": {name: db[name].count_documents({}) for name in ALL_COLLECTIONS},
        },
    })


@bp.get("")
@bp.get("/")
def index():
    routes = []
    for rule in current_app.url_map.iter_rules():
        if rule.rule.startswith("/api"):
            methods = sorted(m for m in rule.methods if m not in ("HEAD", "OPTIONS"))
            routes.append({"path": rule.rule, "methods": methods})
    routes.sort(key=lambda r: r["path"])
    return success({"name": "BorrowLoop API", "version": "1.0.0", "endpoints": routes})


@bp.get("/categories")
def categories():
    return success({"categories": CATEGORIES, "conditions": list(CONDITIONS)})


@bp.get("/communities")
def communities():
    return success([{k: z[k] for k in ("neighbourhood", "borough", "code", "postcode")} for z in COMMUNITY_ZONES])
