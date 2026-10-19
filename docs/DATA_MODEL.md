# BorrowLoop data model

Six MongoDB collections. Every document keeps the flat fields from the project specification at the top level (so filtering and indexing stay simple) and carries richer nested sub-documents underneath.

| Collection | Documents in seed | Max nesting depth | Example deep paths |
|---|---|---|---|
| `users` | 64 | 6 levels | `profile.location.community.zone.code`<br>`preferences.notifications.events.return_reminders.schedule.days_before_due`<br>`trust_profile.breakdown.return_reliability.details.on_time` |
| `items` | 113 | 6 levels | `details.specifications.technical.<spec>.<value>`<br>`pricing.deposit.refund_policy.deductions.damage.major`<br>`pickup.location.community.zone.code` |
| `borrow_requests` | 614 | 7 levels | `negotiation.thread[].proposal.terms.pickup.window.from`<br>`logistics.pickup.location.community.zone.code`<br>`item_snapshot.owner.trust.score` |
| `transactions` | 399 | 6 levels | `handover.pickup.condition_check.checklist.cosmetic.score`<br>`payment.deposit.events[].reference.provider`<br>`payment.deposit.deductions.late_fee` |
| `reviews` | 524 | 5 levels | `context.reviewer.trust_at_review.breakdown_hint.tier`<br>`moderation.checks.automatic.toxicity_score`<br>`ratings.aspects.communication.score` |
| `reports` | 21 | 5 levels | `sla.escalation.policy.hours.first_response`<br>`resolution.effects.trust.penalty_applied.points`<br>`evidence.attachments[].meta.size_kb` |

All timestamps are ISO-8601 UTC strings (`2026-10-18T14:30:00Z`); booking dates (`start_date`, `return_date`, `due_date`) are calendar days (`2026-10-21`).
IDs are human-readable and sequential: `USR-00001`, `ITM-00001`, `REQ-00001`, `TXN-00001`, `REV-00001`, `RPT-00001`.

## Relationships

```
users 1 ──< items                (items.owner_id)
users 1 ──< borrow_requests      (borrower_id, owner_id)
items 1 ──< borrow_requests      (item_id)
borrow_requests 1 ── 0..1 transactions   (transactions.request_id, borrow_requests.transaction_id)
transactions 1 ──< reviews       (max one per reviewer, i.e. up to two per transaction)
reports >── user | item | transaction | review   (target.type + target.id)
```

Full example documents for every collection are in [`docs/sample_documents/`](sample_documents/).

## `users`

Deep paths: `profile.location.community.zone.code`, `preferences.notifications.events.return_reminders.schedule.days_before_due`, `trust_profile.breakdown.return_reliability.details.on_time`, `verification.identity.document.check.method`, `account.login_history[].device.browser.name`

