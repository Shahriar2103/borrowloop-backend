"""Domain constants shared by the API, the trust engine and the dataset generator."""

ROLES = ("borrower", "lender", "admin")
ACCOUNT_STATUSES = ("active", "suspended", "banned")

# Ordered best -> worst. The index is used to measure condition changes.
CONDITIONS = ("new", "like_new", "good", "fair", "poor")
CONDITION_RANK = {c: i for i, c in enumerate(CONDITIONS)}

ITEM_STATUSES = ("active", "paused", "removed")
REQUEST_STATUSES = ("pending", "accepted", "rejected", "cancelled")
TRANSACTION_STATUSES = ("active", "completed")
REVIEW_STATUSES = ("published", "flagged", "hidden")

REPORT_TARGET_TYPES = ("user", "item", "transaction", "review")
REPORT_STATUSES = ("open", "under_review", "resolved", "dismissed")
REPORT_PRIORITIES = ("low", "medium", "high", "critical")
REPORT_CATEGORIES = {
    "safety": ["harassment", "threatening_behaviour", "unsafe_item"],
    "fraud": ["fake_listing", "deposit_scam", "identity_misuse"],
    "conduct": ["no_show", "late_return", "item_damaged", "rude_communication"],
    "content": ["prohibited_item", "misleading_description", "inappropriate_review"],
}
RESOLUTION_ACTIONS = ("none", "warning", "suspend_user", "ban_user", "remove_item", "hide_review")

PICKUP_METHODS = ("collection", "meetup", "delivery")
DAMAGE_SEVERITIES = ("none", "minor", "major")
CURRENCY = "GBP"

MAX_LOAN_DAYS = 60

# category -> subcategory -> item types
CATEGORIES = {
    "electronics": {
        "label": "Electronics",
        "subcategories": {
            "photography": {"label": "Photography", "types": ["camera", "lens", "tripod"]},
            "computing": {"label": "Computing", "types": ["laptop", "tablet", "projector"]},
            "audio": {"label": "Audio", "types": ["speaker", "headphones"]},
            "calculators": {"label": "Calculators", "types": ["scientific", "graphing"]},
            "power": {"label": "Power & Charging", "types": ["power_bank", "charger"]},
        },
    },
    "books": {
        "label": "Books",
        "subcategories": {
            "textbooks": {"label": "Textbooks", "types": ["computer_science", "mathematics", "business"]},
            "fiction": {"label": "Fiction", "types": ["novel", "classic"]},
            "reference": {"label": "Reference", "types": ["dictionary", "guide"]},
        },
    },
    "tools": {
        "label": "Tools & DIY",
        "subcategories": {
            "power_tools": {"label": "Power Tools", "types": ["drill", "sander", "jigsaw"]},
            "hand_tools": {"label": "Hand Tools", "types": ["toolkit", "ladder"]},
            "cleaning": {"label": "Cleaning", "types": ["pressure_washer", "carpet_cleaner"]},
        },
    },
    "sports_outdoor": {
        "label": "Sports & Outdoor",
        "subcategories": {
            "camping": {"label": "Camping", "types": ["tent", "sleeping_bag", "stove"]},
            "cycling": {"label": "Cycling", "types": ["bike", "bike_rack"]},
            "fitness": {"label": "Fitness", "types": ["weights", "yoga_kit"]},
        },
    },
    "kitchen": {
        "label": "Kitchen",
        "subcategories": {
            "appliances": {"label": "Appliances", "types": ["mixer", "air_fryer", "blender"]},
            "cookware": {"label": "Cookware", "types": ["pressure_cooker", "fondue_set"]},
        },
    },
    "music": {
        "label": "Music",
        "subcategories": {
            "instruments": {"label": "Instruments", "types": ["guitar", "keyboard", "ukulele"]},
            "recording": {"label": "Recording", "types": ["microphone", "audio_interface"]},
        },
    },
    "party_events": {
        "label": "Party & Events",
        "subcategories": {
            "furniture": {"label": "Furniture", "types": ["folding_table", "gazebo"]},
            "entertainment": {"label": "Entertainment", "types": ["karaoke", "lighting"]},
        },
    },
    "gaming": {
        "label": "Gaming",
        "subcategories": {
            "consoles": {"label": "Consoles", "types": ["console", "vr_headset"]},
            "board_games": {"label": "Board Games", "types": ["strategy", "party"]},
        },
    },
    "garden": {
        "label": "Garden",
        "subcategories": {
            "machinery": {"label": "Machinery", "types": ["lawn_mower", "hedge_trimmer"]},
            "equipment": {"label": "Equipment", "types": ["wheelbarrow", "hose_reel"]},
        },
    },
    "baby_kids": {
        "label": "Baby & Kids",
        "subcategories": {
            "travel": {"label": "Travel", "types": ["pushchair", "car_seat"]},
            "play": {"label": "Play", "types": ["play_mat", "baby_gate"]},
        },
    },
}

# Community zones used for locations (London neighbourhoods).
COMMUNITY_ZONES = [
    {"neighbourhood": "Camden Town", "borough": "Camden", "code": "NW1-CAM", "postcode": "NW1", "lat": 51.5390, "lng": -0.1426},
    {"neighbourhood": "Kentish Town", "borough": "Camden", "code": "NW5-KEN", "postcode": "NW5", "lat": 51.5505, "lng": -0.1404},
    {"neighbourhood": "Hackney Central", "borough": "Hackney", "code": "E8-HAC", "postcode": "E8", "lat": 51.5450, "lng": -0.0553},
    {"neighbourhood": "Dalston", "borough": "Hackney", "code": "E8-DAL", "postcode": "E8", "lat": 51.5462, "lng": -0.0750},
    {"neighbourhood": "Islington", "borough": "Islington", "code": "N1-ISL", "postcode": "N1", "lat": 51.5362, "lng": -0.1033},
    {"neighbourhood": "Peckham", "borough": "Southwark", "code": "SE15-PEC", "postcode": "SE15", "lat": 51.4740, "lng": -0.0690},
    {"neighbourhood": "Brixton", "borough": "Lambeth", "code": "SW2-BRX", "postcode": "SW2", "lat": 51.4613, "lng": -0.1156},
    {"neighbourhood": "Whitechapel", "borough": "Tower Hamlets", "code": "E1-WHC", "postcode": "E1", "lat": 51.5196, "lng": -0.0598},
    {"neighbourhood": "Greenwich", "borough": "Greenwich", "code": "SE10-GRN", "postcode": "SE10", "lat": 51.4826, "lng": -0.0077},
    {"neighbourhood": "Stratford", "borough": "Newham", "code": "E15-STR", "postcode": "E15", "lat": 51.5413, "lng": 0.0033},
]
ZONES_BY_CODE = {z["code"]: z for z in COMMUNITY_ZONES}
ZONES_BY_NAME = {z["neighbourhood"].lower(): z for z in COMMUNITY_ZONES}

ID_PREFIXES = {
    "user": "USR",
    "item": "ITM",
    "request": "REQ",
    "transaction": "TXN",
    "review": "REV",
    "report": "RPT",
}
