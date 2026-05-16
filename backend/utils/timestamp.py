"""
timestamp.py - Utilities for handling and normalizing log timestamps.
"""
import logging
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)

def normalize_timestamp(ts_str: str) -> Optional[str]:
    """
    Attempts to normalize a raw timestamp string to an ISO 8601 format.
    Gracefully falls back to the original string if parsing fails.
    """
    if not ts_str:
        return None

    try:
        parsed_dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        return parsed_dt.isoformat()

    except ValueError:
        logger.debug(
            f"Timestamp '{ts_str}' did not match expected formats. Returning raw."
        )
        return ts_str

    except Exception as e:
        logger.warning(
            f"Unexpected error normalizing timestamp '{ts_str}': {e}"
        )
        return ts_str