```yaml
user_id: string
name: string
email: string
password_hash: string
role: string
trust_score: number
created_at: string
updated_at: string
profile:
  display_name: string
  bio: string
  avatar:
    url: string
    variants:
      small:
        url: string
        width: number
        height: number
      large:
        url: string
        width: number
        height: number
  contact:
    phone:
      number: string
      country_code: string
      verified: boolean
    preferred_method: string
  location:
    address:
      line1: string
      city: string
      postcode: string
      country: string
    geo:
      type: string
      coordinates: [ number ]
    community:
      neighbourhood: string
      borough: string
      zone:
        code: string
        name: string
        radius_km: number
  interests: [ string ]
preferences:
  notifications:
    channels:
      email:
        enabled: boolean
        frequency: string
      push:
        enabled: boolean
        quiet_hours:
          from: string
          to: string
      sms:
        enabled: boolean
    events:
      borrow_requests:
        enabled: boolean
        channels: [ string ]
      request_updates:
        enabled: boolean
        channels: [ string ]
      return_reminders:
        enabled: boolean
        channels: [ string ]
        schedule:
          days_before_due: number
          time_of_day: string
      reviews:
        enabled: boolean
        channels: [ string ]
  privacy:
    profile_visibility: string
    show_location: string
    show_phone: boolean
  lending:
    auto_decline_below_trust: number | null
    max_concurrent_loans: number
    default_deposit:
      amount: number
      currency: string
verification:
  level: string
  email:
    verified: boolean
    verified_at: string | null
  phone:
    verified: boolean
    verified_at: string | null
  identity:
    status: string
    document:
      type: string | null
      country: string | null
      check:
        method: string | null
        by: string | null
        at: string | null
trust_profile:
  score: number
  tier: string
  last_calculated: string
  breakdown:
    return_reliability:
      value: number
      weight: number
      points: number
      details:
        completed_borrows: number
        on_time: number
        late: number
        damaged: number
        late_cancellations: number
    review_rating:
      value: number
      weight: number
      points: number
      details:
        reviews: number
        raw_average: number | null
        smoothed_average: number
    account_standing:
      value: number
      weight: number
      points: number
      details:
        email_verified: boolean
        phone_verified: boolean
        identity_status: string
        account_status: string
    lending_reliability:
      value: number
      weight: number
      points: number
      details:
        completed_loans: number
        lender_cancellations: number
    experience:
      value: number
      weight: number
      points: number
      details:
        completed_transactions: number
        account_age_days: number
    conduct_penalty:
      value: null
      weight: null
      points: number
      details:
        upheld_reports: number
        points_per_report: number
  summary:
    completed_borrows: number
    completed_loans: number
    reviews_received: number
    average_rating: number | null
  history: [ {
      at: string
      score: number
      change: number | null
      reason: string
    } ]
stats:
  borrowing:
    total_requests: number
    completed: number
    active: number
    late_returns: number
    on_time_rate: number | null
    categories:
      electronics: number
      sports_outdoor: number
      books: number
      music: number
      tools: number
      gaming: number
      party_events: number
      kitchen: number
      garden: number
      baby_kids: number
  lending:
    items_listed: number
    requests_received: number
    completed: number
    active: number
    acceptance_rate: number | null
    total_days_lent: number
  reviews:
    received:
      count: number
      average: number | null
      distribution:
        1: number
        2: number
        3: number
        4: number
        5: number
    given:
      count: number
account:
  status: string
  last_login_at: string
  login_history: [ {
      at: string
      ip: string
      device:
        type: string
        os:
          name: string
        browser:
          name: string
          user_agent: string
    } ]
  badges: [ {
      code: string
      label: string
      awarded_at: string
    } ]
  moderation:
    warnings: [ {
        at: string
        by: string
        report_id: string
        reason: string
      } ]
    suspension: (or null)
      status: string
      at: string
      by: string
      report_id: string
      until: string
```

## `items`

Deep paths: `details.specifications.technical.<spec>.<value>`, `pricing.deposit.refund_policy.deductions.damage.major`, `pickup.location.community.zone.code`, `condition_report.inspections[].result.checklist.cosmetic.score`, `media.images[].variants.thumb.url`

```yaml
item_id: string
owner_id: string
name: string
category: string
description: string
condition: string
availability: boolean
deposit: number
created_at: string
updated_at: string
status: string
taxonomy:
  category:
    key: string
    label: string
  subcategory:
    key: string
    label: string
  type: string
  tags: [ string ]
  attributes:
    <attribute>: string
details:
  brand: string
  model: string
  year: number
  specifications:
    technical:
      <group>:
        <spec>: string
    physical:
      dimensions_cm:
        length: number
        width: number
        height: number
      weight_kg: number
      colour: string
  included_accessories: [ {
      name: string
      quantity: number
    } ]
condition_report:
  grade: string
  summary: string
  last_inspected_at: string
  inspections: [ {
      at: string
      by: string
      context: string
      result:
        grade: string
        checklist:
          cosmetic:
            score: number
            notes: string | null
          functional:
            score: number
            notes: null
          completeness:
            complete: boolean
            missing: [ any ]
        photos: [ any ]
    } ]
pricing:
  deposit:
    amount: number
    currency: string
    refund_policy:
      type: string
      processing_days: number
      deductions:
        late_return:
          per_day: number
          max_total: number
        damage:
          minor: number
          major: number
  late_fee:
    per_day: number
    grace_period_hours: number
    currency: string
lending_rules:
  min_days: number
  max_days: number
  min_trust_score: number
  requires_id_verification: boolean
  max_advance_booking_days: number
availability_details:
  status: string
  current_transaction_id: string | null
  next_available_from: string
  calendar:
    booked: [ {
        request_id: string
        from: string
        to: string
        status: string
      } ]
    blocked: [ {
        from: string
        to: string
        reason: string
      } ]
pickup:
  methods: [ string ]
  location:
    community:
      neighbourhood: string
      borough: string
      zone:
        code: string
        name: string
        radius_km: number
    geo:
      type: string
      coordinates: [ number ]
  schedule:
    weekdays:
      slots: [ {
          from: string
          to: string
        } ]
    weekends:
      slots: [ {
          from: string
          to: string
        } ]
media:
  cover_index: number
  images: [ {
      url: string
      alt: string
      variants:
        thumb:
          url: string
          width: number
          height: number
        full:
          url: string
          width: number
          height: number
      uploaded_at: string
    } ]
stats:
  views: number
  times_borrowed: number
  total_days_lent: number
  last_borrowed_at: string | null
  rating:
    average: number | null
    count: number
    distribution:
      1: number
      2: number
      3: number
      4: number
      5: number
moderation:
  status: string
  flags: [ {
      report_id: string
      reason: string
      at: string
    } ]
  review:
    by: string | null
    at: string | null
    decision: string | null
```

