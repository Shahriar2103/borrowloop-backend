"""Generate the BorrowLoop seed dataset (data/seed/*.json).

    python -m data.generate_dataset            # reproducible (seed 42), relative to today
    python -m data.generate_dataset --seed 7

The generator simulates ~18 months of community activity item by item: listings,
borrow requests (pending / accepted / rejected / cancelled), collections, returns
(on time, late, damaged), deposit settlement, two-way reviews and moderation reports.
It reuses the API's own document builders and business rules, then runs the real
stats and Trust Score services over the result, so the data is internally consistent.
"""
import argparse
import copy
import json
import random
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import mongomock  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

from app.constants import COMMUNITY_ZONES, CONDITIONS, ID_PREFIXES  # noqa: E402
from app.models import (build_borrow_request, build_item, build_location, build_report,  # noqa: E402
                        build_review, build_transaction, build_user)
from app.services.lending_service import assess_return  # noqa: E402
from app.services.stats_service import refresh_item_stats, refresh_user_stats  # noqa: E402
from app.services.trust_service import compute_trust_profile, recalculate_trust  # noqa: E402
from data.item_catalog import CATALOG  # noqa: E402

SEED_DIR = ROOT / "data" / "seed"
HASH_METHOD = "pbkdf2:sha256:100000"

FIRST = ["Oliver", "Amelia", "Noah", "Isla", "Muhammad", "Ava", "Leo", "Mia", "Arthur", "Ivy", "Harry", "Freya",
         "Oscar", "Lily", "George", "Grace", "Theo", "Sophia", "Jack", "Zara", "Yusuf", "Chloe", "Kwame", "Aisha",
         "Ethan", "Hana", "Samuel", "Fatima", "Kai", "Ella", "Ravi", "Maya", "Tomasz", "Nadia", "Luca", "Imogen",
         "Ibrahim", "Ruby", "Finley", "Anya", "Daniel", "Sienna", "Emeka", "Layla", "Callum", "Mei", "Rhys", "Leila",
         "Mateo", "Esme", "Hamza", "Poppy", "Joshua", "Aaliyah", "Kofi", "Evie", "Arjun", "Rosa", "Felix", "Yara"]
LAST = ["Smith", "Patel", "Jones", "Khan", "Williams", "Brown", "Taylor", "Ahmed", "Davies", "Evans", "Okoro",
        "Wilson", "Thomas", "Chen", "Roberts", "Ali", "Walker", "Nowak", "Wright", "Mensah", "Thompson", "Hussain",
        "White", "Kowalski", "Green", "Begum", "Hall", "Wood", "Rossi", "Clarke", "Singh", "Jackson", "Nguyen",
        "Hughes", "Adeyemi", "Edwards", "Murphy", "Rahman", "Turner", "Silva"]
STREETS = ["Albert Road", "Victoria Street", "Church Lane", "Station Road", "Park Avenue", "Mill Lane", "Queens Road",
           "Kings Crescent", "Elm Grove", "Market Street", "Canal Walk", "Orchard Close", "Highfield Road", "Rose Mews"]
BIOS = ["Love fixing things and sharing tools with neighbours.", "Student who borrows more than buys!",
        "Weekend camper and amateur photographer.", "New to the area, happy to lend and borrow.",
        "Trying to live with less stuff.", "Keen baker - ask me about the stand mixer.",
        "Parent of two, lots of baby gear to pass around.", "Musician and podcaster.",
        "Gardening fan with too many tools.", "Board game nights every Friday.", ""]
REQUEST_MESSAGES = ["Hi! Could I borrow this for the dates above? I'll take good care of it.",
                    "Need this for a uni project, happy to collect whenever suits you.",
                    "Would love to borrow this for a weekend trip.", "Is this still available? Can collect in the evening.",
                    "Hosting a party and this would be perfect!", "Doing some DIY at the flat, would be a huge help.",
                    "Exam season - need it for two weeks if possible.", "Trying this out before deciding to buy one.",
                    None]
REJECT_REASONS = ["Sorry, I need it myself that weekend.", "Already promised to a neighbour.",
                  "Dates don't work for me, please try later in the month.", "Item needs a repair first.", None]
CANCEL_REASONS = ["Plans changed, sorry!", "Found one from a friend.", "No longer need it.", "Trip was cancelled."]
DEVICES = [("desktop", "Windows", "Chrome"), ("desktop", "Mac OS", "Safari"), ("mobile", "iPhone", "Safari"),
           ("mobile", "Android", "Chrome"), ("desktop", "Linux", "Firefox")]

POSITIVE_FOR_LENDER = ["Item was exactly as described and pickup was easy.", "Super friendly and flexible on timings.",
                       "Great communication, would definitely borrow again.", "Spotless and well looked after. Thank you!",
                       "Really helpful, even showed me how to use it."]
MIXED_FOR_LENDER = ["Item was fine but pickup was a bit delayed.", "OK overall, a couple of accessories were missing.",
                    "Took a while to reply but got there in the end."]
NEGATIVE_FOR_LENDER = ["Item was not in the condition described.", "Cancelled pickup twice, frustrating.",
                       "Battery barely held a charge, not as advertised."]
POSITIVE_FOR_BORROWER = ["Returned on time and in perfect condition.", "Lovely borrower, very respectful of my things.",
                         "Great communication from start to finish.", "Would happily lend to again!",
                         "Even cleaned it before returning, thank you."]
MIXED_FOR_BORROWER = ["Returned a little late but let me know in advance.", "Fine overall, needed a bit of a clean.",
                      "Slow to respond about the return time."]
