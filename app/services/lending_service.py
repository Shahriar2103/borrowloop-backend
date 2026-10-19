"""Borrowing business rules shared by the API and the dataset generator."""
import copy
from datetime import timedelta

from ..constants import CONDITION_RANK, MAX_LOAN_DAYS
from ..models.common import build_condition_check
from ..models.transaction import payment_reference
from ..utils.helpers import iso, parse_dt
from ..utils.responses import ApiError


def due_deadline(return_date):
    """Return dates are calendar days; an item is due by 23:59:59 UTC on that day."""
    return parse_dt(return_date).replace(hour=23, minute=59, second=59)


def validate_request_dates(start_raw, return_raw, item, now, allow_past=False):
    start = parse_dt(start_raw, "start_date")
    end = parse_dt(return_raw, "return_date")
    start_d, end_d = start.date(), end.date()
    if not allow_past and start_d < now.date():
        raise ApiError("'start_date' cannot be in the past.", 422)
    if end_d <= start_d:
        raise ApiError("'return_date' must be after 'start_date'.", 422)
    rules = item.get("lending_rules", {})
    duration = (end_d - start_d).days
    min_days = rules.get("min_days", 1)
    max_days = min(rules.get("max_days", MAX_LOAN_DAYS), MAX_LOAN_DAYS)
    if duration < min_days or duration > max_days:
        raise ApiError(f"This item can be borrowed for {min_days}-{max_days} days (requested {duration}).", 422,
                       details={"min_days": min_days, "max_days": max_days, "requested_days": duration})
    advance = rules.get("max_advance_booking_days", 60)
    if not allow_past and (start_d - now.date()).days > advance:
        raise ApiError(f"Bookings can be made at most {advance} days in advance.", 422)
    return start_d.isoformat(), end_d.isoformat(), duration


def find_overlaps(db, item_id, start_date, return_date, statuses=("accepted",), exclude_request_id=None):
    """Requests on the same item whose [start, return] range intersects the given one."""
    query = {
        "item_id": item_id,
        "status": {"$in": list(statuses)},
        "start_date": {"$lte": return_date},
        "return_date": {"$gte": start_date},
    }
    if exclude_request_id:
        query["request_id"] = {"$ne": exclude_request_id}
    # accepted requests whose transaction is already completed no longer block the calendar
    results = []
    for r in db.borrow_requests.find(query):
        if r.get("transaction_id"):
            txn = db.transactions.find_one({"transaction_id": r["transaction_id"]}, {"status": 1})
            if txn and txn["status"] == "completed":
                continue
        results.append(r)
    return results


