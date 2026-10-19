"""Item (listing) document builder.

Nesting example (5 levels): pickup.location.community.zone.code
                (5 levels): pricing.deposit.refund_policy.deductions.damage.major
"""
from ..constants import CATEGORIES, CURRENCY
from .common import build_condition_check, build_location, community_only


def build_item(*, item_id, owner_id, name, category, description, condition, deposit, created_at,
               subcategory=None, item_type=None, tags=None, brand=None, model=None, year=None,
               specifications=None, attributes=None, accessories=None, images=None,
               min_days=1, max_days=14, min_trust_score=0, requires_id_verification=False,
               late_fee_per_day=None, pickup_methods=None, zone=None, owner_location=None,
               inspector=None):
    sub = subcategory or next(iter(CATEGORIES[category]["subcategories"]))
    deposit = round(float(deposit or 0), 2)
    late_fee = late_fee_per_day if late_fee_per_day is not None else round(max(1.0, deposit * 0.05), 2)
    location = owner_location or build_location(zone)
    images = images or []
    return {
        "item_id": item_id,
        "owner_id": owner_id,
        "name": name,
        "category": category,
        "description": description,
        "condition": condition,
        "availability": True,
        "deposit": deposit,
        "created_at": created_at,
        "updated_at": created_at,
        "status": "active",
        "taxonomy": {
            "category": {"key": category, "label": CATEGORIES[category]["label"]},
            "subcategory": {"key": sub, "label": CATEGORIES[category]["subcategories"].get(sub, {}).get("label", sub)},
            "type": item_type,
            "tags": tags or [],
            "attributes": attributes or {},
        },
        "details": {
            "brand": brand,
            "model": model,
            "year": year,
            "specifications": specifications or {},
            "included_accessories": accessories or [],
        },
        "condition_report": {
            "grade": condition,
            "summary": f"Listed in {condition.replace('_', ' ')} condition.",
            "last_inspected_at": created_at,
            "inspections": [
                {"at": created_at, "by": inspector or owner_id, "context": "listing",
                 "result": build_condition_check(condition)}
            ],
        },
        "pricing": {
            "deposit": {
                "amount": deposit,
                "currency": CURRENCY,
                "refund_policy": {
                    "type": "full_refund_on_good_return",
                    "processing_days": 3,
                    "deductions": {
                        "late_return": {"per_day": late_fee, "max_total": round(deposit * 0.5, 2)},
                        "damage": {"minor": round(deposit * 0.25, 2), "major": deposit},
                    },
                },
            },
            "late_fee": {"per_day": late_fee, "grace_period_hours": 6, "currency": CURRENCY},
        },
        "lending_rules": {
            "min_days": min_days,
            "max_days": max_days,
            "min_trust_score": min_trust_score,
            "requires_id_verification": requires_id_verification,
            "max_advance_booking_days": 60,
        },
        "availability_details": {
            "status": "available",
            "current_transaction_id": None,
            "next_available_from": created_at,
            "calendar": {"booked": [], "blocked": []},
        },
        "pickup": {
            "methods": pickup_methods or ["collection"],
            "location": community_only(location) | {"geo": location.get("geo")},
            "schedule": {
                "weekdays": {"slots": [{"from": "18:00", "to": "20:30"}]},
                "weekends": {"slots": [{"from": "10:00", "to": "12:00"}, {"from": "15:00", "to": "18:00"}]},
            },
        },
        "media": {
            "cover_index": 0,
            "images": [
                {
                    "url": url,
                    "alt": f"{name} photo {i + 1}",
                    "variants": {
                        "thumb": {"url": url + "?w=200", "width": 200, "height": 150},
                        "full": {"url": url + "?w=1200", "width": 1200, "height": 900},
                    },
                    "uploaded_at": created_at,
                }
                for i, url in enumerate(images)
            ],
        },
        "stats": {
            "views": 0,
            "times_borrowed": 0,
            "total_days_lent": 0,
            "last_borrowed_at": None,
            "rating": {"average": None, "count": 0,
                       "distribution": {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}},
        },
        "moderation": {"status": "approved", "flags": [], "review": {"by": None, "at": None, "decision": None}},
    }
