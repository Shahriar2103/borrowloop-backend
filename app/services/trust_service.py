"""Trust Score engine (0-100).

Five weighted components, each scored 0..1:

  return_reliability  35%  on-time, undamaged returns as a borrower (late / damage / late cancellations penalised)
  review_rating       30%  Bayesian-smoothed average rating received (prior 3.5 stars, weight 3)
  account_standing    15%  email / phone / identity verification
  lending_reliability 10%  completed loans as a lender vs. lender-side cancellations after acceptance
  experience          10%  number of completed transactions and account age

Then: -6 points per upheld report (warning / suspension / ban, max -30), and the score is
capped at 40 while an account is suspended or banned.

Components with no history start from a neutral prior so new members begin around 55-60
instead of 0, and the score moves as real evidence accumulates.
"""
from datetime import datetime, timezone

WEIGHTS = {
    "return_reliability": 0.35,
    "review_rating": 0.30,
    "account_standing": 0.15,
    "lending_reliability": 0.10,
    "experience": 0.10,
}
NEUTRAL = 0.7
TIERS = ((85, "platinum"), (72, "gold"), (58, "silver"), (45, "bronze"), (0, "at_risk"))
UPHELD_ACTIONS = ("warning", "suspend_user", "ban_user")
SUSPENDED_CAP = 40.0
CONDUCT_PENALTY_PER_REPORT = 6.0
MAX_CONDUCT_PENALTY = 30.0


def tier_for(score, completed_transactions):
    if completed_transactions == 0:
        return "new"
    for threshold, name in TIERS:
        if score >= threshold:
            return name
    return "at_risk"


def _parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None


def _return_event_score(txn):
    assessment = txn.get("return_assessment") or {}
    days_late = assessment.get("days_late") or 0
    severity = (assessment.get("damage") or {}).get("severity", "none")
    if days_late <= 0:
        score = 1.0
    elif days_late <= 3:
        score = 0.4
    else:
        score = 0.0
    score -= {"none": 0.0, "minor": 0.3, "major": 0.6}.get(severity, 0.0)
    return max(0.0, score)


