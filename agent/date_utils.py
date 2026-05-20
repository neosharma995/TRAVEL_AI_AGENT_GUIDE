# agent/date_utils.py — Date validation, package checkout derivation, guest parsing

import re
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def validate_dates(check_in: str, check_out: str) -> Dict:
    """
    Validate that check_in is future and check_out is after check_in.
    Returns {"valid": bool, "nights": int, "error": str|None}
    """
    try:
        today = datetime.now().date()
        ci    = datetime.strptime(check_in,  "%Y-%m-%d").date()
        co    = datetime.strptime(check_out, "%Y-%m-%d").date()
        if ci < today:
            return {"valid": False, "error": f"Check-in date {check_in} is in the past."}
        if co <= ci:
            return {"valid": False, "error": "Check-out must be after check-in."}
        return {"valid": True, "nights": (co - ci).days}
    except ValueError:
        return {"valid": False, "error": "Invalid date format."}


def derive_pkg_checkout(start_date_str: str, itinerary: List[Dict]) -> str:
    """
    Auto-derive check_out from package itinerary.
    nights = len(itinerary) - 1  (last day is usually return/departure).
    Returns YYYY-MM-DD string.
    """
    try:
        start_dt   = datetime.strptime(start_date_str, "%Y-%m-%d")
        total_days = len(itinerary)
        nights     = max(total_days - 1, 1)
        check_out  = start_dt + timedelta(days=nights)
        logger.info(
            f"📅 Package checkout derived: start={start_date_str} "
            f"itinerary_days={total_days} nights={nights} "
            f"checkout={check_out.strftime('%Y-%m-%d')}"
        )
        return check_out.strftime("%Y-%m-%d")
    except Exception as e:
        logger.error(f"derive_pkg_checkout error: {e}")
        try:
            return (datetime.strptime(start_date_str, "%Y-%m-%d") + timedelta(days=3)).strftime("%Y-%m-%d")
        except Exception:
            return start_date_str


def try_parse_guest_count(message: str) -> Optional[int]:
    """
    Try to parse a guest count from a free-text message.
    Returns int (1-50) or None if not found.
    """
    stripped = message.strip()

    # Bare integer only
    if re.fullmatch(r'\d+', stripped):
        val = int(stripped)
        return val if 1 <= val <= 50 else None

    # Number with qualifier words, but NOT date-like context
    m = re.search(
        r'\b(?:just|only|around|about|approx(?:imately)?|we\s+are|there\s+are|total|party\s+of)?\s*(\d{1,2})\b',
        stripped, re.IGNORECASE,
    )
    if m and not re.search(
        r'\bto\b|\bjune\b|\bjuly\b|\baug\b|\bjan\b|\bfeb\b|\bmar\b|\bapr\b'
        r'|\bmay\b|\bsep\b|\boct\b|\bnov\b|\bdec\b',
        stripped, re.IGNORECASE
    ):
        val = int(m.group(1))
        return val if 1 <= val <= 50 else None

    return None


def parse_date_flexible(date_str: str) -> Optional[datetime]:
    """
    Parse a date string in multiple formats.
    Returns datetime or None.
    """
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None