"""Passive record vocabulary. No scheduling, HTTP calls, or controller inputs."""
import datetime
import json
import socket
import urllib.error

VERSION = 2


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def failure_category(status, valid, matches, error=None):
    if status is not None and status != 200:
        return 'http_5xx' if 500 <= status < 600 else 'http_4xx' if 400 <= status < 500 else 'unexpected_http_status'
    if error is not None:
        cause = error.reason if isinstance(error, urllib.error.URLError) else error
        if isinstance(cause, (TimeoutError, socket.timeout)):
            return 'timeout'
        if isinstance(error, json.JSONDecodeError):
            return 'invalid_response'
        if isinstance(cause, (ConnectionError, OSError)):
            return 'transport_failure'
        return 'unknown'
    if valid is False:
        return 'invalid_response'
    if status == 200 and valid is True and matches is False:
        return 'content_mismatch'
    if status == 200 and valid is True and matches is True:
        return None
    return 'unknown'


def request_record(start, end, seconds, status, valid, matches, error=None):
    category = failure_category(status, valid, matches, error)
    return {'measurement_version': VERSION, 'role': 'independent_request',
            'request_started_at': start, 'request_completed_at': end,
            'duration_seconds': seconds, 'duration_clock': 'process_monotonic',
            'status': status, 'response_valid': valid, 'content_matches': matches,
            'success': category is None, 'failure_category': category,
            'error_type': type(error).__name__ if error else None}
