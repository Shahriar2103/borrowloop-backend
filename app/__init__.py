"""BorrowLoop API - application factory."""
import logging

from flask import Flask
from flask_cors import CORS

from .config import get_config
from .database import init_db
from .routes import register_blueprints
from .seed import register_cli
from .utils.responses import register_error_handlers


def create_app(config_name=None, **overrides):
    app = Flask(__name__)
    app.config.from_object(get_config(config_name))
    app.config.update(overrides)
    app.json.sort_keys = False

    logging.basicConfig(level=app.config["LOG_LEVEL"],
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    origins = app.config["CORS_ORIGINS"]
    CORS(app, resources={r"/api/*": {"origins": origins if origins == "*" else origins.split(",")}})

    register_error_handlers(app)
    register_blueprints(app)
    register_cli(app)
    init_db(app)
    return app
