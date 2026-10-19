"""Shared nested sub-documents (locations, money, condition checks)."""
from ..constants import COMMUNITY_ZONES, CURRENCY, ZONES_BY_CODE, ZONES_BY_NAME


def resolve_zone(value):
    """Accept a zone code ('E8-HAC') or neighbourhood name ('Hackney Central')."""
    if not value:
        return COMMUNITY_ZONES[0]
    if isinstance(value, dict):
        return value
    return ZONES_BY_CODE.get(value) or ZONES_BY_NAME.get(str(value).lower()) or COMMUNITY_ZONES[0]


def build_location(zone, line1=None, postcode_suffix=None, lat_offset=0.0, lng_offset=0.0):
    zone = resolve_zone(zone)
    postcode = zone["postcode"] + (f" {postcode_suffix}" if postcode_suffix else "")
    return {
        "address": {
            "line1": line1,
            "city": "London",
            "postcode": postcode,
            "country": "United Kingdom",
        },
        "geo": {
            "type": "Point",
            "coordinates": [round(zone["lng"] + lng_offset, 6), round(zone["lat"] + lat_offset, 6)],
        },
        "community": {
            "neighbourhood": zone["neighbourhood"],
            "borough": zone["borough"],
            "zone": {"code": zone["code"], "name": f"{zone['neighbourhood']} sharing circle", "radius_km": 2.5},
        },
    }


def community_only(location):
    """Strip a location down to the public, neighbourhood-level part."""
    if not location:
        return None
    return {"community": location.get("community")}


def money(amount, currency=CURRENCY):
    return {"amount": round(float(amount or 0), 2), "currency": currency}


def build_condition_check(grade, notes=None, photos=None, cosmetic=None, functional=None, missing=None):
    score_for = {"new": 5, "like_new": 5, "good": 4, "fair": 3, "poor": 2}
    base = score_for.get(grade, 3)
    return {
        "grade": grade,
        "checklist": {
            "cosmetic": {"score": cosmetic if cosmetic is not None else base, "notes": notes},
            "functional": {"score": functional if functional is not None else base, "notes": None},
            "completeness": {"complete": not missing, "missing": missing or []},
        },
        "photos": photos or [],
    }
