"""Consistent JSON response envelope and error handling.

Success: {"success": true,  "data": ..., "meta": {...}?, "message": "..."?}
Error:   {"success": false, "error": {"code": "...", "message": "...", "details": ...?}}
"""
import logging

from flask import jsonify
from werkzeug.exceptions import HTTPException

log = logging.getLogger("borrowloop.api")


class ApiError(Exception):
    def __init__(self, message, status=400, code=None, details=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code or {
            400: "bad_request",
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            409: "conflict",
            422: "validation_error",
        }.get(status, "error")
        self.details = details


def success(data=None, status=200, meta=None, message=None):
    body = {"success": True}
    if message:
        body["message"] = message
    body["data"] = data
    if meta is not None:
        body["meta"] = meta
    return jsonify(body), status


def error(message, status=400, code="error", details=None):
    body = {"success": False, "error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return jsonify(body), status


def register_error_handlers(app):
    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error(exc.message, exc.status, exc.code, exc.details)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        code = (exc.name or "error").lower().replace(" ", "_")
        return error(exc.description or exc.name, exc.code or 500, code)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        log.exception("Unhandled error: %s", exc)
        return error("An unexpected error occurred.", 500, "internal_error")
