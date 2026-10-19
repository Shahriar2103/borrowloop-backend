"""MongoDB connection management.

In "auto" mode the app tries a real MongoDB server first and, if it cannot be
reached, falls back to mongomock (an in-memory MongoDB implementation) so the
API always starts. In-memory data is reset every time the server restarts.
"""
import logging

from flask import current_app
from pymongo import ASCENDING, DESCENDING

log = logging.getLogger("borrowloop.db")

USERS = "users"
ITEMS = "items"
REQUESTS = "borrow_requests"
TRANSACTIONS = "transactions"
REVIEWS = "reviews"
REPORTS = "reports"
COUNTERS = "counters"

ALL_COLLECTIONS = (USERS, ITEMS, REQUESTS, TRANSACTIONS, REVIEWS, REPORTS)


def _connect_mongo(app):
    from pymongo import MongoClient

    client = MongoClient(app.config["MONGO_URI"], serverSelectionTimeoutMS=app.config["MONGO_TIMEOUT_MS"])
    client.admin.command("ping")
    return client


def _connect_mock():
    import mongomock

    return mongomock.MongoClient()


def init_db(app):
    mode = str(app.config.get("DB_MODE", "auto")).lower()
    client = None
    backend = None

    if mode in ("auto", "mongo"):
        try:
            client = _connect_mongo(app)
            backend = "mongodb"
            log.info("Connected to MongoDB at %s", app.config["MONGO_URI"])
        except Exception as exc:  # noqa: BLE001 - any connection problem
            if mode == "mongo":
                raise RuntimeError(
                    f"Could not connect to MongoDB at {app.config['MONGO_URI']}: {exc}. "
                    "Start MongoDB or set DB_MODE=auto / DB_MODE=mock in .env"
                ) from exc
            log.warning(
                "MongoDB not reachable at %s (%s). Falling back to the in-memory database "
                "- data resets on restart.", app.config["MONGO_URI"], exc.__class__.__name__,
            )

    if client is None:
        client = _connect_mock()
        backend = "mongomock"

    db = client[app.config["MONGO_DB_NAME"]]
    app.extensions["mongo_client"] = client
    app.extensions["db"] = db
    app.config["DB_BACKEND"] = backend

    ensure_indexes(db)

    if app.config.get("AUTO_SEED") and db[USERS].count_documents({}) == 0:
        from .seed import seed_database

        counts = seed_database(db, data_dir=app.config["SEED_DIR"])
        log.info("Seeded database: %s", counts)

    return db


def get_db():
    return current_app.extensions["db"]


def ensure_indexes(db):
    db[USERS].create_index([("user_id", ASCENDING)], unique=True)
    db[USERS].create_index([("email", ASCENDING)], unique=True)
    db[USERS].create_index([("role", ASCENDING)])
    db[USERS].create_index([("trust_score", DESCENDING)])

    db[ITEMS].create_index([("item_id", ASCENDING)], unique=True)
    db[ITEMS].create_index([("owner_id", ASCENDING)])
    db[ITEMS].create_index([("category", ASCENDING), ("availability", ASCENDING)])
    db[ITEMS].create_index([("status", ASCENDING)])

    db[REQUESTS].create_index([("request_id", ASCENDING)], unique=True)
    db[REQUESTS].create_index([("item_id", ASCENDING), ("status", ASCENDING)])
    db[REQUESTS].create_index([("borrower_id", ASCENDING)])
    db[REQUESTS].create_index([("owner_id", ASCENDING)])

    db[TRANSACTIONS].create_index([("transaction_id", ASCENDING)], unique=True)
    db[TRANSACTIONS].create_index([("request_id", ASCENDING)], unique=True)
    db[TRANSACTIONS].create_index([("borrower_id", ASCENDING), ("status", ASCENDING)])
    db[TRANSACTIONS].create_index([("lender_id", ASCENDING), ("status", ASCENDING)])

    db[REVIEWS].create_index([("review_id", ASCENDING)], unique=True)
    db[REVIEWS].create_index([("reviewed_user_id", ASCENDING)])
    db[REVIEWS].create_index([("transaction_id", ASCENDING), ("reviewer_id", ASCENDING)], unique=True)

    db[REPORTS].create_index([("report_id", ASCENDING)], unique=True)
    db[REPORTS].create_index([("status", ASCENDING)])
