# agent/hotel_handlers.py


import logging
from typing import Dict, Optional

from agent.ui_cards import (
    card_hotel_categories,
    card_hotel_list,
    card_hotel_rooms,
    card_hotel_summary,
)
from agent.context import save_context
from agent.tools import TravelTools

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# FORMATTERS  (thin wrappers around ui_cards)
# ─────────────────────────────────────────────────────────────

def format_categories(context: Dict, error_category: str = None) -> Dict:
    return card_hotel_categories(context, error_category)


def format_hotels(context: Dict) -> Dict:
    return card_hotel_list(context)


def format_rooms(context: Dict) -> Dict:
    return card_hotel_rooms(context)


def format_summary(context: Dict) -> Dict:
    return card_hotel_summary(context)


# ─────────────────────────────────────────────────────────────
# PROCEED TO CATEGORIES
# ─────────────────────────────────────────────────────────────

def proceed_to_categories(context: Dict, tools: TravelTools, state, execute_tool_fn) -> Dict:
    """Fetch hotel categories from API and show selection card."""
    result = execute_tool_fn("get_categories", {}, tools)
    if result.get("success"):
        context["categories_from_api"] = result.get("categories", [])
        # Store partner email from API user object into context
        partner_email = result.get("partner_email", "")
        if partner_email and not context.get("partner_email"):
            context["partner_email"] = partner_email
            logger.info(f"📧 Stored partner_email from hotel categories API: {partner_email}")
        context["step"] = "show_categories"
        save_context(state, context)
        return format_categories(context)
    return {"type": "text", "content": "Trouble fetching hotel categories. Please type 'retry'."}


# ─────────────────────────────────────────────────────────────
# VIEW ROOMS FOR A HOTEL
# ─────────────────────────────────────────────────────────────

def handle_view_rooms(hotel_name: str, context: Dict, tools: TravelTools, state, execute_tool_fn) -> Dict:
    """Fetch rooms for a hotel and show room cards."""
    context["selected_hotel"] = hotel_name
    context["hotel_page"] = 0
    result = execute_tool_fn("get_hotel_rooms", {"hotel_name": hotel_name}, tools)
    
    if result.get("success") and result.get("rooms"):
        context["rooms_list"]     = result.get("rooms", [])
        context["meal_plan_data"] = result.get("meal_plan", {})
        context["hotel_tax"]      = result.get("tax", "0")
        context["step"]           = "show_rooms"
        context["rooms_page"] = 0
        # Store partner email from hotel rooms API if not already set
        partner_email = result.get("partner_email", "")
        if partner_email and not context.get("partner_email"):
            context["partner_email"] = partner_email
            logger.info(f"📧 Stored partner_email from hotel rooms API: {partner_email}")
        save_context(state, context)
        return format_rooms(context)

    return {
        "type": "buttons",
        "content": f"⚠️ No rooms available at *{hotel_name}*.\n\nPlease try another hotel:",
        "buttons": [
            {"text": "Try Other Hotels", "value": "other_hotels"},
            {"text": "⬅Back to Categories", "value": "back_to_categories"},
            {"text": "Change City", "value": "change_city"},
        ]
    }


# ─────────────────────────────────────────────────────────────
# PICK A ROOM
# ─────────────────────────────────────────────────────────────

def handle_pick_room(idx: int, context: Dict, tools: TravelTools, state, execute_tool_fn) -> Dict:
    """Select a room by index, calculate price, prompt for meal plan."""
    rooms = context.get("rooms_list", [])
    if idx >= len(rooms):
        return {"type": "text", "content": "Invalid room selection."}

    room = rooms[idx]
    context["selected_room_data"] = room
    context["selected_room"]      = f"{room.get('category')} – {room.get('type')}"

    price_result = execute_tool_fn(
        "calculate_room_price",
        {
            "room":      room,
            "check_in":  context["check_in"],
            "check_out": context["check_out"],
            "guests":    context["guests"],
        },
        tools,
    )
    if not price_result.get("success"):
        return {"type": "text", "content": "Couldn't calculate the price. Please try again."}

    context["price_details"] = price_result
    context["step"]          = "select_meal"
    save_context(state, context)

    extra_info = ""
    if price_result.get("extra_people", 0) > 0:
        extra_info = f"\n  └ Extra ({price_result['extra_people']} persons): Rs.{price_result['extra_total']:,.0f}"

    return {
        "type": "buttons",
        "content": (
            f"*Room Selected*\n\n"
            f"*{context.get('selected_hotel')}*\n"
            f"*Room Category* {room.get('category')}\n"
            f"*Room Type* {room.get('type')}\n"
            f"*Room Total* Rs.{price_result['grand_total']:,.0f} "
            f"({price_result['nights']} nights / {price_result['rooms_needed']} room(s)){extra_info}\n\n"
            f"Select your *meal plan*"
        ),
        "buttons": [
            {"text": "MAP — Breakfast + Dinner", "value": "map"},
            {"text": "CP  — Breakfast only",     "value": "cp"},
            {"text": "EP  — No meals",           "value": "ep"},
        ],
    }


