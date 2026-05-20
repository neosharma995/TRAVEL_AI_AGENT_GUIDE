# agent/context.py — Session management and default context

from typing import Dict

WELCOME_KEYWORDS = {
    "hi", "hii", "hello", "hey", "helo", "hiya", "howdy",
    "start", "begin", "help", "menu", "home", "restart",
    "new booking", "new", "reset", "back", "main menu",
}


def default_context(business_phone: str = "default") -> Dict:
    """Single flat context for both hotel and package flows."""
    return {
        # ── routing ──
        "service_type": None,           
        "flow": "initial",
        "step": "welcome",
        "business_phone": business_phone,
        # ── shared fields ──
        "destination": None,
        "check_in": None,
        "check_out": None,
        "guests": None,
        # ── hotel-only fields ──
        "selected_category": None,
        "selected_hotel": None,
        "selected_room_data": None,
        "meal_plan": None,
        "meal_plan_data": None,
        "price_details": None,
        "meal_details": None,
        "categories_from_api": None,
        "rooms_list": None,
        "hotels_list": None,
        # ── package-only fields ──
        "hotel_category": None,
        "room_category": None,
        "vehicle_category": None,
        "vehicle_slug": None,
        "vehicle": None,
        "packages_list": None,
        "selected_package": None,
        "pkg_price_details": None,
        "hotel_categories": None,
        "room_categories": None,
        "vehicle_types": None,
        "vehicles_list": None,
        "hotel_data_cache": {},
        "selected_hotels": {},
        "date_error": None,
        "pkg_awaiting_start_date": False,
    }


def session_key(phone: str, business_phone: str) -> str:
    return f"{business_phone}:{phone}"


def save_context(state, context: Dict):
    """Persist context into the state dict (passed in from caller)."""
    if state is not None:
        state["data"] = context


def get_missing_field(context: Dict):
    """
    Returns the first missing required field name, or None if all collected.
    Hotel:   service_type → destination → check_in + check_out → guests
    Package: service_type → destination → check_in (only) → guests
    """
    if not context.get("service_type"):
        return "service_type"
    if not context.get("destination"):
        return "destination"
    svc = context.get("service_type")
    if svc == "package":
        if not context.get("check_in"):
            return "dates"
    else:
        if not context.get("check_in") or not context.get("check_out"):
            return "dates"
    if not context.get("guests"):
        return "guests"
    return None


def ask_for_field(field: str, context: Dict) -> Dict:
    """Return the appropriate prompt message for the missing field."""
    from agent.ui_cards import card_welcome
    svc = context.get("service_type", "")

    if field == "service_type":
        return card_welcome()

    if field == "destination":
        if svc == "package":
            return {"type": "text", "content": "Which destination are you looking for a package in?"}
        return {"type": "text", "content": "Which city are you looking for hotels in?"}

    if field == "dates":
        dest = context.get("destination", "")
        if svc == "package":
            return {
                "type": "text",
                "content": (
                    f"*When would you like to start your trip?*\n\n"
                    "Please share your *starting date*.\n"
                )
            }
        return {
            "type": "text",
            "content": f"What are your check-in and check-out dates for {dest}?"
        }

    if field == "guests":
        return {"type": "text", "content": "How many guests will be travelling?"}

    return {"type": "text", "content": "How can I help with your booking?"}