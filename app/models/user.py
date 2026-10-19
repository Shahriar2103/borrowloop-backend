"""User document builder.

Nesting example (5 levels): profile.location.community.zone.code
                (6 levels): preferences.notifications.events.return_reminders.schedule.days_before_due
"""
from .common import build_location, money


def empty_trust_profile(now):
    return {
        "score": None,
        "tier": "new",
        "last_calculated": now,
        "breakdown": {},
        "summary": {},
        "history": [],
    }


def empty_stats():
    return {
        "borrowing": {"total_requests": 0, "completed": 0, "active": 0, "late_returns": 0,
                      "on_time_rate": None, "categories": {}},
        "lending": {"items_listed": 0, "requests_received": 0, "completed": 0, "active": 0,
                    "acceptance_rate": None, "total_days_lent": 0},
        "reviews": {"received": {"count": 0, "average": None,
                                 "distribution": {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}},
                    "given": {"count": 0}},
    }


def build_user(*, user_id, name, email, password_hash, role, created_at, zone=None, line1=None,
               phone=None, bio="", interests=None, avatar_seed=None, email_verified=False,
               phone_verified=False, identity_status="not_submitted"):
    avatar_seed = avatar_seed or user_id
    avatar_base = f"https://api.dicebear.com/7.x/initials/svg?seed={avatar_seed}"
    verified_level = sum([bool(email_verified), bool(phone_verified), identity_status == "verified"])
    return {
        "user_id": user_id,
        "name": name,
        "email": email,
        "password_hash": password_hash,
        "role": role,
        "trust_score": None,
        "created_at": created_at,
        "updated_at": created_at,
        "profile": {
            "display_name": name.split(" ")[0],
            "bio": bio,
            "avatar": {
                "url": avatar_base,
                "variants": {
                    "small": {"url": avatar_base + "&size=64", "width": 64, "height": 64},
                    "large": {"url": avatar_base + "&size=256", "width": 256, "height": 256},
                },
            },
            "contact": {
                "phone": {"number": phone, "country_code": "+44", "verified": bool(phone_verified)},
                "preferred_method": "in_app",
            },
            "location": build_location(zone, line1),
            "interests": interests or [],
        },
        "preferences": {
            "notifications": {
                "channels": {
                    "email": {"enabled": True, "frequency": "instant"},
                    "push": {"enabled": True, "quiet_hours": {"from": "22:00", "to": "07:30"}},
                    "sms": {"enabled": False},
                },
                "events": {
                    "borrow_requests": {"enabled": True, "channels": ["email", "push"]},
                    "request_updates": {"enabled": True, "channels": ["push"]},
                    "return_reminders": {"enabled": True, "channels": ["push", "email"],
                                         "schedule": {"days_before_due": 1, "time_of_day": "09:00"}},
                    "reviews": {"enabled": True, "channels": ["email"]},
                },
            },
            "privacy": {"profile_visibility": "members", "show_location": "neighbourhood", "show_phone": False},
            "lending": {
                "auto_decline_below_trust": None,
                "max_concurrent_loans": 3,
                "default_deposit": money(0),
            },
        },
        "verification": {
            "level": ["none", "basic", "standard", "full"][verified_level],
            "email": {"verified": bool(email_verified), "verified_at": created_at if email_verified else None},
            "phone": {"verified": bool(phone_verified), "verified_at": created_at if phone_verified else None},
            "identity": {
                "status": identity_status,
                "document": {
                    "type": "passport" if identity_status != "not_submitted" else None,
                    "country": "GB" if identity_status != "not_submitted" else None,
                    "check": {"method": "manual_review" if identity_status == "verified" else None,
                              "by": None, "at": None},
                },
            },
        },
        "trust_profile": empty_trust_profile(created_at),
        "stats": empty_stats(),
        "account": {
            "status": "active",
            "last_login_at": None,
            "login_history": [],
            "badges": [],
            "moderation": {"warnings": [], "suspension": None},
        },
    }