# ─────────────────────────────────────────────────────────────
# SELECT MEAL PLAN
# ─────────────────────────────────────────────────────────────

def handle_meal_selection(meal_type: str, context: Dict, tools: TravelTools, state, execute_tool_fn) -> Optional[Dict]:
    """Calculate meal cost and show final hotel summary."""
    meal_result = execute_tool_fn(
        "calculate_meal_price",
        {
            "meal_type":      meal_type,
            "meal_plan_data": context.get("meal_plan_data", {}),
            "guests":         context.get("guests", 1),
            "nights":         context.get("price_details", {}).get("nights", 1),
        },
        tools,
    )
    if meal_result.get("success"):
        context["meal_plan"]    = meal_type
        context["meal_details"] = meal_result
        context["step"]         = "final_summary"
        save_context(state, context)
        return format_summary(context)
    return None


# ─────────────────────────────────────────────────────────────
# CONFIRM HOTEL BOOKING
# ─────────────────────────────────────────────────────────────

def confirm_hotel_booking(context: Dict, phone: str, business_phone: str, state, reset_fn) -> Dict:
    from datetime import datetime
    from services.email_service import send_admin_booking_alert

    ref = f"HOTEL{datetime.now().strftime('%Y%m%d%H%M%S')}"
    logger.info(f"✅ HOTEL BOOKING CONFIRMED: {ref}")

    pd          = context.get("price_details", {})
    meal_d      = context.get("meal_details", {})
    room_data   = context.get("selected_room_data", {})

    # Price breakdown
    room_total      = pd.get("room_total", 0)
    extra_total     = pd.get("extra_total", 0)
    meal_total      = meal_d.get("total_meal_price", 0)
    subtotal        = room_total + extra_total + meal_total
    tax_rate        = float(str(context.get("hotel_tax", "0")).replace("%", "") or 0)
    tax_amount      = round(subtotal * tax_rate / 100) if tax_rate > 0 else 0
    grand_total     = subtotal + tax_amount

    booking_details = {
        "package_name":         f"Hotel: {context.get('selected_hotel', 'N/A')}",
        "package_id":           ref,
        "package_price":        f"Rs.{grand_total:,.0f}",
        "per_person_price":     "N/A",
        "travel_dates":         f"{context.get('check_in')} → {context.get('check_out')}",
        "travellers":           context.get("guests", "N/A"),
        "destinations":         context.get("destination", "N/A"),
        # Rich hotel details
        "hotel_name":           context.get("selected_hotel", "N/A"),
        "hotel_category":       context.get("selected_category", "N/A"),
        "room_category":        room_data.get("category", "N/A"),
        "room_type":            room_data.get("type", "N/A"),
        "nights":               pd.get("nights", "N/A"),
        "rooms_needed":         pd.get("rooms_needed", 1),
        "price_per_night":      pd.get("price_per_night_per_room", 0),
        "season_used":          pd.get("season_used", "Regular Rate"),
        "extra_people":         pd.get("extra_people", 0),
        "extra_total":          extra_total,
        "room_total":           room_total,
        "meal_plan":            meal_d.get("meal_name", context.get("meal_plan", "N/A")),
        "meal_total":           meal_total,
        "subtotal":             subtotal,
        "tax_rate":             tax_rate,
        "tax_amount":           tax_amount,
        "grand_total":          grand_total,
    }

    admin_email = context.get("partner_email")
    logger.info(f"📧 Sending booking email to: {admin_email}")

    send_admin_booking_alert(
        booking_details=booking_details,
        customer_phone=phone,
        admin_email=admin_email,
    )

    reset_fn(phone, business_phone, state)
    return {
        "type": "text",
        "content": (
            f"✅ *BOOKING CONFIRMED!*\n\n"
            f"Reference: *{ref}*\n\n"
            f"Thank you for booking with us! 🎉\n\n"
            f"Type 'hi' to start a new booking."
        ),
    }


# ─────────────────────────────────────────────────────────────
# CHANGE CITY
# ─────────────────────────────────────────────────────────────

def handle_change_city(context: Dict, state) -> Dict:
    """Clear hotel-related context and ask for a new city."""
    for k in ("destination", "selected_category", "selected_hotel", "hotels_list",
              "rooms_list", "selected_room_data", "meal_plan", "meal_details",
              "price_details", "categories_from_api"):
        context[k] = None
    context["step"] = "collect_info"
    context["hotel_page"] = 0
    save_context(state, context)
    return {"type": "text", "content": "Which city would you like to search hotels in?"}