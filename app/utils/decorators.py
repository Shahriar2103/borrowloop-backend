"""Route protection decorators. The authenticated user document is placed on flask.g.user."""
from functools import wraps

from flask import g, request

from ..database import USERS, get_db
from .responses import ApiError
from .security import decode_token


def _load_user_from_header(required=True):
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        if required:
            raise ApiError("Authentication required. Send 'Authorization: Bearer <token>'.", 401)
        return None
    payload = decode_token(header.split(" ", 1)[1].strip())
    user = get_db()[USERS].find_one({"user_id": payload.get("sub")})
    if not user:
        raise ApiError("The account for this token no longer exists.", 401, "invalid_token")
    status = user.get("account", {}).get("status", "active")
    if status != "active":
        raise ApiError(f"This account is {status}. Contact support.", 403, "account_" + status)
    return user


def auth_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        g.user = _load_user_from_header(required=True)
        return fn(*args, **kwargs)

    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        g.user = _load_user_from_header(required=True)
        if g.user.get("role") != "admin":
            raise ApiError("Administrator access required.", 403)
        return fn(*args, **kwargs)

    return wrapper


def auth_optional(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            g.user = _load_user_from_header(required=False)
        except ApiError:
            g.user = None
        return fn(*args, **kwargs)

    return wrapper


def is_admin(user):
    return bool(user) and user.get("role") == "admin"
