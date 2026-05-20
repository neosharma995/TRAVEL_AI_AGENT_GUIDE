# agent/ai_agent.py — Unified Travel Agent (orchestrator only)


import json
import logging
import re
from typing import Dict, Optional
from datetime import datetime
from openai import OpenAI
import os

from agent.tools import TravelTools, TOOL_DEFINITIONS
from agent.ui_cards import card_welcome, fp

# ── Modules ───────────────────────────────────────────────────
from agent.context import (
    WELCOME_KEYWORDS,
    default_context,
    session_key as make_session_key,
    save_context,
    get_missing_field,
    ask_for_field,
)
from agent.intent import extract_intent, extract_pkg_start_date, validate_city
from agent.date_utils import validate_dates, try_parse_guest_count
import agent.hotel_handlers   as hotel
import agent.package_handlers as pkg

logger = logging.getLogger(__name__)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(console_handler)
logger.setLevel(logging.INFO)


# ═══════════════════════════════════════════════════════════════════════════════
# AGENT
# ═══════════════════════════════════════════════════════════════════════════════

class AIHotelAgent:

    def __init__(self):
        self.client          = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.sessions: Dict  = {}
        self.available_tools = TOOL_DEFINITIONS
        logger.info("=" * 60)
        logger.info("UNIFIED TRAVEL AGENT INITIALIZED")
        logger.info("=" * 60)

    # ─────────────────────────────────────────────────────────────
    # INTERNAL HELPERS
    # ─────────────────────────────────────────────────────────────

    def _make_tools(self, business_phone: str) -> TravelTools:
        return TravelTools(display_phone=business_phone)

    def _save(self, state, context):
        save_context(state, context)

    def _reset_to_welcome(self, phone: str, business_phone: str, state):
        key   = make_session_key(phone, business_phone)
        fresh = default_context(business_phone)
        if key in self.sessions:
            self.sessions[key]["context"] = fresh
            self.sessions[key]["history"] = []
        save_context(state, fresh)

    def execute_tool(self, tool_name: str, parameters: Dict, tools: TravelTools) -> Dict:
        logger.info(f"🚀 TOOL: {tool_name} | PARAMS: {json.dumps(parameters, default=str)}")
        try:
            if tool_name == "get_categories":
                return tools.get_categories()
            elif tool_name == "search_hotels_by_category":
                return tools.search_hotels_by_category(
                    parameters.get("category"), parameters.get("location"))
            elif tool_name == "get_hotel_rooms":
                return tools.get_hotel_rooms(parameters.get("hotel_name"))
            elif tool_name == "validate_dates":
                return tools.validate_dates(parameters.get("check_in"), parameters.get("check_out"))
            elif tool_name == "calculate_room_price":
                return tools.calculate_room_price(
                    parameters.get("room"), parameters.get("check_in"),
                    parameters.get("check_out"), parameters.get("guests"))
            elif tool_name == "calculate_meal_price":
                return tools.calculate_meal_price(
                    parameters.get("meal_type"), parameters.get("meal_plan_data"),
                    parameters.get("guests"), parameters.get("nights"))
            else:
                return {"success": False, "error": f"Unknown tool: {tool_name}"}
        except Exception as e:
            logger.error(f"Tool error [{tool_name}]: {e}")
            return {"success": False, "error": str(e)}

    def reset_session(self, phone: str, business_phone: str = "default"):
        key = make_session_key(phone, business_phone)
        if key in self.sessions:
            del self.sessions[key]
            logger.info("🗑️ Session deleted")

    # ─────────────────────────────────────────────────────────────
    # MAIN EXECUTE
    # ─────────────────────────────────────────────────────────────

    def execute(self, phone: str, user_message: str, state: dict = None,
                business_phone: str = "default") -> Dict:

        sk    = make_session_key(phone, business_phone)
        tools = self._make_tools(business_phone)

        logger.info("=" * 60)
        logger.info(f"📱 {phone}  💬 {user_message}")
        logger.info("=" * 60)

        # ── Session init ──────────────────────────────────────────
        if sk not in self.sessions:
            saved = (state or {}).get("data", {})
            ctx   = ({**default_context(business_phone), **saved}
                     if saved and saved.get("business_phone") == business_phone
                     else default_context(business_phone))
            self.sessions[sk] = {"history": [], "context": ctx}
            logger.info("🆕 New session")

        session = self.sessions[sk]
        context = session["context"]
        session["history"].append({"role": "user", "content": user_message})
        msg = user_message.strip().lower()

        # ════════════════════════════════════════════════════════
        #  WELCOME / RESET
        # ════════════════════════════════════════════════════════
        if msg in WELCOME_KEYWORDS:
            if context.get("step") in ("welcome", None) or msg in (
                "hi", "hii", "hello", "hey", "home", "restart",
                "new", "new booking", "reset", "main menu"
            ):
                self._reset_to_welcome(phone, business_phone, state)
                context = self.sessions[sk]["context"]
                return card_welcome()

        svc = context.get("service_type")

        # ── Service type from button ──────────────────────────────
        if msg in ("hotel", "package") and not svc:
            context["service_type"] = msg
            svc = msg
            self._save(state, context)
            missing = get_missing_field(context)
            if missing and missing != "service_type":
                return ask_for_field(missing, context)

        # ════════════════════════════════════════════════════════
        #  HOTEL BUTTON HANDLERS
        # ════════════════════════════════════════════════════════
        if svc == "hotel":

            if user_message.startswith("view_rooms:"):
                hotel_name = user_message.split(":", 1)[1]
                return hotel.handle_view_rooms(hotel_name, context, tools, state, self.execute_tool)

            if user_message.startswith("pick_room:"):
                idx = int(user_message.split(":", 1)[1])
                return hotel.handle_pick_room(idx, context, tools, state, self.execute_tool)

            if msg in ("map", "cp", "ep") and context.get("step") == "select_meal":
                result = hotel.handle_meal_selection(msg, context, tools, state, self.execute_tool)
                if result:
                    return result

            if msg == "change_meal":
                context["step"] = "select_meal"
                self._save(state, context)
                return {
                    "type": "buttons",
                    "content": "*Select your meal plan:*",
                    "buttons": [
                        {"text": "MAP — Breakfast + Dinner", "value": "map"},
                        {"text": "CP  — Breakfast only",     "value": "cp"},
                        {"text": "EP  — No meals",           "value": "ep"},
                    ],
                }

            if msg in ("other_hotels", "back_to_hotels"):
                context["step"] = "show_hotels"
                self._save(state, context)
                return hotel.format_hotels(context)

            if msg == "back_to_categories":
                context["step"] = "show_categories"
                self._save(state, context)
                return hotel.format_categories(context)

            if msg == "change_city":
                return hotel.handle_change_city(context, state)

            if msg == "confirm" and context.get("step") == "final_summary":
                return hotel.confirm_hotel_booking(context, phone, business_phone, state, self._reset_to_welcome)

        # ════════════════════════════════════════════════════════
        #  PACKAGE BUTTON HANDLERS
        # ════════════════════════════════════════════════════════
        if svc == "package":

            if msg == "pkg_generate_pdf":
                return pkg.generate_and_send_pdf(context, phone, business_phone, state)

            # Hotel category selection
            hotel_cats = [c.get("name", "").lower() for c in (context.get("hotel_categories") or [])]
            if msg in hotel_cats and not context.get("hotel_category"):
                context["hotel_category"] = user_message.strip()
                context["step"]           = "pkg_ask_room_category"
                self._save(state, context)
                return pkg.fetch_room_categories(context, tools, state)

            # Room category selection → packages
            room_cats = [c.get("name", "").lower() for c in (context.get("room_categories") or [])]
            if msg in room_cats and not context.get("room_category"):
                context["room_category"] = user_message.strip()
                context["step"]          = "pkg_fetch_packages"
                self._save(state, context)
                return pkg.fetch_packages(context, tools, state)

            # Vehicle selection → price calculation
            if user_message.startswith("select_vehicle_"):
                try:
                    idx      = int(user_message.replace("select_vehicle_", "").strip())
                    vehicles = context.get("vehicles_list", [])
                    if idx < len(vehicles):
                        context["vehicle"] = vehicles[idx]
                        context["step"]    = "pkg_calculate_price"
                        self._save(state, context)
                        return pkg.calculate_and_show_price(context, tools, state)
                except ValueError:
                    pass

            # Package selection → show package vehicles
            if user_message.startswith("select_package_"):
                try:
                    idx  = int(user_message.replace("select_package_", "").strip())
                    pkgs = context.get("packages_list", [])
                    if idx < len(pkgs):
                        context["selected_package"] = pkgs[idx]
                        context["vehicle"]           = None
                        context["step"]              = "pkg_ask_vehicle"
                        self._save(state, context)
                        return pkg.fetch_package_vehicles(context, tools, state)
                except ValueError:
                    pass

            if msg == "pkg_other_packages":
                pkgs     = context.get("packages_list", [])
                selected = context.get("selected_package", {})
                others   = [p for p in pkgs if p.get("id") != selected.get("id")]
                if others:
                    context["packages_list"] = others
                    context["step"]          = "pkg_show_packages"
                    self._save(state, context)
                    from agent.ui_cards import card_pkg_packages
                    return card_pkg_packages(context)
                return {
                    "type": "buttons",
                    "content": f"No other packages available. Continue with *{selected.get('package_name', 'this package')}*?",
                    "buttons": [{"text": "Continue", "value": "pkg_continue_package"}],
                }

            if msg == "pkg_continue_package":
                context["step"] = "pkg_final_summary"
                self._save(state, context)
                from agent.ui_cards import card_pkg_summary
                return card_pkg_summary(context)

            if msg == "pkg_change_vehicle":
                context["vehicle"] = None
                context["step"]    = "pkg_ask_vehicle"
                self._save(state, context)
                return pkg.fetch_package_vehicles(context, tools, state)

            if msg == "pkg_change_hotel":
                context["hotel_category"]  = None
                context["room_category"]   = None
                context["selected_hotels"] = {}
                self._save(state, context)
                return pkg.fetch_hotel_categories(context, tools, state)

            if msg == "pkg_continue_without_vehicle":
                context["vehicle"] = None
                context["step"] = "pkg_calculate_price"
                self._save(state, context)
                return pkg.calculate_and_show_price(context, tools, state)
                

            if msg == "pkg_change_room":
                context["room_category"] = None
                context["step"] = "pkg_ask_room_category"
                self._save(state, context)
                return pkg.fetch_room_categories(context, tools, state)

            
            

            if msg in ("pkg_book_now", "pkg_confirm_package"):
                return pkg.confirm_package_booking(
                    context, phone, business_phone, state, self._reset_to_welcome)

        # ════════════════════════════════════════════════════════
        #  NATURAL LANGUAGE HANDLING
        # ════════════════════════════════════════════════════════
        intent = extract_intent(self.client, user_message)

        # Service type from NL
        if intent.get("service_type") and not svc:
            context["service_type"] = intent["service_type"]
            svc = intent["service_type"]

        # Free-text confirm
        if intent.get("confirm_booking"):
            if svc == "hotel" and context.get("step") == "final_summary":
                return hotel.confirm_hotel_booking(
                    context, phone, business_phone, state, self._reset_to_welcome) 
            if svc == "package" and context.get("step") in ("pkg_show_itinerary", "pkg_final_summary"):
                return pkg.confirm_package_booking(
                    context, phone, business_phone, state, self._reset_to_welcome)

        # Guest update mid-flow
        if intent.get("guests"):
            try:
                new_guests = int(intent["guests"])
                if 1 <= new_guests <= 50:
                    context["guests"] = new_guests
                    logger.info(f"✅ Guests set via LLM: {new_guests}")
                    if svc == "package" and context.get("selected_package") and context.get("pkg_price_details"):
                        return pkg.calculate_and_show_price(context, tools, state)
                    if svc == "hotel" and context.get("selected_room_data") and context.get("price_details"):
                        room = context["selected_room_data"]
                        pr   = self.execute_tool(
                            "calculate_room_price",
                            {"room": room, "check_in": context["check_in"],
                             "check_out": context["check_out"], "guests": new_guests},
                            tools,
                        )
                        if pr.get("success"):
                            context["price_details"] = pr
                            mr = self.execute_tool(
                                "calculate_meal_price",
                                {"meal_type":      context.get("meal_plan", "ep"),
                                 "meal_plan_data": context.get("meal_plan_data", {}),
                                 "guests":         new_guests,
                                 "nights":         pr.get("nights", 1)},
                                tools,
                            )
                            if mr.get("success"):
                                context["meal_details"] = mr
                            self._save(state, context)
                            return hotel.format_summary(context)
            except (TypeError, ValueError):
                pass

        # Bare-number guest shortcut
        if (
            not context.get("guests")
            and context.get("destination")
            and context.get("check_in")
            and (svc == "package" or context.get("check_out"))
        ):
            bare = try_parse_guest_count(user_message)
            if bare is not None:
                context["guests"] = bare
                logger.info(f"✅ Bare-number guest: {bare}")
                self._save(state, context)
                if svc == "hotel":
                    return hotel.proceed_to_categories(context, tools, state, self.execute_tool)
                if svc == "package":
                    return pkg.fetch_hotel_categories(context, tools, state)

        # ── Package start date collection ─────────────────────────
        if svc == "package" and context.get("destination") and not context.get("check_in"):
            date_result = extract_pkg_start_date(self.client, user_message)

            if date_result.get("start_date"):
                context["check_in"]  = date_result["start_date"]
                context["check_out"] = None
                logger.info(f"✅ Package start date: {context['check_in']}")
                self._save(state, context)
                if not context.get("guests"):
                    return ask_for_field("guests", context)
                return pkg.fetch_hotel_categories(context, tools, state)

            elif date_result.get("is_past"):
                self._save(state, context)
                return {
                    "type": "text",
                    "content": (
                        f"⚠️ {date_result.get('error', 'That date is in the past.')}\n\n"
                        f"Please provide a *future* starting date.\n"
                    )
                }
            else:
                bare = try_parse_guest_count(user_message)
                if bare is not None and not context.get("guests"):
                    context["guests"] = bare
                    self._save(state, context)
                    return ask_for_field("dates", context)
                self._save(state, context)
                return {
                    "type": "text",
                    "content": (
                        f"Please share your *trip starting date* for {context.get('destination')}.\n\n"
                    )
                }

        # ── City validation ───────────────────────────────────────
        city_to_check = intent.get("city") or (
            intent.get("possible_city") if not context.get("destination") and svc else None
        )
        if city_to_check:
            city_candidate = city_to_check.title()
            city_check     = validate_city(self.client, city_candidate)
            if city_check.get("valid"):
                context["destination"] = city_check.get("corrected") or city_candidate
                logger.info(f"✅ City accepted: {context['destination']}")
            else:
                error_msg = city_check.get("message") or (
                    f"I don't recognise *{city_candidate}* as a city. Please check and try again."
                )
                self._save(state, context)
                return {"type": "text", "content": f"⚠️ {error_msg}"}

        # ── Hotel date merge + validation ─────────────────────────
        if svc != "package":
            if intent.get("check_in"):
                context["check_in"]  = intent["check_in"]
            if intent.get("check_out"):
                context["check_out"] = intent["check_out"]
            if context.get("check_in") and context.get("check_out"):
                v = validate_dates(context["check_in"], context["check_out"])
                if not v.get("valid"):
                    context["check_in"] = context["check_out"] = None
                    self._save(state, context)
                    return {
                        "type": "text",
                        "content": (
                            f"⚠️ {v['error']} Please provide valid dates.\n\n"
                        )
                    }

        # ── Guest fallback ────────────────────────────────────────
        if not context.get("guests"):
            bare = try_parse_guest_count(user_message)
            if bare is not None:
                context["guests"] = bare
                logger.info(f"✅ Guest fallback: {bare}")

        # ── Hotel: category selection from text ───────────────────
        if svc == "hotel" and context.get("step") == "show_categories" and context.get("categories_from_api"):
            for cat in context["categories_from_api"]:
                if cat.get("name", "").lower() == msg:
                    context["selected_category"] = cat["name"]
                    result = self.execute_tool(
                        "search_hotels_by_category",
                        {"category": cat["name"], "location": context.get("destination")},
                        tools,
                    )
                    if result.get("success") and result.get("hotels"):
                        context["hotels_list"] = result["hotels"]
                        context["step"]        = "show_hotels"
                        self._save(state, context)
                        return hotel.format_hotels(context)
                    self._save(state, context)
                    return hotel.format_categories(context, error_category=cat["name"])

        # ── Hotel: select by number ───────────────────────────────
        if svc == "hotel" and context.get("step") == "show_hotels" and context.get("hotels_list"):
            m = re.search(r"(\d+)", user_message)
            if m:
                idx = int(m.group(1)) - 1
                if 0 <= idx < len(context["hotels_list"]):
                    hotel_name = context["hotels_list"][idx]["name"]
                    context["selected_hotel"] = hotel_name
                    result = self.execute_tool("get_hotel_rooms", {"hotel_name": hotel_name}, tools)
                    if result.get("success"):
                        context["rooms_list"]     = result.get("rooms", [])
                        context["meal_plan_data"] = result.get("meal_plan", {})
                        context["step"]           = "show_rooms"
                        self._save(state, context)
                        return hotel.format_rooms(context)

        self._save(state, context)

        # ── Auto-advance ──────────────────────────────────────────
        missing = get_missing_field(context)
        if not missing:
            if svc == "hotel" and context.get("step") in ("collect_info", "welcome"):
                return hotel.proceed_to_categories(context, tools, state, self.execute_tool)
            if svc == "package" and not context.get("hotel_category"):
                return pkg.fetch_hotel_categories(context, tools, state)

        if missing:
            return ask_for_field(missing, context)

        return card_welcome()