## `borrow_requests`

Deep paths: `negotiation.thread[].proposal.terms.pickup.window.from`, `logistics.pickup.location.community.zone.code`, `item_snapshot.owner.trust.score`, `status_history[].by.user_id`, `decision.auto.rule`

```yaml
request_id: string
item_id: string
borrower_id: string
owner_id: string
start_date: string
return_date: string
status: string
created_at: string
updated_at: string
duration_days: number
message: string | null
item_snapshot:
  name: string
  category: string
  condition: string
  deposit:
    amount: number
    currency: string
  owner:
    user_id: string
    name: string
    trust:
      score: number
      tier: string
borrower_snapshot:
  name: string
  trust:
    score: number
    tier: string
  verification:
    level: string
  community:
    neighbourhood: string
    borough: string
    zone:
      code: string
      name: string
      radius_km: number
logistics:
  pickup:
    method: string
    location:
      community:
        neighbourhood: string
        borough: string
        zone:
          code: string
          name: string
          radius_km: number
      geo:
        type: string
        coordinates: [ number ]
    scheduled:
      date: string
      window:
        from: string
        to: string
  return:
    method: string
    location:
      community:
        neighbourhood: string
        borough: string
        zone:
          code: string
          name: string
          radius_km: number
      geo:
        type: string
        coordinates: [ number ]
    scheduled:
      date: string
      window:
        from: string
        to: string
negotiation:
  rounds: number
  thread: [ {
      message_id: string
      sender_id: string
      sent_at: string
      body: string | null
      proposal:
        start_date: string
        return_date: string
        terms:
          deposit:
            amount: number
            currency: string
          pickup:
            method: string
            window:
              from: string
              to: string
    } ]
status_history: [ {
    status: string
    at: string
    by:
      user_id: string
      role: string
    note: string
  } ]
decision: (or null)
  by: string
  at: string
  reason: string | null
  auto:
    triggered: boolean
    rule: null
cancellation: (or null)
  by: string
  role: string
  at: string
  reason: string
  after_acceptance: boolean
transaction_id: string | null
```

## `transactions`

Deep paths: `handover.pickup.condition_check.checklist.cosmetic.score`, `payment.deposit.events[].reference.provider`, `payment.deposit.deductions.late_fee`, `parties.borrower.trust_at_start.tier`, `return_assessment.condition_change.degraded_by`

