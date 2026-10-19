"""Report (moderation case) document builder.

Nesting example (5 levels): sla.escalation.policy.hours.first_response
                (5 levels): resolution.effects.trust.penalty_applied.points
                (4 levels): evidence.attachments[].meta.size_kb
"""


from datetime import datetime, timedelta

SLA_HOURS = {
    "low": {"first_response": 72, "resolution": 240},
    "medium": {"first_response": 24, "resolution": 120},
    "high": {"first_response": 8, "resolution": 48},
    "critical": {"first_response": 2, "resolution": 24},
}


def _plus_hours(ts, hours):
    dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ") + timedelta(hours=hours)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_report(*, report_id, reporter, target_type, target_id, target_snapshot, category, subcategory,
                 description, created_at, attachments=None, related=None, priority="medium"):
    report = {
        "report_id": report_id,
        "reporter_id": reporter["user_id"],
        "target": {"type": target_type, "id": target_id, "snapshot": target_snapshot},
        "reason": {"category": category, "subcategory": subcategory, "description": description},
        "evidence": {
            "attachments": [
                {"url": url, "type": "image", "uploaded_at": created_at,
                 "meta": {"size_kb": 180 + i * 37, "mime": "image/jpeg"}}
                for i, url in enumerate(attachments or [])
            ],
            "related": related or {},
        },
        "status": "open",
        "priority": priority,
        "sla": {
            "first_response_due": None,
            "escalation": {
                "level": 0,
                "policy": {"name": priority, "hours": SLA_HOURS[priority]},
            },
        },
        "assigned_to": None,
        "resolution": None,
        "activity_log": [
            {"at": created_at, "by": {"user_id": reporter["user_id"], "role": reporter["role"]},
             "action": "created", "note": "Report submitted", "changes": {"status": {"from": None, "to": "open"}}}
        ],
        "created_at": created_at,
        "updated_at": created_at,
    }
    report["sla"]["first_response_due"] = _plus_hours(created_at, SLA_HOURS[priority]["first_response"])
    return report
