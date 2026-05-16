"""
parser.py - Orchestration layer for parsing raw logs into structured JSON payloads.
"""
import logging
from typing import Dict, Optional, Any

from utils.patterns import PARSERS
from utils.metadata import extract_metadata
from utils.timestamp import normalize_timestamp

logger = logging.getLogger(__name__)

class LogParser:
    """
    Orchestrates the parsing of raw log lines into a standardized dictionary format.
    Delegates pattern matching, timestamp formatting, and metadata extraction to specialized modules.
    """

    @staticmethod
    def parse_line(line: str) -> Optional[Dict[str, Any]]:
        """
        Parses a single log line against dynamically loaded patterns.
        
        Args:
            line (str): The raw log line string.
            
        Returns:
            Optional[Dict]: A standardized dictionary representing the parsed log,
                            or None if the line could not be parsed or was empty.
        """
        if not line or not line.strip():
            return None

        clean_line = line.strip()

        for parser_name, pattern in PARSERS:
            match = pattern.match(clean_line)
            
            if match:
                data = match.groupdict()
                raw_ts = data.get("timestamp", "")
                level = data.get("level", "INFO").upper()
                message = data.get("message", "")

                timestamp = raw_ts
                try:
                    normalized = normalize_timestamp(raw_ts)
                    if normalized:
                        timestamp = normalized
                except Exception as e:
                    logger.warning(f"Timestamp normalization failed for '{raw_ts}': {e}", exc_info=True)

                metadata = {}
                try:
                    metadata = extract_metadata(message)
                except Exception as e:
                    logger.warning(f"Metadata extraction failed: {e}", exc_info=True)

                return {
                    "timestamp": timestamp,
                    "level": level,
                    "message": message,
                    "metadata": metadata,
                    "parser_type": parser_name,
                    "raw": clean_line
                }

        logger.debug(f"Unparseable log line (no patterns matched): {clean_line[:100]}...")
        return None