"""Password hashing and JWT access tokens."""
from datetime import timedelta

import jwt
from flask import current_app
from werkzeug.security import check_password_hash, generate_password_hash

from .helpers import utcnow
from .responses import ApiError


def hash_password(password):
    return generate_password_hash(password)


def verify_password(password_hash, password):
    if not password_hash:
        return False
    return check_password_hash(password_hash, password)


def create_token(user):
    now = utcnow()
    hours = current_app.config["JWT_EXPIRES_HOURS"]
    payload = {
        "sub": user["user_id"],
        "role": user["role"],
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=hours)).timestamp()),
    }
    token = jwt.encode(payload, current_app.config["JWT_SECRET_KEY"], algorithm=current_app.config["JWT_ALGORITHM"])
    return token, hours * 3600


def decode_token(token):
    try:
        return jwt.decode(token, current_app.config["JWT_SECRET_KEY"], algorithms=[current_app.config["JWT_ALGORITHM"]])
    except jwt.ExpiredSignatureError as exc:
        raise ApiError("Token has expired. Please log in again.", 401, "token_expired") from exc
    except jwt.InvalidTokenError as exc:
        raise ApiError("Invalid authentication token.", 401, "invalid_token") from exc
