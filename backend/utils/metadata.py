"""
metadata.py - Heuristics and logic for extracting contextual metadata from log messages.
"""
import logging
from typing import Dict, Any

from utils.constants import META_SERVICE

logger = logging.getLogger(__name__)

def extract_metadata(message: str) -> Dict[str, Any]:
    """
    Applies heuristics to extract potential metadata from log messages.
    Returns an empty dictionary on failure to ensure safety.
    """
    metadata: Dict[str, Any] = {}

    if not message:
        return metadata

    try:
        if "service" in message.lower():
            words = message.split()

            for word in words:
                if "service" in word.lower():
                    clean_word = word.strip(".,:;\"'()[]{}")
                    metadata[META_SERVICE] = clean_word

    except Exception as e:
        logger.warning(
            f"Unexpected error during metadata extraction for message '{message}': {e}"
        )

    return metadata