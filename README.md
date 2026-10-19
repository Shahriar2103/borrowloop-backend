# BorrowLoop – Backend API

Community item lending and resource-sharing platform. **Flask + MongoDB REST API** with JWT authentication,
a Trust Score engine, admin moderation and a large, deeply nested seed dataset.

---

## 1. Run it in VS Code (about 2 minutes)

**You need:** Python **3.10 or newer** ([python.org](https://www.python.org/downloads/)) and VS Code with the Python extension.
MongoDB is **optional**: if it isn't running, the API automatically uses a built-in in-memory database loaded with the full dataset.

1. Unzip the folder and open it in VS Code: **File → Open Folder… → `borrowloop-backend`**.
2. Open a terminal (**Terminal → New Terminal**) and run:

   **Windows (PowerShell)**
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   python run.py
   ```
   **macOS / Linux**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   python run.py
   ```
   > On Windows, if activation is blocked, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.
3. Open <http://127.0.0.1:5000/api/health>. You should see `"status": "ok"` and the collection counts.

You can also press **F5** and pick **"BorrowLoop: Run API"** (after selecting the `.venv` interpreter with
**Ctrl/Cmd+Shift+P → Python: Select Interpreter**). Other launch options: *Seed MongoDB*, *Regenerate dataset*, *Run tests*.

> **macOS note:** if port 5000 is taken by AirPlay Receiver, set `PORT=5001` in `.env`.

### Demo accounts

| Role | Email | Password | Good for testing |
|---|---|---|---|
| Admin | `admin@borrowloop.com` | `Admin@123` | all `/api/admin/*` endpoints |
| Admin | `moderator@borrowloop.com` | `Admin@123` | second moderator |
| Lender | `lender@borrowloop.com` | `Password@123` | has pending requests waiting for a decision |
| Borrower | `borrower@borrowloop.com` | `Password@123` | has an accepted request starting tomorrow (ready to collect) and a completed loan to review |

All other 60 seeded members use the password `Password@123` (emails are in `data/seed/users.json`).

### Try the API

* **VS Code REST Client:** install the recommended *REST Client* extension, open **`api.http`**, run the three login requests,
  then click **Send Request** on anything. The requests are ordered as a complete borrowing flow and use real IDs from the dataset.
* **Postman:** import **`docs/BorrowLoop.postman_collection.json`**, then run the three *Login as …* requests. They save tokens automatically.

---

## 2. Database modes

Set `DB_MODE` in `.env`:

| `DB_MODE` | Behaviour |
|---|---|
| `auto` *(default)* | Uses MongoDB at `MONGO_URI` if it is running; otherwise falls back to the in-memory database. |
| `mongo` | Requires a real MongoDB server; startup fails with a clear message if it is not reachable. |
| `mock` | Always uses the in-memory database (data resets every restart). |

**Using a real MongoDB** (Community Server, Docker or Atlas):

```bash
# local server or Docker:  docker run -d -p 27017:27017 --name mongo mongo:7
# Atlas: put your connection string in .env ->  MONGO_URI=mongodb+srv://user:pass@cluster.xxxxx.mongodb.net
python run.py                               # auto-seeds the empty database on first start
flask --app run seed-db --drop              # wipe and reload the dataset at any time
```

Seed dates are **shifted to be relative to today** when they load, so "active", "overdue" and "upcoming" records stay
realistic whenever you run the project. Browse the data with the *MongoDB for VS Code* extension (`mongodb://localhost:27017`).

---

## 3. API reference

Base URL `http://127.0.0.1:5000/api`. Protected routes need `Authorization: Bearer <access_token>` (from register or login).

**Response envelope**
```json
{ "success": true, "message": "Item listed.", "data": { }, "meta": { "page": 1, "per_page": 20, "total": 92, "pages": 5 } }
{ "success": false, "error": { "code": "validation_error", "message": "'deposit' must be a number.", "details": { } } }
```
Status codes used: `200` OK, `201` Created, `400` bad JSON, `401` not logged in / bad token, `403` not allowed,
`404` not found, `409` conflict (e.g. dates already booked), `422` validation error.

Lists accept `?page=` and `?per_page=` (max 100). Many accept `?sort=field` or `?sort=-field` (descending).

### Guest (no token)
| Method | Endpoint | Notes |
|---|---|---|
| POST | `/auth/register` | `name, email, password` (+ `role` borrower/lender, `neighbourhood`, `phone`, `bio`, `interests[]`) |
| POST | `/auth/login` | `email, password` → `access_token` |
| GET | `/items` | Available items. `?category=&sort=-rating\|deposit\|popularity\|created_at&view=full` |
| GET | `/items/<id>` | Full nested item + owner summary and booked dates |
| GET | `/items/search` | `?name=` (also matches description, tags and brand), `category=` (comma list), `subcategory=`, `available=true\|false\|all`, `condition=`, `min_deposit=`, `max_deposit=`, `neighbourhood=`, `zone=`, `owner_id=` |

### Logged-in user
| Method | Endpoint | Notes |
|---|---|---|
| GET | `/auth/me` | Current account (private view) |
| GET | `/users/<id>` | Public profile (private fields only for yourself or an admin) |
| PUT | `/users/<id>` | `name, bio, phone, neighbourhood, address_line1, interests, preferences{…}` (deep-merged), `current_password + new_password` |
| GET | `/users/<id>/trust-score` | Score, tier, 5-component breakdown, history |
| GET | `/users/<id>/items` | A member's listings |
| POST | `/items` | `name, category, description, condition, deposit` (+ `subcategory, tags, brand, model, specifications{}, lending_rules{min_days,max_days,min_trust_score,requires_id_verification}, pickup_methods[], images[], late_fee_per_day, neighbourhood`) |
| PUT | `/items/<id>` | Owner only. Any of the above + `status` (active/paused), `availability` |
| DELETE | `/items/<id>` | Owner only. Soft delete; open requests are cancelled. Blocked while on loan |
| POST | `/borrow-requests` | `item_id, start_date, return_date` (YYYY-MM-DD) + `message, pickup_method` |
| GET | `/borrow-requests` | `?role=borrower\|lender\|all&status=pending,accepted&item_id=` |
| GET | `/borrow-requests/<id>` | Borrower, owner or admin |
| PUT | `/borrow-requests/<id>` | Owner: `{"status":"accepted"}` or `{"status":"rejected","reason":…}`. Borrower: new `start_date/return_date/message` while pending. Either: `{"status":"cancelled"}` |
| DELETE | `/borrow-requests/<id>` | Borrower cancels (pending or accepted, before collection) |
| POST | `/transactions` | `request_id` (+ `condition, notes`). Records collection; request must be accepted |
| GET | `/transactions` | Active loans (`?role=`). Each includes `is_overdue` and `days_overdue` |
| GET | `/transactions/history` | Completed loans |
| GET | `/transactions/<id>` | Borrower, lender or admin |
| PUT | `/transactions/<id>` | Lender records the return: `return_condition` (+ `damage_severity` none/minor/major, `notes`, `returned_at`) |
| POST | `/reviews` | `transaction_id, rating` 1–5 (+ `comment`, `aspects{communication, punctuality, item_accuracy\|care_of_item}`) |
| GET | `/reviews/<user_id>` | `?as=lender\|borrower`; `meta.summary` holds the rating distribution |
| POST | `/reviews/<id>/response` | Reviewed member replies once |
| POST | `/reviews/<id>/helpful` | Upvote a review |
| POST | `/reports` | `target_type` (user/item/transaction/review), `target_id, category, subcategory, description` |
| GET | `/reports/mine` | Reports you submitted |

### Admin
| Method | Endpoint | Notes |
|---|---|---|
| GET | `/admin/users` | `?role=&status=&tier=&q=&neighbourhood=&sort=-trust_score` |
| DELETE | `/admin/users/<id>` | Removes the account, delists their items, cancels open requests (`?force=true` if they have active loans) |
| GET | `/admin/items` | `?status=&category=&owner_id=&flagged=true&available=` |
| DELETE | `/admin/items/<id>` | Body `{"reason": …}`; soft by default, `?hard=true` deletes permanently |
| GET | `/admin/transactions` | `?status=&user_id=&item_id=&overdue=true&late=true&disputed=true` |
| GET | `/admin/reports` | `?status=open,under_review&priority=&target_type=&category=` |
| GET | `/admin/reports/<id>` | Full report with activity log |
| PUT | `/admin/reports/<id>` | `status, priority, assigned_to, note`; resolve with `resolution{action: none\|warning\|suspend_user\|ban_user\|remove_item\|hide_review, notes, suspension_days, user_id}` |
| GET | `/admin/analytics` | Users, items, requests, transactions, deposits, reviews, reports, 12-month activity, leaderboards |

Reference data: `GET /api/categories`, `GET /api/communities`, `GET /api` (lists every route).

---

## 4. Business rules

* **Dates:** start can't be in the past or more than 60 days ahead; the loan length must fit the item's `min_days`–`max_days`.
* **No double booking:** a request can't overlap an accepted booking. Accepting one request **auto-rejects** pending requests for overlapping dates.
* **Eligibility:** borrowers below an item's `min_trust_score` get `403 trust_too_low`; some items need a verified identity; owners can auto-decline below a trust threshold (`preferences.lending.auto_decline_below_trust`).
* **Collection:** from one day before the start date until the return date; marks the item `on_loan` and holds the deposit.
* **Return:** the lender records it. Due by 23:59 on the return date plus a 6-hour grace period. Late fee is `per_day × days late` (capped at 50% of the deposit). Damage is inferred from the condition drop (or set with `damage_severity`) and deducted from the deposit. The deposit then becomes `refunded`, `partially_refunded` or `forfeited`.
* **Reviews:** only after completion, one per party per transaction. Abusive wording is held for moderation.
* **Cancelling after acceptance** counts against the canceller's Trust Score.

### Trust Score (0–100)

| Component | Weight | Measures |
|---|---|---|
| Return reliability | 35% | On-time, undamaged returns as a borrower (late / damaged / late cancellations penalised) |
| Review rating | 30% | Average rating received, smoothed toward 3.5★ until there are enough reviews |
| Account standing | 15% | Email, phone and identity verification |
| Lending reliability | 10% | Completed loans vs. lender cancellations after accepting |
| Experience | 10% | Completed transactions and account age |

After that, −6 points per upheld report (max −30), and a cap of 40 while suspended. Tiers: **platinum ≥85, gold ≥72, silver ≥58,
bronze ≥45, at_risk <45**, or **new** before the first completed transaction. Scores recalculate automatically after
returns, reviews, late cancellations and moderation decisions. Logic: `app/services/trust_service.py`.

---

## 5. Dataset

`data/seed/` holds about 1,700 consistent documents covering 18 months of activity in 10 London neighbourhoods:

| Collection | Docs | Max depth | Example deep path |
|---|---|---|---|
| users | 64 | 6 | `preferences.notifications.events.return_reminders.schedule.days_before_due` |
| items | 113 | 6 | `pricing.deposit.refund_policy.deductions.damage.major` |
| borrow_requests | 614 | 7 | `negotiation.thread[].proposal.terms.pickup.window.from` |
| transactions | 399 | 6 | `handover.pickup.condition_check.checklist.cosmetic.score` |
| reviews | 524 | 5 | `context.reviewer.trust_at_review.breakdown_hint.tier` |
| reports | 21 | 5 | `sla.escalation.policy.hours.first_response` |

It covers every state: pending, accepted, rejected (manual and automatic), cancelled (before and after acceptance), active, overdue,
on-time / late / damaged returns, full and partial refunds, forfeited deposits, two-way reviews with responses, flagged and
hidden reviews, warnings, a suspension, removed and paused listings, and open, under-review, resolved and dismissed reports.
Trust snapshots inside requests, transactions and reviews reflect the score *at that moment*.

* Full schema of every collection: **`docs/DATA_MODEL.md`**. One full example document per collection: **`docs/sample_documents/`**.
* Regenerate (reproducible, relative to today): `python -m data.generate_dataset` (or `--seed 7` for different data).
  The generator reuses the API's own builders and business rules, so generated data always matches what the API produces.

---

## 6. Tests

```bash
python -m pytest -v
```
24 tests run against an isolated in-memory database: auth, privacy, item CRUD, the full request → accept → collect →
return → review → trust lifecycle, overlap and auto-reject rules, late fees and damage, moderation, suspension and admin tools.

---

## 7. Project structure

```
borrowloop-backend/
├── run.py                     # entry point: python run.py
├── requirements.txt  .env  .env.example  pytest.ini
├── api.http                   # VS Code REST Client requests (whole flow)
├── app/
│   ├── __init__.py            # create_app() factory
│   ├── config.py              # settings from .env
│   ├── database.py            # MongoDB / in-memory connection, indexes, auto-seed
│   ├── seed.py                # JSON loader with date shifting + `flask seed-db` CLI
│   ├── constants.py           # roles, statuses, category taxonomy, London zones
│   ├── models/                # document builders (one per collection) - the nested schema lives here
│   ├── services/
│   │   ├── trust_service.py   # Trust Score engine
│   │   ├── lending_service.py # date validation, overlap checks, return/deposit assessment
│   │   └── stats_service.py   # denormalised user/item statistics
│   ├── routes/                # blueprints: auth, users, items, borrow_requests, transactions,
│   │                          #             reviews, reports, admin, meta
│   └── utils/                 # responses/errors, JWT + hashing, auth decorators, validation, helpers
├── data/
│   ├── generate_dataset.py    # activity simulator that writes data/seed/*.json
│   ├── item_catalog.py        # 59 item templates across 10 categories
│   └── seed/                  # users, items, borrow_requests, transactions, reviews, reports (+ _meta.json)
├── docs/
│   ├── DATA_MODEL.md          # full nested schema for every collection
│   ├── sample_documents/      # one complete example document per collection
│   └── BorrowLoop.postman_collection.json
├── tests/                     # pytest suite
└── .vscode/                   # launch configs (F5), tasks, settings, recommended extensions
```

## 8. Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: flask` | The virtual environment isn't active. Activate `.venv` and run `pip install -r requirements.txt`. In VS Code, select the `.venv` interpreter. |
| Log says *MongoDB not reachable … falling back* | Expected without MongoDB. Start MongoDB, or set `DB_MODE=mock` to silence it. |
| `Address already in use` / port 5000 busy | Change `PORT` in `.env` (and `@baseUrl` in `api.http`). |
| `401 Token has expired` | Log in again (tokens last `JWT_EXPIRES_HOURS`, default 24). |
| Changes disappear after restart | You're on the in-memory database. Use MongoDB for persistent data. |
| Want a fresh dataset in MongoDB | `flask --app run seed-db --drop` |
