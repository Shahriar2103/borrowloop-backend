"""Small, dependency-free request validation helpers. All raise ApiError on failure."""

import json
import re

from flask import request

from .responses import ApiError


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------------------------------------------------------
# REQUEST BODY VALIDATION
# Supports JSON and x-www-form-urlencoded
# ---------------------------------------------------------

def get_json():
    """
    Accept request data from:
    1. application/json
    2. application/x-www-form-urlencoded

    Convert supported form values into appropriate Python types.
    """

    # JSON requests
    if request.is_json:
        data = request.get_json(silent=True)

        if data is None:
            raise ApiError(
                "Request body must contain valid JSON.",
                400
            )

        if not isinstance(data, dict):
            raise ApiError(
                "Request body must be a JSON object.",
                400
            )

        return data

    # x-www-form-urlencoded requests
    if request.mimetype == "application/x-www-form-urlencoded":

        if not request.form:
            raise ApiError(
                "Form data cannot be empty.",
                400
            )

        data = {}

        numeric_fields = {
            "deposit",
            "price",
            "rating",
            "quantity",
            "latitude",
            "longitude",
            "amount",
            "daily_rate",
            "rental_price",
            "loan_days",
            "duration_days",
        }

        boolean_fields = {
            "available",
            "availability",
            "is_available",
            "is_active",
            "active",
            "verified",
        }

        for key in request.form:

            values = request.form.getlist(key)

            # Multiple values with the same key become a list
            if len(values) > 1:
                data[key] = values
                continue

            value = values[0].strip()

            # Convert JSON objects and arrays
            if value.startswith("{") or value.startswith("["):
                try:
                    data[key] = json.loads(value)
                    continue
                except (ValueError, TypeError):
                    pass

            # Convert boolean values for known boolean fields
            if key in boolean_fields:
                if value.lower() == "true":
                    data[key] = True
                    continue

                if value.lower() == "false":
                    data[key] = False
                    continue

            # Convert numeric fields
            if key in numeric_fields:
                try:
                    number_value = float(value)

                    if number_value.is_integer():
                        data[key] = int(number_value)
                    else:
                        data[key] = number_value

                    continue

                except ValueError:
                    pass

            # Default: keep as string
            data[key] = value

        return data

    # Unsupported Content-Type
    raise ApiError(
        "Content-Type must be application/json or application/x-www-form-urlencoded.",
        400
    )


# ---------------------------------------------------------
# REQUIRED FIELD VALIDATION
# ---------------------------------------------------------

def require_fields(data, *fields):

    missing = [
        field
        for field in fields
        if data.get(field) in (None, "")
    ]

    if missing:
        raise ApiError(
            "Missing required field(s).",
            422,
            details={"missing": missing}
        )


# ---------------------------------------------------------
# STRING VALIDATION
# ---------------------------------------------------------

def string(
    data,
    field,
    *,
    required=False,
    min_len=1,
    max_len=500,
    default=None
):

    value = data.get(field)

    if value is None or value == "":
        if required:
            raise ApiError(
                f"'{field}' is required.",
                422
            )

        return default

    if not isinstance(value, str):
        raise ApiError(
            f"'{field}' must be a string.",
            422
        )

    value = value.strip()

    if not (min_len <= len(value) <= max_len):
        raise ApiError(
            f"'{field}' must be between {min_len} and {max_len} characters.",
            422
        )

    return value


# ---------------------------------------------------------
# NUMBER VALIDATION
# ---------------------------------------------------------

def number(
    data,
    field,
    *,
    required=False,
    minimum=None,
    maximum=None,
    default=None,
    integer=False
):

    value = data.get(field)

    if value is None or value == "":
        if required:
            raise ApiError(
                f"'{field}' is required.",
                422
            )

        return default

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(
            f"'{field}' must be a number.",
            422
        )

    if integer and int(value) != value:
        raise ApiError(
            f"'{field}' must be a whole number.",
            422
        )

    if minimum is not None and value < minimum:
        raise ApiError(
            f"'{field}' must be at least {minimum}.",
            422
        )

    if maximum is not None and value > maximum:
        raise ApiError(
            f"'{field}' must be at most {maximum}.",
            422
        )

    return int(value) if integer else round(float(value), 2)


# ---------------------------------------------------------
# BOOLEAN VALIDATION
# ---------------------------------------------------------

def boolean(data, field, *, default=None):

    value = data.get(field)

    if value is None:
        return default

    if not isinstance(value, bool):
        raise ApiError(
            f"'{field}' must be true or false.",
            422
        )

    return value


# ---------------------------------------------------------
# CHOICE VALIDATION
# ---------------------------------------------------------

def choice(
    data,
    field,
    options,
    *,
    required=False,
    default=None
):

    value = data.get(field)

    if value is None or value == "":
        if required:
            raise ApiError(
                f"'{field}' is required.",
                422,
                details={"allowed": list(options)}
            )

        return default

    if value not in options:
        raise ApiError(
            f"'{field}' must be one of: {', '.join(options)}.",
            422,
            details={"allowed": list(options)}
        )

    return value


# ---------------------------------------------------------
# STRING LIST VALIDATION
# ---------------------------------------------------------

def string_list(data, field, *, max_items=20, max_len=40):

    value = data.get(field)

    if value is None:
        return None

    if not isinstance(value, list) or not all(
        isinstance(v, str) for v in value
    ):
        raise ApiError(
            f"'{field}' must be a list of strings.",
            422
        )

    if len(value) > max_items:
        raise ApiError(
            f"'{field}' can contain at most {max_items} entries.",
            422
        )

    return [
        value_item.strip()[:max_len]
        for value_item in value
        if value_item.strip()
    ]


# ---------------------------------------------------------
# EMAIL VALIDATION
# ---------------------------------------------------------

def email(value):

    if not isinstance(value, str) or not EMAIL_RE.match(value.strip()):
        raise ApiError(
            "A valid email address is required.",
            422
        )

    return value.strip().lower()


# ---------------------------------------------------------
# PASSWORD VALIDATION
# ---------------------------------------------------------

def password(value):

    if not isinstance(value, str) or len(value) < 8:
        raise ApiError(
            "Password must be at least 8 characters.",
            422
        )

    if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
        raise ApiError(
            "Password must contain at least one letter and one number.",
            422
        )

    return value


# ---------------------------------------------------------
# OBJECT VALIDATION
# ---------------------------------------------------------

def obj(data, field):

    value = data.get(field)

    if value is None:
        return None

    if not isinstance(value, dict):
        raise ApiError(
            f"'{field}' must be an object.",
            422
        )

    return value