def assess_return(txn, item, returned_at, return_condition, *, damage_severity=None, notes=None,
                  actor_id=None, now=None):
    """Pure function. Returns (updated_transaction, item_set_fields)."""
    txn = copy.deepcopy(txn)
    now = now or returned_at
    returned_iso = iso(returned_at)
    pricing = item.get("pricing", {})
    grace_h = pricing.get("late_fee", {}).get("grace_period_hours", 6)
    per_day = pricing.get("late_fee", {}).get("per_day", txn["payment"]["late_fee"]["per_day"])
    deductions_cfg = pricing.get("deposit", {}).get("refund_policy", {}).get("deductions", {})

    deadline = due_deadline(txn["due_date"])
    overdue_seconds = (returned_at - deadline - timedelta(hours=grace_h)).total_seconds()
    days_late = max(0, int(-(-overdue_seconds // 86400))) if overdue_seconds > 0 else 0

    from_grade = txn["item_snapshot"]["condition_at_pickup"]
    degraded_by = CONDITION_RANK[return_condition] - CONDITION_RANK[from_grade]
    if damage_severity is None:
        if degraded_by >= 2:
            damage_severity = "major"
        elif degraded_by == 1 and return_condition in ("fair", "poor"):
            damage_severity = "minor"
        else:
            damage_severity = "none"

    deposit = txn["payment"]["deposit"]["amount"]
    late_cap = deductions_cfg.get("late_return", {}).get("max_total", deposit * 0.5)
    late_fee = round(min(days_late * per_day, late_cap), 2)
    damage_fee = round(deductions_cfg.get("damage", {}).get(damage_severity, 0.0) if damage_severity != "none" else 0.0, 2)
    total = round(min(deposit, late_fee + damage_fee), 2)
    refunded = round(deposit - total, 2)

    deposit_doc = txn["payment"]["deposit"]
    deposit_doc["deductions"] = {"late_fee": late_fee, "damage_fee": damage_fee, "total": total}
    deposit_doc["refunded_amount"] = refunded if deposit > 0 else None
    if deposit <= 0:
        deposit_doc["status"] = "not_required"
    elif total == 0:
        deposit_doc["status"] = "refunded"
    elif refunded > 0:
        deposit_doc["status"] = "partially_refunded"
    else:
        deposit_doc["status"] = "forfeited"
    if deposit > 0:
        if refunded > 0:
            deposit_doc["events"].append({"type": "refund", "amount": refunded, "at": returned_iso,
                                          "reference": {"provider": "stripe_test",
                                                        "id": payment_reference(txn["transaction_id"] + "refund")}})
        if total > 0:
            deposit_doc["events"].append({"type": "capture", "amount": total, "at": returned_iso,
                                          "reference": {"provider": "stripe_test",
                                                        "id": payment_reference(txn["transaction_id"] + "capture")}})
    txn["payment"]["late_fee"] = {"per_day": per_day, "days": days_late, "amount": late_fee}

    actor_id = actor_id or txn["lender_id"]
    txn["returned_at"] = returned_iso
    txn["return_condition"] = return_condition
    txn["status"] = "completed"
    txn["updated_at"] = iso(now)
    txn["handover"]["return"] = {
        "at": returned_iso,
        "method": txn["handover"]["pickup"]["method"],
        "location": txn["handover"]["pickup"].get("location"),
        "confirmations": {"lender": {"confirmed": True, "at": returned_iso},
                          "borrower": {"confirmed": True, "at": returned_iso}},
        "condition_check": build_condition_check(return_condition, notes=notes),
    }
    txn["return_assessment"] = {
        "on_time": days_late == 0,
        "days_late": days_late,
        "condition_change": {"from": from_grade, "to": return_condition, "degraded_by": max(0, degraded_by)},
        "damage": {"reported": damage_severity != "none", "severity": damage_severity, "description": notes},
        "assessed_by": actor_id,
    }
    txn["timeline"].append({"event": "item_returned", "at": returned_iso,
                            "actor": {"user_id": actor_id, "role": "lender"},
                            "meta": {"condition": return_condition, "days_late": days_late}})
    txn["timeline"].append({"event": "deposit_settled", "at": returned_iso,
                            "actor": {"user_id": "system", "role": "system"},
                            "meta": {"refunded": refunded, "deducted": total, "status": deposit_doc["status"]}})
    for reminder in txn.get("reminders", []):
        if reminder.get("scheduled_for") and reminder["scheduled_for"] <= returned_iso:
            reminder["sent"] = True

    item_set = {
        "condition": return_condition,
        "condition_report.grade": return_condition,
        "condition_report.summary": f"Returned in {return_condition.replace('_', ' ')} condition"
                                    + (f" ({damage_severity} damage)" if damage_severity != "none" else "") + ".",
        "condition_report.last_inspected_at": returned_iso,
        "availability_details.status": "available" if item.get("status") == "active" else "unavailable",
        "availability_details.current_transaction_id": None,
        "availability_details.next_available_from": returned_iso,
        "availability": item.get("status") == "active",
        "updated_at": iso(now),
    }
    inspection = {"at": returned_iso, "by": actor_id, "context": f"return:{txn['transaction_id']}",
                  "result": build_condition_check(return_condition, notes=notes)}
    return txn, item_set, inspection