def compute_trust_profile(user, *, borrowed, lent, reviews_received, lender_cancellations=0,
                          borrower_late_cancellations=0, upheld_reports=0, now=None):
    """Pure function: compute the trust profile from already-loaded history."""
    now = now or datetime.now(timezone.utc)

    # 1. return reliability (as borrower)
    events = [_return_event_score(t) for t in borrowed] + [0.3] * borrower_late_cancellations
    on_time = sum(1 for t in borrowed if ((t.get("return_assessment") or {}).get("days_late") or 0) <= 0)
    late = len(borrowed) - on_time
    damaged = sum(1 for t in borrowed
                  if ((t.get("return_assessment") or {}).get("damage") or {}).get("severity", "none") != "none")
    prior_w = 1
    return_value = (sum(events) + NEUTRAL * prior_w) / (len(events) + prior_w)

    # 2. review rating (Bayesian average)
    ratings = [r["rating"] for r in reviews_received]
    smoothed = (sum(ratings) + 3.5 * 3) / (len(ratings) + 3)
    review_value = (smoothed - 1) / 4

    # 3. account standing
    verification = user.get("verification", {})
    standing = 0.0
    standing += 0.4 if verification.get("email", {}).get("verified") else 0.0
    standing += 0.3 if verification.get("phone", {}).get("verified") else 0.0
    standing += 0.3 if verification.get("identity", {}).get("status") == "verified" else 0.0
    if user.get("account", {}).get("status") != "active":
        standing = 0.0
    standing = max(0.0, min(1.0, standing))

    # 4. lending reliability
    lending_value = (len(lent) + NEUTRAL * prior_w) / (len(lent) + lender_cancellations + prior_w)

    # 5. experience
    completed_total = len(borrowed) + len(lent)
    created = _parse(user.get("created_at")) or now
    age_days = max(0, (now - created).days)
    experience_value = 0.7 * min(1.0, completed_total / 20) + 0.3 * min(1.0, age_days / 365)

    values = {
        "return_reliability": return_value,
        "review_rating": review_value,
        "account_standing": standing,
        "lending_reliability": lending_value,
        "experience": experience_value,
    }
    details = {
        "return_reliability": {"completed_borrows": len(borrowed), "on_time": on_time, "late": late,
                               "damaged": damaged, "late_cancellations": borrower_late_cancellations},
        "review_rating": {"reviews": len(ratings),
                          "raw_average": round(sum(ratings) / len(ratings), 2) if ratings else None,
                          "smoothed_average": round(smoothed, 2)},
        "account_standing": {"email_verified": verification.get("email", {}).get("verified", False),
                             "phone_verified": verification.get("phone", {}).get("verified", False),
                             "identity_status": verification.get("identity", {}).get("status"),
                             "account_status": user.get("account", {}).get("status")},
        "lending_reliability": {"completed_loans": len(lent), "lender_cancellations": lender_cancellations},
        "experience": {"completed_transactions": completed_total, "account_age_days": age_days},
    }
    breakdown = {}
    total = 0.0
    for name, weight in WEIGHTS.items():
        weighted = values[name] * weight * 100
        total += weighted
        breakdown[name] = {"value": round(values[name], 3), "weight": weight,
                           "points": round(weighted, 2), "details": details[name]}
    penalty = min(MAX_CONDUCT_PENALTY, CONDUCT_PENALTY_PER_REPORT * upheld_reports)
    total -= penalty
    breakdown["conduct_penalty"] = {"value": None, "weight": None, "points": -penalty,
                                    "details": {"upheld_reports": upheld_reports,
                                                "points_per_report": CONDUCT_PENALTY_PER_REPORT}}
    if user.get("account", {}).get("status", "active") != "active":
        total = min(total, SUSPENDED_CAP)  # suspended / banned members are always 'at risk'
    score = round(max(0.0, min(100.0, total)), 1)
    return {
        "score": score,
        "tier": tier_for(score, completed_total),
        "last_calculated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "breakdown": breakdown,
        "summary": {
            "completed_borrows": len(borrowed),
            "completed_loans": len(lent),
            "reviews_received": len(ratings),
            "average_rating": details["review_rating"]["raw_average"],
        },
    }


def gather_and_compute(db, user, now=None):
    uid = user["user_id"]
    borrowed = list(db.transactions.find({"borrower_id": uid, "status": "completed"}))
    lent = list(db.transactions.find({"lender_id": uid, "status": "completed"}))
    reviews = list(db.reviews.find({"reviewed_user_id": uid, "moderation.status": "published"}))
    lender_cancellations = db.borrow_requests.count_documents(
        {"owner_id": uid, "status": "cancelled", "cancellation.role": "lender", "cancellation.after_acceptance": True})
    borrower_late = db.borrow_requests.count_documents(
        {"borrower_id": uid, "status": "cancelled", "cancellation.role": "borrower", "cancellation.after_acceptance": True})
    upheld = db.reports.count_documents(
        {"target.type": "user", "target.id": uid, "status": "resolved", "resolution.action": {"$in": list(UPHELD_ACTIONS)}})
    return compute_trust_profile(user, borrowed=borrowed, lent=lent, reviews_received=reviews,
                                 lender_cancellations=lender_cancellations,
                                 borrower_late_cancellations=borrower_late, upheld_reports=upheld, now=now)


def recalculate_trust(db, user_id, reason="recalculated", now=None):
    """Recompute and persist trust_score + trust_profile (keeps the last 25 history points)."""
    user = db.users.find_one({"user_id": user_id})
    if not user:
        return None
    profile = gather_and_compute(db, user, now=now)
    history = list(user.get("trust_profile", {}).get("history", []))
    previous = user.get("trust_score")
    if previous != profile["score"] or not history:
        history.append({"at": profile["last_calculated"], "score": profile["score"],
                        "change": round(profile["score"] - previous, 1) if previous is not None else None,
                        "reason": reason})
    profile["history"] = history[-25:]
    db.users.update_one({"user_id": user_id}, {"$set": {"trust_score": profile["score"], "trust_profile": profile}})
    return profile
