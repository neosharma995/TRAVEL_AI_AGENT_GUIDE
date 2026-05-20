# agent/pricing.py  

import math
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from agent.date_utils import parse_date_flexible

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# SEASON MATCHING
# ─────────────────────────────────────────────────────────────

def find_matching_season(
    seasons: List[Dict],
    check_in_date: datetime,
    check_out_date: datetime
) -> Optional[Dict]:
    """
    Match check_in/check_out against a seasons list.
    Compares month+day only (ignores year on season dates).
    Supports wrap-around seasons (e.g. Dec–Mar).
    Returns the first matched season dict or None.
    """
    try:
        for season in seasons:
            season_start = parse_date_flexible(season.get("starting_date", ""))
            season_end   = parse_date_flexible(season.get("end_date", ""))
            if not season_start or not season_end:
                continue

            s_md  = (season_start.month, season_start.day)
            e_md  = (season_end.month,   season_end.day)
            ci_md = (check_in_date.month,  check_in_date.day)
            co_md = (check_out_date.month, check_out_date.day)

            if s_md > e_md:                          
                if ci_md >= s_md or ci_md <= e_md:
                    return season
                if co_md >= s_md or co_md <= e_md:
                    return season
            else:                                    
                if s_md <= ci_md <= e_md:
                    return season
                if s_md <= co_md <= e_md:
                    return season
        return None
    except Exception as e:
        logger.error(f"find_matching_season error: {e}")
        return None


# ─────────────────────────────────────────────────────────────
# ROOM SEASONAL PRICE
# ─────────────────────────────────────────────────────────────

def get_room_seasonal_price(
    room: Dict,
    check_in_date: datetime,
    check_out_date: datetime
) -> Tuple[float, float, str]:
    """
    Returns (price_per_night, extra_person_price, season_name)
    for a room dict that contains a seasons[] list.
    Falls back to base_price / extra_person_price if no season matches.
    """
    base_price = float(room.get("base_price", 0))
    base_extra = float(room.get("extra_person_price", 0))

    matched = find_matching_season(room.get("seasons", []), check_in_date, check_out_date)
    if matched:
        try:
            price = float(matched.get("price", base_price))
            extra = float(matched.get("extra_price", base_extra))
            name  = matched.get("season_name", "Seasonal Rate")
            return price, extra, name
        except (ValueError, TypeError):
            pass

    return base_price, base_extra, "Regular Rate"


# ─────────────────────────────────────────────────────────────
# VEHICLE SEASONAL PRICE
# ─────────────────────────────────────────────────────────────

def get_vehicle_seasonal_price(
    vehicle: Dict,
    check_in_date: datetime,
    check_out_date: datetime
) -> Tuple[float, str]:
    """
    Returns (price_per_day, season_name) for a vehicle dict.
    Reads vehicle_price or price field.
    Falls back to base price if no season matches.
    """
    raw_price  = vehicle.get("price", vehicle.get("vehicle_price", "0"))
    base_price = float(str(raw_price).replace(",", ""))

    matched = find_matching_season(vehicle.get("seasons", []), check_in_date, check_out_date)
    if matched:
        try:
            price = float(str(matched.get("price", base_price)).replace(",", ""))
            name  = matched.get("season_name", "Seasonal Rate")
            return price, name
        except (ValueError, TypeError):
            pass

    return base_price, "Regular Rate"


# ─────────────────────────────────────────────────────────────
# ROOM OCCUPANCY CALCULATION
# ─────────────────────────────────────────────────────────────

def calculate_rooms_and_extra(guests: int, min_cap: int, max_cap: int) -> Dict:
    """
    Calculate number of rooms needed and extra persons above min capacity.
    Returns {"rooms_needed": int, "extra_persons_total": int}
    """
    rooms_needed  = math.ceil(guests / max_cap)
    extra_persons = max(0, guests - (rooms_needed * min_cap))
    return {"rooms_needed": rooms_needed, "extra_persons_total": extra_persons}


# ─────────────────────────────────────────────────────────────
# FULL ROOM PRICE CALCULATION
# ─────────────────────────────────────────────────────────────

def calculate_room_price(
    room: Dict,
    check_in: str,
    check_out: str,
    guests: int
) -> Dict:
    """
    Full room price calculation with season matching.
    Mirrors TravelTools.calculate_room_price but uses this module's helpers.
    Returns the same dict shape as the tool method.
    """
    try:
        check_in_date  = datetime.strptime(check_in,  "%Y-%m-%d")
        check_out_date = datetime.strptime(check_out, "%Y-%m-%d")
        nights = (check_out_date - check_in_date).days

        if nights <= 0:
            return {"success": False, "error": "Check-out must be after check-in"}

        min_capacity = int(room.get("minimum_capacity", room.get("min_capacity", 1)))
        max_capacity = int(room.get("maximum_capacity", room.get("max_capacity", 2)))

        price_per_night, extra_price, season_name = get_room_seasonal_price(
            room, check_in_date, check_out_date
        )

        rooms_needed = math.ceil(guests / max_capacity)
        extra_people = max(0, guests - (rooms_needed * min_capacity))
        room_total   = rooms_needed * price_per_night * nights
        extra_total  = extra_people * extra_price * nights
        grand_total  = room_total + extra_total

        return {
            "success": True,
            "nights": nights,
            "guests": guests,
            "rooms_needed": rooms_needed,
            "min_capacity": min_capacity,
            "max_capacity": max_capacity,
            "extra_people": extra_people,
            "price_per_night_per_room": price_per_night,
            "extra_price_per_night": extra_price,
            "room_total": room_total,
            "extra_total": extra_total,
            "grand_total": grand_total,
            "season_used": season_name,
        }
    except Exception as e:
        logger.error(f"calculate_room_price error: {e}")
        return {"success": False, "error": str(e)}