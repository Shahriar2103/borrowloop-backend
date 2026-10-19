from .admin import bp as admin_bp
from .auth import bp as auth_bp
from .borrow_requests import bp as requests_bp
from .items import bp as items_bp
from .meta import bp as meta_bp
from .reports import bp as reports_bp
from .reviews import bp as reviews_bp
from .transactions import bp as transactions_bp
from .users import bp as users_bp

BLUEPRINTS = (meta_bp, auth_bp, users_bp, items_bp, requests_bp, transactions_bp, reviews_bp, reports_bp, admin_bp)


def register_blueprints(app):
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)