```yaml
transaction_id: string
request_id: string
borrowed_at: string
returned_at: string | null
return_condition: string | null
status: string
created_at: string
updated_at: string
item_id: string
lender_id: string
borrower_id: string
due_date: string
parties:
  lender:
    user_id: string
    name: string
    trust_at_start:
      score: number
      tier: string
  borrower:
    user_id: string
    name: string
    trust_at_start:
      score: number
      tier: string
item_snapshot:
  name: string
  category: string
  condition_at_pickup: string
handover:
  pickup:
    at: string
    method: string
    location:
      community:
        neighbourhood: string
        borough: string
        zone:
          code: string
          name: string
          radius_km: number
      geo:
        type: string
        coordinates: [ number ]
    confirmations:
      lender:
        confirmed: boolean
        at: string
      borrower:
        confirmed: boolean
        at: string
    condition_check:
      grade: string
      checklist:
        cosmetic:
          score: number
          notes: null
        functional:
          score: number
          notes: null
        completeness:
          complete: boolean
          missing: [ any ]
      photos: [ any ]
  return: (or null)
    at: string
    method: string
    location:
      community:
        neighbourhood: string
        borough: string
        zone:
          code: string
          name: string
          radius_km: number
      geo:
        type: string
        coordinates: [ number ]
    confirmations:
      lender:
        confirmed: boolean
        at: string
      borrower:
        confirmed: boolean
        at: string
    condition_check:
      grade: string
      checklist:
        cosmetic:
          score: number
          notes: string | null
        functional:
          score: number
          notes: null
        completeness:
          complete: boolean
          missing: [ any ]
      photos: [ any ]
return_assessment: (or null)
  on_time: boolean
  days_late: number
  condition_change:
    from: string
    to: string
    degraded_by: number
  damage:
    reported: boolean
    severity: string
    description: string | null
  assessed_by: string
payment:
  currency: string
  deposit:
    amount: number
    status: string
    events: [ {
        type: string
        amount: number
        at: string
        reference:
          provider: string
          id: string
      } ]
    deductions:
      late_fee: number
      damage_fee: number
      total: number
    refunded_amount: number | null
  late_fee:
    per_day: number
    days: number
    amount: number
timeline: [ {
    event: string
    at: string
    actor:
      user_id: string
      role: string
    meta:
      request_id: string
      condition: string
      deposit:
        amount: number
        currency: string
      days_late: number
      refunded: number
      deducted: number
      status: string
  } ]
reminders: [ {
    type: string
    channel: string
    scheduled_for: string
    sent: boolean
  } ]
dispute:
  open: boolean
  report_id: string | null
```

## `reviews`

Deep paths: `context.reviewer.trust_at_review.breakdown_hint.tier`, `moderation.checks.automatic.toxicity_score`, `ratings.aspects.communication.score`, `context.transaction.outcome.days_late`, `engagement.helpful.voters[]`

```yaml
review_id: string
reviewer_id: string
reviewed_user_id: string
item_id: string
rating: number
comment: string
created_at: string
updated_at: string
transaction_id: string
direction: string
ratings:
  overall: number
  aspects:
    communication:
      score: number
      weight: number
    care_of_item:
      score: number
      weight: number
    punctuality:
      score: number
      weight: number
    item_accuracy:
      score: number
      weight: number
context:
  item:
    name: string
    category: string
  transaction:
    borrowed_at: string
    returned_at: string
    outcome:
      on_time: boolean
      days_late: number
      damage: string
  reviewer:
    name: string
    role_in_transaction: string
    trust_at_review:
      score: number
      breakdown_hint:
        tier: string
moderation:
  status: string
  flags: [ {
      by: string
      reason: string
      at: string
    } ]
  checks:
    automatic:
      toxicity_score: number
      passed: boolean
      checked_at: string
    manual:
      by: string | null
      at: string | null
      decision: string | null
response: (or null)
  comment: string
  at: string
engagement:
  helpful:
    count: number
    voters: [ string ]
```

## `reports`

Deep paths: `sla.escalation.policy.hours.first_response`, `resolution.effects.trust.penalty_applied.points`, `evidence.attachments[].meta.size_kb`, `activity_log[].changes.status.to`, `target.snapshot.trust_score`

```yaml
report_id: string
reporter_id: string
target:
  type: string
  id: string
  snapshot:
    item: string
    lender_id: string
    borrower_id: string
    status: string
    reviewer_id: string
    reviewed_user_id: string
    rating: number
    comment: string
    name: string
    role: string
    trust_score: number
    category: string
    owner_id: string
reason:
  category: string
  subcategory: string
  description: string
evidence:
  attachments: [ {
      url: string
      type: string
      uploaded_at: string
      meta:
        size_kb: number
        mime: string
    } ]
  related:
    transaction_id: string
    request_id: string
status: string
priority: string
sla:
  first_response_due: string
  escalation:
    level: number
    policy:
      name: string
      hours:
        first_response: number
        resolution: number
assigned_to: string | null
resolution: (or null)
  action: string
  notes: string
  by: string
  at: string
  effects:
    user: (or null)
      user_id: string
      action: string
    item: (or null)
      item_id: string
      action: string
    review: (or null)
      review_id: string
      action: string
    trust: null
activity_log: [ {
    at: string
    by:
      user_id: string
      role: string
    action: string
    note: string
    changes:
      status:
        from: string | null
        to: string
      assigned_to:
        from: null
        to: string
  } ]
created_at: string
updated_at: string
```
