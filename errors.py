"""Error handling in one place."""
from flask import jsonify


class LibraryError(Exception):
    def __init__(self, message, status):
        super().__init__(message)
        self.message = message
        self.status = status


def make_error(message, status_code):
    """Create an error from a custom message and an HTTP status code."""
    return LibraryError(message, status_code)


def bad_request(message):
    return make_error(message, 400)


def not_found(message):
    return make_error(message, 404)


def conflict(message):
    return make_error(message, 409)


def error_response(message, status_code):
    """Turn a message and status code into the JSON response sent to the client."""
    return jsonify({"error": message}), status_code