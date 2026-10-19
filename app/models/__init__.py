"""Document builders. The API and the dataset generator both use these so every
record in the database has exactly the same nested shape."""
from .borrow_request import build_borrow_request
from .common import build_condition_check, build_location, money, resolve_zone
from .item import build_item
from .report import build_report
from .review import ASPECTS, build_review
from .transaction import build_transaction, payment_reference
from .user import build_user

__all__ = [
    "build_borrow_request", "build_condition_check", "build_location", "money", "resolve_zone",
    "build_item", "build_report", "ASPECTS", "build_review", "build_transaction",
    "payment_reference", "build_user",
]