NEGATIVE_FOR_BORROWER = ["Returned several days late with no message.", "Item came back damaged.",
                         "Hard to get hold of for the return."]


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Generator:
    def __init__(self, seed=42, now=None):
        self.rng = random.Random(seed)
        self.now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
        self.users, self.items, self.requests, self.txns, self.reviews, self.reports = [], [], [], [], [], []
        self.users_by_id = {}
        self.items_by_id = {}
        self.seq = {"REQ": 0, "TXN": 0, "REV": 0, "RPT": 0}

    # ------------------------------------------------------------------ helpers
    def tmp_id(self, kind):
        self.seq[kind] += 1
        return f"__{kind}_{self.seq[kind]}__"

    def at(self, base, min_h, max_h):
        return base + timedelta(hours=self.rng.uniform(min_h, max_h))

    def day(self, dt):
        return dt.date().isoformat()

    def to_dt(self, day_str, hour=0):
        d = datetime.strptime(day_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return d + timedelta(hours=hour)

    # ------------------------------------------------------------------ users
    def make_users(self):
        demo = [
            ("Amara Okafor", "admin@borrowloop.com", "Admin@123", "admin", 610),
            ("Daniel Hughes", "moderator@borrowloop.com", "Admin@123", "admin", 600),
            ("Oliver Bennett", "lender@borrowloop.com", "Password@123", "lender", 560),
            ("Priya Shah", "borrower@borrowloop.com", "Password@123", "borrower", 540),
        ]
        specs = [{"name": n, "email": e, "password": p, "role": r, "age": a, "demo": True} for n, e, p, r, a in demo]
        used = {s["name"] for s in specs}
        roles = ["lender"] * 26 + ["borrower"] * 34
        for role in roles:
            while True:
                name = f"{self.rng.choice(FIRST)} {self.rng.choice(LAST)}"
                if name not in used:
                    used.add(name)
                    break
            first, last = name.lower().split(" ")
            specs.append({"name": name, "email": f"{first}.{last}@example.com", "password": "Password@123",
                          "role": role, "age": self.rng.randint(25, 520), "demo": False})
        demo_specs, rest = specs[:4], sorted(specs[4:], key=lambda s: -s["age"])
        for n, spec in enumerate(demo_specs + rest, start=1):
            uid = f"{ID_PREFIXES['user']}-{n:05d}"
            created = self.now - timedelta(days=spec["age"], hours=self.rng.randint(0, 23))
            zone = COMMUNITY_ZONES[0] if spec["demo"] else self.rng.choice(COMMUNITY_ZONES)
            email_v = spec["demo"] or self.rng.random() < 0.9
            phone_v = spec["demo"] or self.rng.random() < 0.6
            identity = "verified" if (spec["role"] == "admin" or spec["email"].startswith("lender") or
                                      self.rng.random() < 0.35) else self.rng.choice(["not_submitted", "not_submitted", "pending"])
            interests = self.rng.sample(["electronics", "books", "tools", "sports_outdoor", "kitchen", "music",
                                         "party_events", "gaming", "garden", "baby_kids"], self.rng.randint(1, 4))
            user = build_user(
                user_id=uid, name=spec["name"], email=spec["email"],
                password_hash=generate_password_hash(spec["password"], method=HASH_METHOD),
                role=spec["role"], created_at=iso(created), zone=zone,
                line1=f"{self.rng.randint(1, 180)} {self.rng.choice(STREETS)}",
                phone="07" + "".join(str(self.rng.randint(0, 9)) for _ in range(9)),
                bio=self.rng.choice(BIOS), interests=interests, email_verified=email_v,
                phone_verified=phone_v, identity_status=identity,
            )
            user["profile"]["location"] = build_location(
                zone, user["profile"]["location"]["address"]["line1"],
                postcode_suffix=f"{self.rng.randint(1, 9)}{self.rng.choice('ABDEFGHJLNPQRSTUWXYZ')}{self.rng.choice('ABDEFGHJLNPQRSTUWXYZ')}",
                lat_offset=self.rng.uniform(-0.006, 0.006), lng_offset=self.rng.uniform(-0.008, 0.008))
            if identity == "verified":
                user["verification"]["identity"]["document"]["check"] = {
                    "method": "manual_review", "by": "USR-00001", "at": iso(self.at(created, 2, 72))}
            if spec["role"] == "lender":
                user["preferences"]["lending"]["auto_decline_below_trust"] = self.rng.choice([None, None, None, 35, 40])
                user["preferences"]["lending"]["max_concurrent_loans"] = self.rng.choice([2, 3, 5])
            if self.rng.random() < 0.3:
                user["preferences"]["notifications"]["events"]["return_reminders"]["schedule"]["days_before_due"] = 2
            if self.rng.random() < 0.2:
                user["preferences"]["notifications"]["channels"]["sms"]["enabled"] = True
            # login history
            logins = []
            for _ in range(self.rng.randint(1, 6)):
                dtype, os_name, browser = self.rng.choice(DEVICES)
                logins.append({"at": iso(self.now - timedelta(days=self.rng.uniform(0, min(spec["age"], 90)))),
                               "ip": f"81.{self.rng.randint(0, 255)}.{self.rng.randint(0, 255)}.{self.rng.randint(1, 254)}",
                               "device": {"type": dtype, "os": {"name": os_name},
                                          "browser": {"name": browser, "user_agent": f"{browser} on {os_name}"}}})
            logins.sort(key=lambda x: x["at"])
            user["account"]["login_history"] = logins
            user["account"]["last_login_at"] = logins[-1]["at"]
            user["updated_at"] = logins[-1]["at"]
            user["_password"] = spec["password"]
            self.users.append(user)
            self.users_by_id[uid] = user

    # ------------------------------------------------------------------ items
    def make_items(self):
        lenders = [u for u in self.users if u["role"] == "lender"]
        specs = []
        for lender in lenders:
            count = 7 if lender["email"] == "lender@borrowloop.com" else self.rng.randint(2, 6)
            for template in self.rng.sample(CATALOG, count):
                owner_created = datetime.fromisoformat(lender["created_at"].replace("Z", "+00:00"))
                latest = self.now - timedelta(days=6)
                span = max(1, (latest - owner_created).days - 2)
                created = owner_created + timedelta(days=self.rng.randint(1, min(span, 120)), hours=self.rng.randint(8, 21))
                specs.append((created, lender, template))
        # the showcase item for the demo lender: listed recently with a clean calendar
        demo_lender = self.users_by_id["USR-00003"]
        showcase = next(t for t in CATALOG if t["type"] == "camera")
        specs.append((self.now - timedelta(days=12), demo_lender, dict(showcase, name="Canon EOS R50 Vlogging Kit", _showcase=True)))
        specs.sort(key=lambda s: s[0])

        for n, (created, owner, t) in enumerate(specs, start=1):
            iid = f"{ID_PREFIXES['item']}-{n:05d}"
            deposit = t["deposit"]
            if deposit:
                deposit = max(5, round(deposit * self.rng.uniform(0.8, 1.2) / 5) * 5)
            condition = self.rng.choices(["new", "like_new", "good", "fair"], [15, 40, 35, 10])[0]
            min_days, max_days = t["days"]
            l, w, h = t["dims"]
            item = build_item(
                item_id=iid, owner_id=owner["user_id"], name=t["name"], category=t["cat"], description=t["desc"],
                condition=condition, deposit=deposit, created_at=iso(created), subcategory=t["sub"], item_type=t["type"],
                tags=t["tags"], brand=t["brand"], model=t["model"], year=self.rng.randint(2018, 2025),
                specifications={"technical": t["technical"],
                                "physical": {"dimensions_cm": {"length": l, "width": w, "height": h},
                                             "weight_kg": t["weight"],
                                             "colour": self.rng.choice(["black", "grey", "white", "blue", "red", "silver"])}},
                attributes=t["attributes"],
                accessories=[{"name": a, "quantity": q} for a, q in t["accessories"]],
                images=[f"https://picsum.photos/seed/{iid.lower()}-{i}/1200/900" for i in range(self.rng.randint(1, 4))],
                min_days=min_days, max_days=max_days,
                min_trust_score=self.rng.choices([0, 40, 50, 60], [55, 20, 15, 10])[0],
                requires_id_verification=deposit >= 150 and self.rng.random() < 0.5,
                pickup_methods=self.rng.choice([["collection"], ["collection", "meetup"], ["meetup"], ["collection", "delivery"]]),
                owner_location=owner["profile"]["location"],
            )
            item["stats"]["views"] = self.rng.randint(5, 60)
            item["_showcase"] = bool(t.get("_showcase"))
            if item["_showcase"]:
                item["lending_rules"]["min_trust_score"] = 0
                item["lending_rules"]["requires_id_verification"] = False
                item["pickup"]["methods"] = ["collection", "meetup"]
            self.items.append(item)
            self.items_by_id[iid] = item

    # ------------------------------------------------------------------ simulation
    def pick_borrower(self, item, when):
        candidates, weights = [], []
        for u in self.users:
            if u["role"] == "admin" or u["user_id"] == item["owner_id"] or u["created_at"] > iso(when - timedelta(days=1)):
                continue
            if u["account"]["status"] != "active":
                continue
            candidates.append(u)
            weights.append(4 if u["email"] == "borrower@borrowloop.com" else (3 if u["role"] == "borrower" else 1))
        return self.rng.choices(candidates, weights)[0] if candidates else None

    def history(self, req, status, at, user_id, role, note):
        req["status_history"].append({"status": status, "at": iso(at), "by": {"user_id": user_id, "role": role}, "note": note})

    def new_request(self, item, borrower, start_day, end_day, created):
        owner = self.users_by_id[item["owner_id"]]
        req = build_borrow_request(
            request_id=self.tmp_id("REQ"), item=item, borrower=borrower, owner=owner,
            start_date=start_day, return_date=end_day, created_at=iso(created),
            duration_days=(self.to_dt(end_day) - self.to_dt(start_day)).days,
            message=self.rng.choice(REQUEST_MESSAGES), pickup_method=self.rng.choice(item["pickup"]["methods"]),
            pickup_window=self.rng.choice([{"from": "18:00", "to": "20:00"}, {"from": "10:00", "to": "12:00"},
                                           {"from": "15:00", "to": "17:00"}]),
        )
        req["updated_at"] = iso(created)
        # occasionally a negotiation round where the borrower shifted the dates
        if self.rng.random() < 0.12:
            sent = self.at(created, 0.2, 1.2)
            req["negotiation"]["rounds"] = 2
            req["negotiation"]["thread"].append({
                "message_id": f"{req['request_id']}-M2", "sender_id": borrower["user_id"], "sent_at": iso(sent),
                "body": "Would these dates work instead?",
                "proposal": {"start_date": start_day, "return_date": end_day,
                             "terms": copy.deepcopy(req["negotiation"]["thread"][0]["proposal"]["terms"])}})
            self.history(req, "pending", sent, borrower["user_id"], "borrower", "Borrower updated the request")
        self.requests.append(req)
        return req

    def accept(self, req, at):
        req["status"] = "accepted"
        req["decision"] = {"by": req["owner_id"], "at": iso(at), "reason": None, "auto": {"triggered": False, "rule": None}}
        req["updated_at"] = iso(at)
        self.history(req, "accepted", at, req["owner_id"], "lender", "Request accepted")

    def simulate_item(self, item):
        if item["_showcase"]:
            return
        created = datetime.fromisoformat(item["created_at"].replace("Z", "+00:00"))
        cursor = created + timedelta(days=self.rng.randint(1, 15))
        rules = item["lending_rules"]
        cond = item["condition"]
        loans = 0
        cap = self.rng.randint(2, 8)
        has_active = False
        while cursor < self.now + timedelta(days=40) and loans < cap:
            borrower = self.pick_borrower(item, cursor - timedelta(days=7))
            if not borrower:
                break
            duration = self.rng.randint(rules["min_days"], min(rules["max_days"], 10))
            start_day = self.day(cursor)
            end_day = self.day(cursor + timedelta(days=duration))
            created_at = cursor - timedelta(days=self.rng.randint(1, 6), hours=self.rng.randint(0, 10))
            if created_at < created:
                created_at = created + timedelta(hours=self.rng.randint(1, 20))
            if created_at > self.now - timedelta(hours=2):
                break
            future = self.to_dt(start_day) > self.now
            if future:
                outcome = self.rng.choices(["pending", "accepted", "rejected", "cancelled"], [60, 25, 10, 5])[0]
            else:
                outcome = self.rng.choices(["completed", "rejected", "cancelled"], [72, 14, 14])[0]
            if outcome == "completed" and has_active:
                outcome = "rejected"
            req = self.new_request(item, borrower, start_day, end_day, created_at)
            decision_at = min(self.at(created_at, 1.5, 30), self.now - timedelta(minutes=30))

            if outcome == "pending":
                # sometimes a competing pending request for the same dates
                if self.rng.random() < 0.25:
                    other = self.pick_borrower(item, cursor - timedelta(days=7))
                    if other and other["user_id"] != borrower["user_id"]:
                        self.new_request(item, other, start_day, end_day, min(self.at(created_at, 2, 30), self.now - timedelta(hours=1)))
                cursor = self.to_dt(end_day) + timedelta(days=self.rng.randint(1, 6))
                continue
            if outcome == "rejected":
                req["status"] = "rejected"
                reason = self.rng.choice(REJECT_REASONS)
                req["decision"] = {"by": req["owner_id"], "at": iso(decision_at), "reason": reason,
                                   "auto": {"triggered": False, "rule": None}}
                req["updated_at"] = iso(decision_at)
                self.history(req, "rejected", decision_at, req["owner_id"], "lender", reason or "Request rejected")
                cursor += timedelta(days=self.rng.randint(0, 4))
                continue
            if outcome == "cancelled":
                after_acceptance = self.rng.random() < 0.3
                if after_acceptance:
                    self.accept(req, decision_at)
                cancel_at = min(self.at(decision_at, 1, 48), self.now - timedelta(minutes=10))
                lender_cancel = after_acceptance and self.rng.random() < 0.2
                actor = req["owner_id"] if lender_cancel else req["borrower_id"]
                role = "lender" if lender_cancel else "borrower"
                reason = "Sorry, the item broke before pickup." if lender_cancel else self.rng.choice(CANCEL_REASONS)
                req["status"] = "cancelled"
                req["cancellation"] = {"by": actor, "role": role, "at": iso(cancel_at), "reason": reason,
                                       "after_acceptance": after_acceptance}
                req["updated_at"] = iso(cancel_at)
                self.history(req, "cancelled", cancel_at, actor, role, reason)
                cursor += timedelta(days=self.rng.randint(0, 4))
                continue
            if outcome == "accepted":
                self.accept(req, decision_at)
                item["availability_details"]["calendar"]["booked"].append(
                    {"request_id": req["request_id"], "from": start_day, "to": end_day, "status": "accepted"})
                cursor = self.to_dt(end_day) + timedelta(days=self.rng.randint(1, 10))
                continue

            # ---- collected: active or completed
            self.accept(req, decision_at)
            borrowed_at = self.to_dt(start_day, self.rng.uniform(9, 19))
            if borrowed_at <= decision_at:
                borrowed_at = decision_at + timedelta(hours=1)
            if borrowed_at > self.now:
                borrowed_at = self.now - timedelta(hours=self.rng.uniform(1, 6))
            lender = self.users_by_id[item["owner_id"]]
            item["condition"] = cond
            txn = build_transaction(transaction_id=self.tmp_id("TXN"), request=req, item=item, lender=lender,
                                    borrower=borrower, borrowed_at=iso(borrowed_at), created_at=iso(borrowed_at),
                                    pickup_grade=cond)
            txn["reminders"][0]["scheduled_for"] = self.day(self.to_dt(end_day) - timedelta(days=1))
            req["transaction_id"] = txn["transaction_id"]
            self.history(req, "accepted", borrowed_at, req["owner_id"], "lender",
                         f"Item collected - transaction {txn['transaction_id']}")
            self.txns.append(txn)
            loans += 1

            lateness = self.rng.choices(["early", "on_time", "late", "very_late"], [20, 60, 14, 6])[0]
            due = self.to_dt(end_day)
            if lateness == "early":
                returned = due - timedelta(days=1) + timedelta(hours=self.rng.uniform(10, 20))
            elif lateness == "on_time":
                returned = due + timedelta(hours=self.rng.uniform(9, 21))
            elif lateness == "late":
                returned = due + timedelta(days=self.rng.randint(1, 3), hours=self.rng.uniform(10, 20))
            else:
                returned = due + timedelta(days=self.rng.randint(4, 9), hours=self.rng.uniform(10, 20))
            if returned <= borrowed_at:
                returned = borrowed_at + timedelta(hours=self.rng.uniform(20, 30))

            recently_due = timedelta(0) < self.now - due < timedelta(days=12)
            if recently_due and self.rng.random() < 0.3:
                returned = self.now + timedelta(days=1)  # never brought back yet -> overdue
            if returned >= self.now - timedelta(hours=1):
                # still out (either not due yet, or overdue)
                has_active = True
                for reminder in txn["reminders"]:
                    reminder["sent"] = bool(reminder["scheduled_for"] and reminder["scheduled_for"] <= self.day(self.now))
                item["availability"] = False
                item["availability_details"].update({"status": "on_loan", "current_transaction_id": txn["transaction_id"],
                                                     "next_available_from": end_day})
                item["availability_details"]["calendar"]["booked"].append(
                    {"request_id": req["request_id"], "from": start_day, "to": end_day, "status": "on_loan"})
                cursor = max(due, self.now) + timedelta(days=self.rng.randint(2, 8))
                continue

            drift = self.rng.choices([0, 1, 2], [78, 17, 5])[0]
            if lateness == "very_late" and self.rng.random() < 0.4:
                drift = max(drift, 1)
            ret_cond = CONDITIONS[min(len(CONDITIONS) - 1, CONDITIONS.index(cond) + drift)]
            notes = None
            if drift == 1:
                notes = self.rng.choice(["Light scuffs on the casing.", "Minor wear, nothing major.", "A little dusty."])
            elif drift == 2:
                notes = self.rng.choice(["Cracked cover, needs replacing.", "Visible damage to the body.",
                                         "One accessory missing and casing scratched."])
            updated, item_set, inspection = assess_return(txn, item, returned, ret_cond, notes=notes,
                                                          actor_id=item["owner_id"], now=returned)
            txn.clear()
            txn.update(updated)
            cond = ret_cond
            item["condition"] = ret_cond
            item["condition_report"]["grade"] = ret_cond
            item["condition_report"]["summary"] = item_set["condition_report.summary"]
            item["condition_report"]["last_inspected_at"] = item_set["condition_report.last_inspected_at"]
            item["condition_report"]["inspections"] = (item["condition_report"]["inspections"] + [inspection])[-6:]
            cursor = returned + timedelta(days=self.rng.randint(0, 20))

    def simulate(self):
        for item in self.items:
            self.simulate_item(item)

    # ------------------------------------------------------------------ demo guarantees
    def demo_scenarios(self):
        demo_lender, demo_borrower = "USR-00003", "USR-00004"
        showcase = next(i for i in self.items if i["_showcase"])
        borrower = self.users_by_id[demo_borrower]
        # accepted request starting tomorrow -> lets you test POST /api/transactions immediately
        start = self.day(self.now + timedelta(days=1))
        end = self.day(self.now + timedelta(days=4))
        req = self.new_request(showcase, borrower, start, end, self.now - timedelta(days=1, hours=3))
        req["message"] = "Hi Oliver, could I borrow the camera for a vlogging weekend?"
        self.accept(req, self.now - timedelta(hours=20))
        showcase["availability_details"]["calendar"]["booked"].append(
            {"request_id": req["request_id"], "from": start, "to": end, "status": "accepted"})
        # pending requests on the showcase item later in the month -> test accept / reject
        for offset in (9, 10):
            other = self.pick_borrower(showcase, self.now - timedelta(days=30))
            while other["user_id"] == demo_borrower:
                other = self.pick_borrower(showcase, self.now - timedelta(days=30))
            self.new_request(showcase, other, self.day(self.now + timedelta(days=offset)),
                             self.day(self.now + timedelta(days=offset + 3)), self.now - timedelta(hours=offset))

    def fresh_demand(self, count=30):
        """Recent pending requests on available items, so owners have decisions waiting."""
        candidates = [i for i in self.items if i["status"] == "active" and i["availability"] and not i["_showcase"]]
        for item in self.rng.sample(candidates, min(count, len(candidates))):
            rules = item["lending_rules"]
            start = self.now + timedelta(days=self.rng.randint(2, 20))
            duration = self.rng.randint(rules["min_days"], min(rules["max_days"], 7))
            start_day, end_day = self.day(start), self.day(start + timedelta(days=duration))
            clash = any(r["item_id"] == item["item_id"] and r["status"] in ("accepted", "pending")
                        and not r["transaction_id"] and r["start_date"] <= end_day and r["return_date"] >= start_day
                        for r in self.requests)
            if clash:
                continue
            borrower = self.pick_borrower(item, self.now - timedelta(days=7))
            if borrower:
                self.new_request(item, borrower, start_day, end_day,
                                 self.now - timedelta(hours=self.rng.uniform(2, 72)))

    # ------------------------------------------------------------------ reviews
    def rating_for(self, direction, txn):
        assessment = txn["return_assessment"]
        if direction == "lender_to_borrower":
            if assessment["damage"]["severity"] == "major":
                return self.rng.choice([1, 2, 2, 3])
            if assessment["days_late"] > 3:
                return self.rng.choice([1, 2, 3])
            if assessment["days_late"] > 0 or assessment["damage"]["severity"] == "minor":
                return self.rng.choice([3, 3, 4, 4, 5])
            return self.rng.choices([3, 4, 5], [5, 30, 65])[0]
        return self.rng.choices([1, 2, 3, 4, 5], [2, 4, 10, 30, 54])[0]

    def comment_for(self, direction, rating):
        if direction == "borrower_to_lender":
            pool = POSITIVE_FOR_LENDER if rating >= 4 else MIXED_FOR_LENDER if rating == 3 else NEGATIVE_FOR_LENDER
        else:
            pool = POSITIVE_FOR_BORROWER if rating >= 4 else MIXED_FOR_BORROWER if rating == 3 else NEGATIVE_FOR_BORROWER
        return self.rng.choice(pool)

    def make_reviews(self):
        completed = sorted([t for t in self.txns if t["status"] == "completed"], key=lambda t: t["returned_at"])
        voters = [u["user_id"] for u in self.users if u["role"] != "admin"]
        for txn in completed:
            returned = datetime.fromisoformat(txn["returned_at"].replace("Z", "+00:00"))
            for direction, chance in (("borrower_to_lender", 0.75), ("lender_to_borrower", 0.65)):
                if self.rng.random() > chance:
                    continue
                created = self.at(returned, 2, 120)
                if created > self.now:
                    continue
                if direction == "borrower_to_lender":
                    reviewer, reviewed = txn["borrower_id"], txn["lender_id"]
                else:
                    reviewer, reviewed = txn["lender_id"], txn["borrower_id"]
                rating = self.rating_for(direction, txn)
                aspects = {}
                for name in ("communication", "punctuality", "item_accuracy" if direction == "borrower_to_lender" else "care_of_item"):
                    aspects[name] = max(1, min(5, rating + self.rng.choice([-1, 0, 0, 0, 1])))
                review = build_review(review_id=self.tmp_id("REV"), reviewer=self.users_by_id[reviewer],
                                      reviewed_user=self.users_by_id[reviewed], transaction=txn, rating=rating,
                                      comment=self.comment_for(direction, rating), created_at=iso(created),
                                      direction=direction, aspects=aspects,
                                      toxicity_score=round(self.rng.uniform(0.01, 0.12), 2))
                if self.rng.random() < 0.15 and created + timedelta(days=1) < self.now:
                    review["response"] = {"comment": self.rng.choice(["Thanks so much!", "Thank you, happy to help again.",
                                                                      "Sorry about that - lesson learned.",
                                                                      "Appreciate the feedback."]),
                                          "at": iso(min(self.at(created, 6, 72), self.now))}
                n_votes = self.rng.choices([0, 1, 2, 3, 5], [50, 20, 15, 10, 5])[0]
                review_voters = self.rng.sample([v for v in voters if v not in (reviewer, reviewed)], n_votes)
                review["engagement"]["helpful"] = {"count": len(review_voters), "voters": review_voters}
                self.reviews.append(review)
        # leave the demo borrower's most recent completed loan unreviewed so it can be reviewed via the API
        mine = [t for t in completed if t["borrower_id"] == "USR-00004"]
        if mine:
            last = mine[-1]["transaction_id"]
            self.reviews = [r for r in self.reviews if not (r["transaction_id"] == last and r["reviewer_id"] == "USR-00004")]

    # ------------------------------------------------------------------ reports
    def make_reports(self):
        rng = self.rng
        admins = ["USR-00001", "USR-00002"]

        def report(reporter_id, ttype, tid, snapshot, cat, sub, desc, created, priority="medium", related=None):
            rep = build_report(report_id=self.tmp_id("RPT"), reporter=self.users_by_id[reporter_id], target_type=ttype,
                               target_id=tid, target_snapshot=snapshot, category=cat, subcategory=sub, description=desc,
                               created_at=iso(created), priority=priority, related=related,
                               attachments=[f"https://picsum.photos/seed/evidence-{rng.randint(1, 9999)}/800/600"
                                            for _ in range(rng.randint(0, 2))])
            self.reports.append(rep)
            return rep

        def progress(rep, status, created, action=None, notes=None, effects=None):
            admin = rng.choice(admins)
            t1 = self.at(created, 2, 30)
            rep["assigned_to"] = admin
            rep["status"] = "under_review"
            rep["activity_log"].append({"at": iso(t1), "by": {"user_id": admin, "role": "admin"}, "action": "updated",
                                        "note": "Looking into this", "changes": {"status": {"from": "open", "to": "under_review"},
                                                                                "assigned_to": {"from": None, "to": admin}}})
            rep["updated_at"] = iso(t1)
            if status == "under_review":
                return
            t2 = min(self.at(t1, 4, 96), self.now - timedelta(hours=1))
            rep["status"] = status
            rep["updated_at"] = iso(t2)
            rep["activity_log"].append({"at": iso(t2), "by": {"user_id": admin, "role": "admin"},
                                        "action": "resolved" if status == "resolved" else "updated", "note": notes,
                                        "changes": {"status": {"from": "under_review", "to": status}}})
            if status == "resolved":
                rep["resolution"] = {"action": action, "notes": notes, "by": admin, "at": iso(t2),
                                     "effects": effects or {"user": None, "item": None, "review": None, "trust": None}}
            return t2

        completed = [t for t in self.txns if t["status"] == "completed"]
        late = sorted([t for t in completed if t["return_assessment"]["days_late"] > 3], key=lambda t: t["returned_at"])
        damaged = [t for t in completed if t["return_assessment"]["damage"]["severity"] != "none"]

        # users reported for late returns / damage
        offenders = {}
        for t in late + damaged:
            offenders.setdefault(t["borrower_id"], []).append(t)
        offender_ids = [u for u in offenders if u not in ("USR-00003", "USR-00004")]
        rng.shuffle(offender_ids)
        plan = ["warning", "warning", "warning", "suspend_user", "dismissed", "dismissed", "open", "under_review"]
        suspended_done = False
        for uid, outcome in zip(offender_ids, plan):
            t = offenders[uid][-1]
            created = self.at(datetime.fromisoformat(t["returned_at"].replace("Z", "+00:00")), 3, 48)
            if created > self.now:
                created = self.now - timedelta(hours=5)
            user = self.users_by_id[uid]
            sub = "late_return" if t["return_assessment"]["days_late"] > 0 else "item_damaged"
            rep = report(t["lender_id"], "user", uid, {"name": user["name"], "role": user["role"], "trust_score": None},
                         "conduct", sub, f"Borrowed my {t['item_snapshot']['name']} and "
                         + ("returned it days late without replying to messages." if sub == "late_return"
                            else "it came back damaged."), created, "medium",
                         related={"transaction_id": t["transaction_id"], "request_id": t["request_id"]})
            if outcome in ("open",):
                continue
            if outcome == "under_review":
                progress(rep, "under_review", created)
                continue
            if outcome == "dismissed":
                progress(rep, "dismissed", created, notes="Borrower provided evidence of agreed extension.")
                continue
            if outcome == "suspend_user" and suspended_done:
                outcome = "warning"
            effects = {"user": {"user_id": uid, "action": outcome}, "item": None, "review": None, "trust": None}
            t2 = progress(rep, "resolved", created, action=outcome,
                          notes="Repeated late returns." if outcome == "suspend_user" else "First warning issued.",
                          effects=effects)
            if outcome == "warning":
                user["account"]["moderation"]["warnings"].append(
                    {"at": iso(t2), "by": rep["resolution"]["by"], "report_id": rep["report_id"], "reason": sub})
            else:
                suspended_done = True
                user["account"]["status"] = "suspended"
                user["account"]["moderation"]["suspension"] = {
                    "status": "suspended", "at": iso(t2), "by": rep["resolution"]["by"], "report_id": rep["report_id"],
                    "until": iso(t2 + timedelta(days=30))}

        # item reports
        live = [i for i in self.items if i["availability_details"]["status"] != "on_loan" and not i["_showcase"]
                and i["owner_id"] != "USR-00003"]
        for i, item in enumerate(rng.sample(live, 6)):
            reporter = self.pick_borrower(item, self.now)
            created = self.now - timedelta(days=rng.randint(1, 60), hours=rng.randint(0, 20))
            sub = rng.choice(["misleading_description", "prohibited_item", "misleading_description"])
            rep = report(reporter["user_id"], "item", item["item_id"],
                         {"name": item["name"], "category": item["category"], "owner_id": item["owner_id"]},
                         "content", sub, "The listing photos don't match the actual item." if sub != "prohibited_item"
                         else "This looks like it breaks the community rules.", created,
                         "high" if sub == "prohibited_item" else "low")
            item["moderation"]["flags"].append({"report_id": rep["report_id"], "reason": sub, "at": iso(created)})
            if i == 0:
                t2 = progress(rep, "resolved", created, action="remove_item", notes="Listing breached guidelines.",
                              effects={"user": None, "item": {"item_id": item["item_id"], "action": "removed"},
                                       "review": None, "trust": None})
                item.update({"status": "removed", "availability": False})
                item["availability_details"].update({"status": "unavailable"})
                item["availability_details"]["calendar"]["booked"] = []
                item["moderation"]["status"] = "removed"
                item["moderation"]["review"] = {"by": rep["resolution"]["by"], "at": iso(t2), "decision": f"report:{rep['report_id']}"}
                for r in self.requests:
                    if r["item_id"] == item["item_id"] and r["status"] in ("pending", "accepted") and not r["transaction_id"]:
                        r["status"] = "cancelled"
                        r["cancellation"] = {"by": rep["resolution"]["by"], "role": "admin", "at": iso(t2),
                                             "reason": "Listing removed by administrator", "after_acceptance": False}
                        self.history(r, "cancelled", t2, rep["resolution"]["by"], "admin", "Listing removed")
            elif i == 1:
                progress(rep, "dismissed", created, notes="Listing checked - accurate.")
                item["moderation"]["review"] = {"by": rep["assigned_to"], "at": rep["updated_at"], "decision": "no_action"}
            elif i == 2:
                progress(rep, "under_review", created)

        # transaction disputes
        for i, t in enumerate(rng.sample(damaged or completed, min(4, len(damaged or completed)))):
            created = self.at(datetime.fromisoformat(t["returned_at"].replace("Z", "+00:00")), 2, 24)
            if created > self.now:
                created = self.now - timedelta(hours=3)
            rep = report(t["borrower_id"], "transaction", t["transaction_id"],
                         {"item": t["item_snapshot"]["name"], "lender_id": t["lender_id"], "borrower_id": t["borrower_id"],
                          "status": t["status"]}, "conduct", "item_damaged",
                         "The lender kept part of my deposit for damage that was already there at pickup.", created,
                         "medium", related={"transaction_id": t["transaction_id"], "request_id": t["request_id"]})
            if i % 2 == 0:
                t["dispute"] = {"open": True, "report_id": rep["report_id"]}
                if i == 2:
                    progress(rep, "under_review", created)
            else:
                progress(rep, "resolved", created, action="none", notes="Pickup photos confirm the damage was new.")
                t["dispute"] = {"open": False, "report_id": rep["report_id"]}

        # review reports
        low = [r for r in self.reviews if r["rating"] <= 2]
        for i, review in enumerate(rng.sample(low, min(3, len(low)))):
            created = self.at(datetime.fromisoformat(review["created_at"].replace("Z", "+00:00")), 2, 48)
            if created > self.now:
                created = self.now - timedelta(hours=2)
            rep = report(review["reviewed_user_id"], "review", review["review_id"],
                         {"reviewer_id": review["reviewer_id"], "reviewed_user_id": review["reviewed_user_id"],
                          "rating": review["rating"], "comment": review["comment"]},
                         "content", "inappropriate_review", "This review is unfair and not what happened.", created, "low")
            review["moderation"]["flags"].append({"by": review["reviewed_user_id"], "reason": "reported", "at": iso(created)})
            if i == 0:
                t2 = progress(rep, "resolved", created, action="hide_review", notes="Review violated guidelines.",
                              effects={"user": None, "item": None, "review": {"review_id": review["review_id"], "action": "hidden"},
                                       "trust": None})
                review["moderation"]["status"] = "hidden"
                review["moderation"]["checks"]["manual"] = {"by": rep["resolution"]["by"], "at": iso(t2), "decision": "hidden"}
            elif i == 1:
                progress(rep, "dismissed", created, notes="Review reflects the transaction outcome.")
                review["moderation"]["checks"]["manual"] = {"by": rep["assigned_to"], "at": rep["updated_at"], "decision": "kept"}
            else:
                review["moderation"]["status"] = "flagged"

    def pause_some(self, count=3):
        busy = {r["item_id"] for r in self.requests if r["status"] in ("pending", "accepted")}
        candidates = [i for i in self.items if i["status"] == "active" and i["availability"]
                      and i["item_id"] not in busy and i["owner_id"] != "USR-00003"]
        for item in self.rng.sample(candidates, min(count, len(candidates))):
            item["status"] = "paused"
            item["availability"] = False
            item["availability_details"]["status"] = "unavailable"
            item["availability_details"]["calendar"]["blocked"].append(
                {"from": self.day(self.now - timedelta(days=3)), "to": self.day(self.now + timedelta(days=21)),
                 "reason": self.rng.choice(["Owner away", "Being repaired", "Using it myself"])})

    # ------------------------------------------------------------------ trust snapshots
    def historical_trust(self):
        """Fill trust snapshots inside requests/transactions/reviews with the score at that moment."""
        by_borrower, by_lender, reviews_for = {}, {}, {}
        for t in self.txns:
            if t["status"] == "completed":
                by_borrower.setdefault(t["borrower_id"], []).append(t)
                by_lender.setdefault(t["lender_id"], []).append(t)
        for r in self.reviews:
            if r["moderation"]["status"] == "published":
                reviews_for.setdefault(r["reviewed_user_id"], []).append(r)
        cache = {}

        def trust_at(uid, ts):
            key = (uid, ts[:10])
            if key in cache:
                return cache[key]
            user = self.users_by_id[uid]
            when = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            snapshot_user = dict(user, account={"status": "active"})
            profile = compute_trust_profile(
                snapshot_user,
                borrowed=[t for t in by_borrower.get(uid, []) if t["returned_at"] <= ts],
                lent=[t for t in by_lender.get(uid, []) if t["returned_at"] <= ts],
                reviews_received=[r for r in reviews_for.get(uid, []) if r["created_at"] <= ts], now=when)
            cache[key] = {"score": profile["score"], "tier": profile["tier"]}
            return cache[key]

        for r in self.requests:
            r["item_snapshot"]["owner"]["trust"] = trust_at(r["owner_id"], r["created_at"])
            r["borrower_snapshot"]["trust"] = trust_at(r["borrower_id"], r["created_at"])
        for t in self.txns:
            t["parties"]["lender"]["trust_at_start"] = trust_at(t["lender_id"], t["borrowed_at"])
            t["parties"]["borrower"]["trust_at_start"] = trust_at(t["borrower_id"], t["borrowed_at"])
        for r in self.reviews:
            snap = trust_at(r["reviewer_id"], r["created_at"])
            r["context"]["reviewer"]["trust_at_review"] = {"score": snap["score"], "breakdown_hint": {"tier": snap["tier"]}}
        for rep in self.reports:
            if rep["target"]["type"] == "user":
                rep["target"]["snapshot"]["trust_score"] = trust_at(rep["target"]["id"], rep["created_at"])["score"]
        # monthly trust history for every user
        for user in self.users:
            created = datetime.fromisoformat(user["created_at"].replace("Z", "+00:00"))
            points, cursor, previous = [], created + timedelta(days=1), None
            while cursor < self.now:
                snap = trust_at(user["user_id"], iso(cursor))
                points.append({"at": iso(cursor), "score": snap["score"],
                               "change": round(snap["score"] - previous, 1) if previous is not None else None,
                               "reason": "account_created" if previous is None else "monthly_recalculation"})
                previous = snap["score"]
                cursor += timedelta(days=30)
            user["trust_profile"]["history"] = points[-24:]

    # ------------------------------------------------------------------ finalise
    def finalise(self):
        db = mongomock.MongoClient().borrowloop_gen
        for name, docs in (("users", self.users), ("items", self.items), ("borrow_requests", self.requests),
                           ("transactions", self.txns), ("reviews", self.reviews), ("reports", self.reports)):
            clean_docs = []
            for d in docs:
                d = copy.deepcopy(d)
                for k in ("_password", "_showcase"):
                    d.pop(k, None)
                clean_docs.append(d)
            if clean_docs:
                db[name].insert_many(clean_docs)
        for item in self.items:
            refresh_item_stats(db, item["item_id"])
            views = db.items.find_one({"item_id": item["item_id"]})["stats"]["times_borrowed"] * self.rng.randint(6, 20)
            db.items.update_one({"item_id": item["item_id"]}, {"$inc": {"stats.views": views}})
        for user in self.users:
            refresh_user_stats(db, user["user_id"])
            recalculate_trust(db, user["user_id"], reason="dataset_snapshot", now=self.now)
        # badges
        for user in db.users.find():
            stats, badges = user["stats"], []
            created = user["created_at"]
            if created < iso(self.now - timedelta(days=450)):
                badges.append({"code": "early_member", "label": "Early Member", "awarded_at": iso(
                    datetime.fromisoformat(created.replace("Z", "+00:00")) + timedelta(days=365))})
            if stats["lending"]["completed"] >= 10:
                badges.append({"code": "super_lender", "label": "Super Lender", "awarded_at": user["updated_at"]})
            if stats["borrowing"]["completed"] >= 5 and (stats["borrowing"]["on_time_rate"] or 0) >= 0.9:
                badges.append({"code": "reliable_borrower", "label": "Reliable Borrower", "awarded_at": user["updated_at"]})
            if user["verification"]["level"] == "full":
                badges.append({"code": "fully_verified", "label": "Fully Verified", "awarded_at": user["created_at"]})
            db.users.update_one({"user_id": user["user_id"]}, {"$set": {"account.badges": badges}})
        return db

    def dump(self, db, out_dir):
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        # map temporary IDs to chronological, human-readable IDs
        mapping = {}
        for coll, kind, prefix, field in (("borrow_requests", "REQ", "REQ", "created_at"),
                                          ("transactions", "TXN", "TXN", "borrowed_at"),
                                          ("reviews", "REV", "REV", "created_at"),
                                          ("reports", "RPT", "RPT", "created_at")):
            id_field = {"REQ": "request_id", "TXN": "transaction_id", "REV": "review_id", "RPT": "report_id"}[kind]
            ordered = sorted(db[coll].find({}, {id_field: 1, field: 1}), key=lambda d: (d[field], d[id_field]))
            for n, d in enumerate(ordered, start=1):
                mapping[d[id_field]] = f"{prefix}-{n:05d}"
        pattern = re.compile(r"__(REQ|TXN|REV|RPT)_\d+__")
        sort_fields = {"users": "user_id", "items": "item_id", "borrow_requests": "request_id",
                       "transactions": "transaction_id", "reviews": "review_id", "reports": "report_id"}
        counts = {}
        for coll, id_field in sort_fields.items():
            docs = [{k: v for k, v in d.items() if k != "_id"} for d in db[coll].find()]
            text = pattern.sub(lambda m: mapping[m.group(0)], json.dumps(docs, ensure_ascii=False))
            docs = sorted(json.loads(text), key=lambda d: d[id_field])
            with (out_dir / f"{coll}.json").open("w", encoding="utf-8") as fh:
                json.dump(docs, fh, indent=2, ensure_ascii=False)
            counts[coll] = len(docs)
        meta = {"generated_at": iso(self.now), "generator": "data/generate_dataset.py", "counts": counts,
                "demo_accounts": [
                    {"role": "admin", "email": "admin@borrowloop.com", "password": "Admin@123", "user_id": "USR-00001"},
                    {"role": "admin", "email": "moderator@borrowloop.com", "password": "Admin@123", "user_id": "USR-00002"},
                    {"role": "lender", "email": "lender@borrowloop.com", "password": "Password@123", "user_id": "USR-00003"},
                    {"role": "borrower", "email": "borrower@borrowloop.com", "password": "Password@123", "user_id": "USR-00004"},
                ],
                "other_accounts_password": "Password@123"}
        with (out_dir / "_meta.json").open("w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2)
        return counts


def main(seed=42, out_dir=SEED_DIR):
    gen = Generator(seed=seed)
    gen.make_users()
    gen.make_items()
    gen.simulate()
    gen.demo_scenarios()
    gen.fresh_demand()
    gen.make_reviews()
    gen.make_reports()
    gen.pause_some()
    gen.historical_trust()
    db = gen.finalise()
    counts = gen.dump(db, out_dir)
    print(f"Dataset written to {out_dir}: {counts}")
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", default=str(SEED_DIR))
    args = parser.parse_args()
    main(seed=args.seed, out_dir=args.out)
