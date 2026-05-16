"""
patterns.py - Regular expression patterns for log parsing.
"""
import re
from typing import List, Tuple, Pattern

# List of tuples containing (parser_name, compiled_regex_pattern)
# Evaluated in order. The first matching pattern wins.
PARSERS: List[Tuple[str, Pattern]] = [
    (
        "standard",
        re.compile(
            r'^\[(?P<timestamp>.*?)\]\s+(?P<level>INFO|WARN|WARNING|ERROR|DEBUG|CRITICAL):\s+(?P<message>.*)$',
            re.IGNORECASE
        )
    ),
    (
        "fallback_json",
        re.compile(r'^(?P<message>\{.*\})$')
    )
]