# agent/intent.py — LLM-powered intent extraction and city/date validation

import json
import logging
from datetime import datetime, timedelta
from typing import Dict

from agent.prompts import (
    INTENT_EXTRACTION_PROMPT,
    PKG_DATE_EXTRACTION_PROMPT,
    CITY_VALIDATION_PROMPT,
)

logger = logging.getLogger(__name__)


def extract_intent(client, message: str) -> Dict:
    """
    Extract service_type, city, dates, guests, confirm_booking from free text.
    Returns a dict with those keys (any can be None).
    """
    today = datetime.now().strftime("%Y-%m-%d")
    prompt = INTENT_EXTRACTION_PROMPT.format(today=today, message=message)
    try:
        resp = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            response_format={"type": "json_object"},
            max_tokens=300,
        )
        result = json.loads(resp.choices[0].message.content)
        logger.info(f"🧠 Intent: {result}")
        return result
    except Exception as e:
        logger.error(f"Intent extraction error: {e}")
        return {
            "service_type": None, "city": None,
            "check_in": None, "check_out": None,
            "guests": None, "confidence": "low",
            "confirm_booking": False, "possible_city": None,
        }


def extract_pkg_start_date(client, message: str) -> Dict:
    """
    Extract ONLY a single starting date for the package flow.
    Returns {"start_date": "YYYY-MM-DD"|None, "is_past": bool, "error": str|None}
    """
    today     = datetime.now()
    tomorrow  = today + timedelta(days=1)
    after_4   = today + timedelta(days=4)
    next_week = today + timedelta(days=7)
    month_name = today.strftime("%B")

    prompt = PKG_DATE_EXTRACTION_PROMPT.format(
        today=today.strftime("%Y-%m-%d"),
        current_month_name=month_name,
        current_year=today.year,
        tomorrow=tomorrow.strftime("%Y-%m-%d"),
        after_4_days=after_4.strftime("%Y-%m-%d"),
        next_week=next_week.strftime("%Y-%m-%d"),
        message=message,
    )
    try:
        resp = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            response_format={"type": "json_object"},
            max_tokens=100,
        )
        result = json.loads(resp.choices[0].message.content)
        logger.info(f"📅 Pkg start date: {result}")

        # Hard-check: reject today or past
        if result.get("start_date"):
            try:
                sd = datetime.strptime(result["start_date"], "%Y-%m-%d").date()
                if sd <= today.date():
                    return {
                        "start_date": None,
                        "is_past": True,
                        "error": f"*{result['start_date']}* is today or in the past. Please provide a future date."
                    }
            except ValueError:
                pass
        return result
    except Exception as e:
        logger.error(f"Pkg date extraction error: {e}")
        return {"start_date": None, "is_past": False, "error": None}


def validate_city(client, city: str) -> Dict:
    """
    Validate whether a city string is a real place.
    Returns {"valid": bool, "corrected": str|None, "message": str|None}
    """
    try:
        resp = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": CITY_VALIDATION_PROMPT.format(city=city)}],
            temperature=0.0,
            response_format={"type": "json_object"},
            max_tokens=100,
        )
        result = json.loads(resp.choices[0].message.content)
        logger.info(f"🏙️ City validation '{city}': {result}")
        return result
    except Exception:
        return {"valid": True, "corrected": None, "message": None}