"""Load the JSON dataset in data/seed into MongoDB, plus Flask CLI commands.

    flask --app run seed-db            # load data if the database is empty
    flask --app run seed-db --drop     # wipe and reload
"""
import copy
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import click

from .constants import ID_PREFIXES
from .database import ALL_COLLECTIONS, COUNTERS, ensure_indexes

log = logging.getLogger("borrowloop.seed")

ID_FIELDS = {
    "users": ("user", "user_id"),
    "items": ("item", "item_id"),
    "borrow_requests": ("request", "request_id"),
    "transactions": ("transaction", "transaction_id"),
    "reviews": ("review", "review_id"),
    "reports": ("report", "report_id"),
}


DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(T\d{2}:\d{2}:\d{2}Z)?$")


def _shift_value(value, days):
    if isinstance(value, str):
        m = DATE_RE.match(value)
        if m:
            shifted = (datetime.strptime(m.group(1), "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")
            return shifted + (m.group(2) or "")
        return value
    if isinstance(value, list):
        return [_shift_value(v, days) for v in value]
    if isinstance(value, dict):
        return {k: _shift_value(v, days) for k, v in value.items()}
    return value


def load_seed_files(data_dir, shift_dates=True):
    """Load the JSON files. If the snapshot is older than today, every date is moved
    forward by the same number of days so 'active', 'overdue' and 'upcoming' stay realistic."""
    data_dir = Path(data_dir)
    data = {}
    for name in ALL_COLLECTIONS:
        path = data_dir / f"{name}.json"
        if not path.exists():
            raise FileNotFoundError(f"Seed file missing: {path}. Run `python -m data.generate_dataset` first.")
        with path.open(encoding="utf-8") as fh:
            data[name] = json.load(fh)
    meta_path = data_dir / "_meta.json"
    if shift_dates and meta_path.exists():
        generated = json.loads(meta_path.read_text(encoding="utf-8"))["generated_at"][:10]
        days = (datetime.now(timezone.utc).date() - datetime.strptime(generated, "%Y-%m-%d").date()).days
        if days > 0:
            log.info("Shifting seed dates forward by %s day(s) to keep the dataset current.", days)
            data = {name: _shift_value(docs, days) for name, docs in data.items()}
    return data


def seed_database(db, data_dir, drop=False, shift_dates=True):
    if drop:
        for name in (*ALL_COLLECTIONS, COUNTERS):
            db[name].drop()
    data = load_seed_files(data_dir, shift_dates=shift_dates)
    counts = {}
    for name, docs in data.items():
        if docs:
            db[name].insert_many(copy.deepcopy(docs))
        counts[name] = len(docs)
        kind, field = ID_FIELDS[name]
        pattern = re.compile(rf"^{ID_PREFIXES[kind]}-(\d+)$")
        highest = max((int(m.group(1)) for d in docs if (m := pattern.match(d.get(field, "")))), default=0)
        db[COUNTERS].update_one({"_id": kind}, {"$max": {"seq": highest}}, upsert=True)
    ensure_indexes(db)
    return counts


def register_cli(app):
    @app.cli.command("seed-db")
    @click.option("--drop", is_flag=True, help="Drop existing BorrowLoop collections first.")
    def seed_db_command(drop):
        """Load data/seed/*.json into the configured database."""
        from .database import USERS, get_db

        db = get_db()
        if not drop and db[USERS].count_documents({}) > 0:
            click.echo("Database already has data. Use --drop to wipe and reload.")
            return
        counts = seed_database(db, app.config["SEED_DIR"], drop=drop)
        click.echo(f"Seeded ({app.config['DB_BACKEND']}): {counts}")

    @app.cli.command("generate-data")
    @click.option("--seed", default=42, help="Random seed for reproducible data.")
    def generate_data_command(seed):
        """Regenerate data/seed/*.json relative to today's date."""
        from data.generate_dataset import main as generate

        generate(seed=seed)
