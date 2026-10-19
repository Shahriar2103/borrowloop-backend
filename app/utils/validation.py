"""Small, dependency-free request validation helpers. All raise ApiError(422) on failure."""
import re

from flask import request

from .responses import ApiError

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def get_json():
    data = request.get_json(silent=True)
    if data is None:
        raise ApiError("Request body must be valid JSON with Content-Type: application/json.", 400)
    if not isinstance(data, dict):
        raise ApiError("Request body must be a JSON object.", 400)
    return data


def require_fields(data, *fields):
    missing = [f for f in fields if data.get(f) in (None, "")]
    if missing:
        raise ApiError("Missing required field(s).", 422, details={"missing": missing})


def string(data, field, *, required=False, min_len=1, max_len=500, default=None):
    value = data.get(field)
    if value is None or value == "":
        if required:
            raise ApiError(f"'{field}' is required.", 422)
        return default
    if not isinstance(value, str):
        raise ApiError(f"'{field}' must be a string.", 422)
    value = value.strip()
    if not (min_len <= len(value) <= max_len):
        raise ApiError(f"'{field}' must be between {min_len} and {max_len} characters.", 422)
    return value


def number(data, field, *, required=False, minimum=None, maximum=None, default=None, integer=False):
    value = data.get(field)
    if value is None or value == "":
        if required:
            raise ApiError(f"'{field}' is required.", 422)
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(f"'{field}' must be a number.", 422)
    if integer and int(value) != value:
        raise ApiError(f"'{field}' must be a whole number.", 422)
    if minimum is not None and value < minimum:
        raise ApiError(f"'{field}' must be at least {minimum}.", 422)
    if maximum is not None and value > maximum:
        raise ApiError(f"'{field}' must be at most {maximum}.", 422)
    return int(value) if integer else round(float(value), 2)


def boolean(data, field, *, default=None):
    value = data.get(field)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ApiError(f"'{field}' must be true or false.", 422)
    return value


def choice(data, field, options, *, required=False, default=None):
    value = data.get(field)
    if value is None or value == "":
        if required:
            raise ApiError(f"'{field}' is required.", 422, details={"allowed": list(options)})
        return default
    if value not in options:
        raise ApiError(f"'{field}' must be one of: {', '.join(options)}.", 422, details={"allowed": list(options)})
    return value


def string_list(data, field, *, max_items=20, max_len=40):
    value = data.get(field)
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ApiError(f"'{field}' must be a list of strings.", 422)
    if len(value) > max_items:
        raise ApiError(f"'{field}' can contain at most {max_items} entries.", 422)
    return [v.strip()[:max_len] for v in value if v.strip()]


def email(value):
    if not isinstance(value, str) or not EMAIL_RE.match(value.strip()):
        raise ApiError("A valid email address is required.", 422)
    return value.strip().lower()


def password(value):
    if not isinstance(value, str) or len(value) < 8:
        raise ApiError("Password must be at least 8 characters.", 422)
    if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
        raise ApiError("Password must contain at least one letter and one number.", 422)
    return value


def obj(data, field):
    value = data.get(field)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ApiError(f"'{field}' must be an object.", 422)
    return value
