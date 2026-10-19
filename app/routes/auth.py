"""Registration, login and current-user endpoints."""
from flask import Blueprint, g, request
from pymongo.errors import DuplicateKeyError

from ..constants import CATEGORIES
from ..database import USERS, get_db
from ..models import build_user
from ..services.trust_service import recalculate_trust
from ..utils import validation as v
from ..utils.decorators import auth_required
from ..utils.helpers import clean_user, next_id, now_iso
from ..utils.responses import ApiError, success
from ..utils.security import create_token, hash_password, verify_password

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _client_info():
    ua = request.headers.get("User-Agent", "")
    os_name = next((o for o in ("Windows", "Mac OS", "Android", "iPhone", "Linux") if o in ua), "Unknown")
    browser = next((b for b in ("Edg", "Chrome", "Firefox", "Safari", "PostmanRuntime", "python-requests") if b in ua), "Unknown")
    return {
        "ip": request.headers.get("X-Forwarded-For", request.remote_addr),
        "device": {
            "type": "mobile" if any(m in ua for m in ("Android", "iPhone")) else "desktop",
            "os": {"name": os_name},
            "browser": {"name": browser.replace("Edg", "Edge"), "user_agent": ua[:200]},
        },
    }


@bp.post("/register")
def register():
    data = v.get_json()
    name = v.string(data, "name", required=True, min_len=2, max_len=80)
    email = v.email(data.get("email"))
    password = v.password(data.get("password"))
    role = v.choice(data, "role", ("borrower", "lender"), default="borrower")
    interests = v.string_list(data, "interests") or []
    unknown = [i for i in interests if i not in CATEGORIES]
    if unknown:
        raise ApiError("Unknown interest categories.", 422, details={"unknown": unknown, "allowed": list(CATEGORIES)})

    db = get_db()
    if db[USERS].find_one({"email": email}):
        raise ApiError("An account with this email already exists.", 409)

    now = now_iso()
    user = build_user(
        user_id=next_id(db, "user"), name=name, email=email, password_hash=hash_password(password),
        role=role, created_at=now, zone=data.get("neighbourhood"),
        phone=v.string(data, "phone", max_len=20), bio=v.string(data, "bio", max_len=500, default=""),
        interests=interests, email_verified=False,
    )
    try:
        db[USERS].insert_one(user)
    except DuplicateKeyError as exc:
        raise ApiError("An account with this email already exists.", 409) from exc
    recalculate_trust(db, user["user_id"], reason="account_created")
    user = db[USERS].find_one({"user_id": user["user_id"]})
    token, expires_in = create_token(user)
    return success({"user": clean_user(user, private=True), "access_token": token,
                    "token_type": "Bearer", "expires_in": expires_in}, 201, message="Account created.")


@bp.post("/login")
def login():
    data = v.get_json()
    v.require_fields(data, "email", "password")
    db = get_db()
    user = db[USERS].find_one({"email": str(data["email"]).strip().lower()})
    if not user or not verify_password(user.get("password_hash"), str(data["password"])):
        raise ApiError("Invalid email or password.", 401, "invalid_credentials")
    status = user.get("account", {}).get("status", "active")
    if status != "active":
        raise ApiError(f"This account is {status}. Contact support.", 403, "account_" + status)

    now = now_iso()
    entry = {"at": now, **_client_info()}
    db[USERS].update_one({"user_id": user["user_id"]}, {
        "$set": {"account.last_login_at": now},
        "$push": {"account.login_history": {"$each": [entry], "$slice": -10}},
    })
    user = db[USERS].find_one({"user_id": user["user_id"]})
    token, expires_in = create_token(user)
    return success({"user": clean_user(user, private=True), "access_token": token,
                    "token_type": "Bearer", "expires_in": expires_in}, message="Logged in.")


@bp.get("/me")
@auth_required
def me():
    return success(clean_user(g.user, private=True))
