"""Review document builder.

Nesting example (5 levels): context.reviewer.trust_at_review.breakdown_hint.tier
                (4 levels): moderation.checks.automatic.toxicity_score
"""

ASPECTS = {
    "borrower_to_lender": ("communication", "item_accuracy", "punctuality"),
    "lender_to_borrower": ("communication", "care_of_item", "punctuality"),
}


def build_review(*, review_id, reviewer, reviewed_user, transaction, rating, comment, created_at,
                 direction, aspects=None, toxicity_score=0.02):
    aspects = aspects or {}
    aspect_doc = {}
    for name in ASPECTS[direction]:
        score = aspects.get(name, rating)
        aspect_doc[name] = {"score": int(score), "weight": round(1 / len(ASPECTS[direction]), 3)}
    assessment = transaction.get("return_assessment") or {}
    return {
        "review_id": review_id,
        "reviewer_id": reviewer["user_id"],
        "reviewed_user_id": reviewed_user["user_id"],
        "item_id": transaction["item_id"],
        "rating": int(rating),
        "comment": comment,
        "created_at": created_at,
        "updated_at": created_at,
        "transaction_id": transaction["transaction_id"],
        "direction": direction,
        "ratings": {"overall": int(rating), "aspects": aspect_doc},
        "context": {
            "item": {"name": transaction["item_snapshot"]["name"],
                     "category": transaction["item_snapshot"]["category"]},
            "transaction": {
                "borrowed_at": transaction["borrowed_at"],
                "returned_at": transaction["returned_at"],
                "outcome": {"on_time": assessment.get("on_time"), "days_late": assessment.get("days_late"),
                            "damage": (assessment.get("damage") or {}).get("severity")},
            },
            "reviewer": {
                "name": reviewer["name"],
                "role_in_transaction": "borrower" if direction == "borrower_to_lender" else "lender",
                "trust_at_review": {"score": reviewer.get("trust_score"),
                                    "breakdown_hint": {"tier": reviewer.get("trust_profile", {}).get("tier")}},
            },
        },
        "moderation": {
            "status": "published",
            "flags": [],
            "checks": {
                "automatic": {"toxicity_score": toxicity_score, "passed": toxicity_score < 0.7,
                              "checked_at": created_at},
                "manual": {"by": None, "at": None, "decision": None},
            },
        },
        "response": None,
        "engagement": {"helpful": {"count": 0, "voters": []}},
    }
