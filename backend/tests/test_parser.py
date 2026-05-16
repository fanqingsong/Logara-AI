"""
test_parser.py - Unit tests for the LogParser orchestration system.
"""

from utils.parser import LogParser


def test_standard_log_parsing():
    """
    Test parsing of a standard formatted log line.
    """
    log = "[2026-05-16 10:30:00] ERROR: auth-service failed"

    parsed = LogParser.parse_line(log)

    assert parsed is not None
    assert parsed["level"] == "ERROR"
    assert parsed["message"] == "auth-service failed"
    assert parsed["parser_type"] == "standard"
    assert parsed["metadata"]["service"] == "auth-service"


def test_empty_log_returns_none():
    """
    Empty log lines should safely return None.
    """
    parsed = LogParser.parse_line("")

    assert parsed is None


def test_invalid_log_returns_none():
    """
    Invalid log formats should return None.
    """
    log = "this is not a valid log format"

    parsed = LogParser.parse_line(log)

    assert parsed is None


def test_timestamp_normalization():
    """
    Timestamp should be normalized to ISO format.
    """
    log = "[2026-05-16 14:24:49] INFO: service started"

    parsed = LogParser.parse_line(log)

    assert parsed is not None
    assert parsed["timestamp"] == "2026-05-16T14:24:49"


def test_json_fallback_parser():
    """
    Ensure fallback JSON parser works correctly.
    """
    log = '{"event":"startup","status":"ok"}'

    parsed = LogParser.parse_line(log)

    assert parsed is not None
    assert parsed["parser_type"] == "fallback_json"