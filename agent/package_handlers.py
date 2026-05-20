# agent/package_handlers.py  

import logging
from datetime import datetime
from typing import Dict, List, Optional
import os
from agent.context import save_context
from agent.date_utils import derive_pkg_checkout
from agent.pricing import (
    get_room_seasonal_price,
    get_vehicle_seasonal_price,
    calculate_rooms_and_extra,
    find_matching_season,
)
from agent.ui_cards import card_pkg_packages, card_pkg_summary, card_vehicles_list, fp
from agent.tools import TravelTools

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# HOTEL CATEGORIES
# ─────────────────────────────────────────────────────────────

def fetch_hotel_categories(context: Dict, tools: TravelTools, state) -> Dict:
    result = tools.get_categories()
    context["hotel_categories"] = result.get("categories", [])
    if not context["hotel_categories"]:
        return {"type": "text", "content": "No hotel categories available. Please try again later."}
    buttons = [{"text": c["name"], "value": c["name"]} for c in context["hotel_categories"]]
    context["step"] = "pkg_ask_hotel_category"
    save_context(state, context)
    return {
        "type": "buttons_grid",
        "content": (
            f"*SELECT HOTEL CATEGORY*\n\n"
            f"Choose your preferred hotel type"
        ),
        "buttons": buttons,
    }


# ─────────────────────────────────────────────────────────────
# ROOM CATEGORIES
# ─────────────────────────────────────────────────────────────

def fetch_room_categories(context: Dict, tools: TravelTools, state) -> Dict:
    result = tools.get_room_categories()
    logger.info(f"Room categories API response: {result}")
    context["room_categories"] = result.get("room_categories", []) if result.get("success") else []
    if not context["room_categories"]:
        return {"type": "text", "content": "No room categories available. Please try again later."}
    buttons = [{"text": c["name"], "value": c["name"]} for c in context["room_categories"] if c.get("name")]
    context["step"] = "pkg_ask_room_category"
    save_context(state, context)
    return {
        "type": "buttons_grid",
        "content": (
            f"*SELECT ROOM CATEGORY*\n\n"
            f"*Hotel* {context.get('hotel_category')}\n\n"
            f"Choose your preferred room type"
        ),
        "buttons": buttons,
    }


# ─────────────────────────────────────────────────────────────
# PACKAGES
# ─────────────────────────────────────────────────────────────

def fetch_packages(context: Dict, tools: TravelTools, state) -> Dict:
    try:
        cities = context.get("cities", [])
        result = tools.get_packages(context["destination"], cities=cities)
        if not result.get("success"):
            return {"type": "text", "content": "Unable to fetch packages. Please try again."}
        matched = result.get("packages", [])
        context["packages_list"] = matched
        if matched:
            context["step"] = "pkg_show_packages"
            save_context(state, context)
            return card_pkg_packages(context)
        
         
        return {
            "type": "buttons",
            "content": (
                f"⚠️ No packages found for *{context.get('destination')}* with:\n"
                f"• Hotel Category: *{context.get('hotel_category')}*\n"
                f"• Room Category: *{context.get('room_category')}*\n\n"
                f"What would you like to do?"
            ),
            "buttons": [
                {"text": "🏨 Change Hotel Category", "value": "pkg_change_hotel"},
                {"text": "🛏️ Change Room Category", "value": "pkg_change_room"},
                {"text": "🏙️ Change Destination", "value": "change_city"},
            ]
        }
    except Exception as e:
        logger.error(f"fetch_packages error: {e}")
        return {"type": "text", "content": "Unable to fetch packages. Please try again."}

# ─────────────────────────────────────────────────────────────
# PACKAGE VEHICLES 
# ─────────────────────────────────────────────────────────────

def fetch_package_vehicles(context: Dict, tools: TravelTools, state) -> Dict:
    """
    Read vehicles directly from selected_package["vehicles"].
    Each item is a full object: vehicle_name, vehicle_image, vehicle_price,
    seater_capacity, seasons[].
    Normalise to the shape card_vehicles_list expects.
    """
    try:
        pkg          = context.get("selected_package", {})
        raw_vehicles = pkg.get("vehicles", [])

        if not raw_vehicles:
            return {
                "type": "buttons",
                "content": (
                    f"⚠️ No vehicles are included in *{pkg.get('package_name', 'this package')}*.\n\n"
                    f"You can continue with the booking without a vehicle, or choose a different package."
                ),
                "buttons": [
                    {"text": "✅ Continue", "value": "pkg_continue_without_vehicle"},
                    {"text": "📦 Other Packages", "value": "pkg_other_packages"},
                ]
            }

        normalised = []
        for v in raw_vehicles:
            if isinstance(v, str):
                continue
            normalised.append({
                "name":             v.get("vehicle_name", v.get("name", "Vehicle")),
                "image":            v.get("vehicle_image", v.get("image", "")),
                "price":            v.get("vehicle_price", v.get("price", "0")),
                "seater_capacity":  v.get("seater_capacity", v.get("capacity", "")),
                "seasons":          v.get("seasons", []),
                "vehicle_name":     v.get("vehicle_name", ""),
                "vehicle_slug":     v.get("vehicle_slug", ""),
                "vehicle_category": v.get("vehicle_category", ""),
            })

        if not normalised:
            return {
                "type": "buttons",
                "content": "⚠️ No valid vehicles available for this package.\n\nWould you like to continue without a vehicle?",
                "buttons": [
                    {"text": "✅ Continue", "value": "pkg_continue_without_vehicle"},
                ]
            }

        context["vehicles_list"] = normalised
        context["step"]          = "pkg_ask_vehicle"
        save_context(state, context)
        return card_vehicles_list(context)

    except Exception as e:
        logger.error(f"fetch_package_vehicles error: {e}", exc_info=True)
        return {
            "type": "buttons",
            "content": f"⚠️ Error loading vehicles: {str(e)}\n\nWould you like to continue without a vehicle?",
            "buttons": [
                {"text": "✅ Continue Without Vehicle", "value": "pkg_continue_without_vehicle"},
                {"text": "📦 Other Packages", "value": "pkg_other_packages"},
            ]
        }


# ─────────────────────────────────────────────────────────────
# HOTEL LOOKUP FOR A STAY LOCATION
# ─────────────────────────────────────────────────────────────

def get_hotel_for_location(
    location: str,
    hotel_category: str,
    room_category: str,
    tools: TravelTools
) -> Optional[Dict]:
    """
    Find the first hotel in a location that matches hotel_category and has
    a room matching room_category. Returns combined hotel+room+meal_plan dict.
    """
    try:
        result = tools.get_hotels_in_location_for_package(location, hotel_category)
        if result.get("success") and result.get("hotels"):
            for hotel in result["hotels"]:
                hotel_name   = hotel.get("name")
                rooms_result = tools.get_hotel_rooms(hotel_name)
                if rooms_result.get("success"):
                    for room in rooms_result.get("rooms", []):
                        if room.get("category", "").lower() == room_category.lower():
                            return {
                                "hotel":         hotel,
                                "room":          room,
                                "hotel_name":    hotel_name,
                                "room_category": room.get("category"),
                                "meal_plan":     rooms_result.get("meal_plan", {}),
                            }
        return None
    except Exception as e:
        logger.error(f"get_hotel_for_location error: {e}")
        return None


# ─────────────────────────────────────────────────────────────
# PRICE CALCULATION
# ─────────────────────────────────────────────────────────────

def calculate_and_show_price(context: Dict, tools: TravelTools, state) -> Dict:
    try:
        pkg            = context.get("selected_package", {})
        itinerary      = pkg.get("itinerary", [])
        check_in_str   = context.get("check_in")
        guests         = context.get("guests", 1)
        hotel_category = context.get("hotel_category")
        room_category  = context.get("room_category")
        vehicle        = context.get("vehicle", {})

        if not check_in_str:
            return {"type": "text", "content": "⚠️ Start date missing. Please provide your travel start date."}

        check_out_str = derive_pkg_checkout(check_in_str, itinerary)
        context["check_out"] = check_out_str
        logger.info(f"📦 Package dates: {check_in_str} → {check_out_str}")

        check_in_dt  = datetime.strptime(check_in_str,  "%Y-%m-%d")
        check_out_dt = datetime.strptime(check_out_str, "%Y-%m-%d")
        nights       = (check_out_dt - check_in_dt).days

        # ─────────────────────────────────────────────────────────
        # STEP 1: Categorise each itinerary day
        # ─────────────────────────────────────────────────────────
        hotel_locations   = {}   # location → nights count
        vehicle_days      = 0    # days where user-selected vehicle applies
        embedded_vehicles = []   # list of {type, vehicle_dict, day_label}

        for day in itinerary:
            day_label   = day.get("day", "")
            has_volvo   = "volvo"   in day
            has_vehicle = "vehicle" in day
            stay_loc    = day.get("stay_location", "")
            v_include   = day.get("vehicle_include", "") == "Yes"

            if has_volvo:
                # Day 0 type: overnight bus — only volvo price, no hotel, no user vehicle
                embedded_vehicles.append({
                    "type":    "volvo",
                    "data":    day["volvo"],
                    "day":     day_label,
                    "title":   day.get("title", ""),
                })

            elif has_vehicle:
                # Day 3 type: return vehicle — only that vehicle price, no hotel, no user vehicle
                embedded_vehicles.append({
                    "type":  "vehicle",
                    "data":  day["vehicle"],
                    "day":   day_label,
                    "title": day.get("title", ""),
                })

            else:
                # Normal stay day
                if stay_loc:
                    hotel_locations[stay_loc] = hotel_locations.get(stay_loc, 0) + 1

                if v_include:
                    vehicle_days += 1

        logger.info(f"🏨 Hotel locations: {hotel_locations}")
        logger.info(f"🚗 User vehicle days: {vehicle_days}")
        logger.info(f"🚌 Embedded vehicles: {[(e['day'], e['type']) for e in embedded_vehicles]}")

        # ─────────────────────────────────────────────────────────
        # STEP 2: Hotel cost per unique stay location
        # ─────────────────────────────────────────────────────────
        hotel_costs       = []
        total_hotel_price = 0
        total_map_price   = 0
        selected_hotels   = {}

        for location, loc_nights in hotel_locations.items():
            hotel_data = get_hotel_for_location(location, hotel_category, room_category, tools)
            if hotel_data:
                room       = hotel_data["room"]
                hotel_name = hotel_data["hotel_name"]
                meal_plan  = hotel_data["meal_plan"]
                min_cap    = int(room.get("minimum_capacity", 2))
                max_cap    = int(room.get("maximum_capacity", 3))

                price_per_room, extra_price, season_name = get_room_seasonal_price(
                    room, check_in_dt, check_out_dt
                )
                logger.info(
                    f"Location={location} Hotel={hotel_name} "
                    f"Season={season_name} Price={price_per_room} Extra={extra_price} "
                    f"Nights={loc_nights}"
                )

                map_per_person = float(meal_plan.get("map_price", 0))
                calc           = calculate_rooms_and_extra(guests, min_cap, max_cap)
                rooms_needed   = calc["rooms_needed"]
                extra_persons  = calc["extra_persons_total"]
                hotel_total    = ((price_per_room * rooms_needed) + (extra_persons * extra_price)) * loc_nights
                map_total      = map_per_person * guests * loc_nights

                hotel_costs.append({
                    "location":             location,
                    "hotel_name":           hotel_name,
                    "room_category":        room_category,
                    "price_per_room":       price_per_room,
                    "extra_person_price":   extra_price,
                    "rooms_needed":         rooms_needed,
                    "extra_persons_total":  extra_persons,
                    "min_capacity":         min_cap,
                    "max_capacity":         max_cap,
                    "hotel_total":          hotel_total,
                    "map_price_per_person": map_per_person,
                    "map_total":            map_total,
                    "season_name":          season_name,
                    "nights":               loc_nights,
                })
                selected_hotels[location] = hotel_name
                total_hotel_price += hotel_total
                total_map_price   += map_total
            else:
                logger.warning(f"⚠️ No hotel found for location={location}")
                hotel_costs.append({
                    "location":             location,
                    "hotel_name":           f"{hotel_category} Hotel",
                    "room_category":        room_category,
                    "price_per_room":       0,
                    "extra_person_price":   0,
                    "rooms_needed":         0,
                    "extra_persons_total":  0,
                    "min_capacity":         2,
                    "max_capacity":         3,
                    "hotel_total":          0,
                    "map_price_per_person": 0,
                    "map_total":            0,
                    "season_name":          "N/A",
                    "nights":               loc_nights,
                })
                selected_hotels[location] = f"{hotel_category} Hotel"

        context["selected_hotels"] = selected_hotels

        # ─────────────────────────────────────────────────────────
        # STEP 3: User-selected vehicle cost (only vehicle_include days)
        # ─────────────────────────────────────────────────────────
        vehicle_price         = 0
        vehicle_price_per_day = 0
        vehicle_name          = "None"
        vehicle_season_name   = "Regular Rate"

        if vehicle and vehicle_days > 0:
            vehicle_name          = vehicle.get("name", "Unknown")
            v_base, v_season      = get_vehicle_seasonal_price(vehicle, check_in_dt, check_out_dt)
            vehicle_price_per_day = v_base
            vehicle_price         = v_base * vehicle_days
            vehicle_season_name   = v_season
            logger.info(
                f"🚗 Vehicle={vehicle_name} Season={vehicle_season_name} "
                f"Price/day={v_base} Days={vehicle_days} Total={vehicle_price}"
            )

        # ─────────────────────────────────────────────────────────
        # STEP 4: Embedded vehicle costs (volvo / day-vehicle)
        # ─────────────────────────────────────────────────────────
        embedded_vehicle_costs = []
        total_embedded_price   = 0

        for ev in embedded_vehicles:
            ev_data  = ev["data"]
            ev_type  = ev["type"]

            # normalise field names (volvo uses volvo_price, vehicle uses vehicle_price)
            raw_price  = ev_data.get("volvo_price") or ev_data.get("vehicle_price", "0")
            ev_name    = ev_data.get("volvo_name")  or ev_data.get("vehicle_name",  "Vehicle")
            ev_seasons = ev_data.get("seasons", [])

            base_price = float(str(raw_price).replace(",", ""))

            # seasonal price
            matched = find_matching_season(ev_seasons, check_in_dt, check_out_dt)
            if matched:
                try:
                    ev_price       = float(str(matched.get("price", base_price)).replace(",", ""))
                    ev_season_name = matched.get("season_name", "Seasonal Rate")
                except (ValueError, TypeError):
                    ev_price       = base_price
                    ev_season_name = "Regular Rate"
            else:
                ev_price       = base_price
                ev_season_name = "Regular Rate"

            embedded_vehicle_costs.append({
                "day":          ev["day"],
                "title":        ev["title"],
                "type":         ev_type,
                "name":         ev_name,
                "price":        ev_price,
                "season_name":  ev_season_name,
            })
            total_embedded_price += ev_price
            logger.info(
                f"🚌 Embedded {ev_type}: {ev_name} Day={ev['day']} "
                f"Season={ev_season_name} Price={ev_price}"
            )

        # ─────────────────────────────────────────────────────────
        # STEP 5: Package margin + grand total
        # ─────────────────────────────────────────────────────────
        package_margin = 0
        try:
            margin_raw     = pkg.get("package_margin_price_manual", pkg.get("margin", "0"))
            package_margin = float(str(margin_raw).replace(",", "")) if margin_raw else 0
        except (ValueError, TypeError):
            package_margin = 0

        total_price = (
            total_hotel_price
            + total_map_price
            + vehicle_price
            + total_embedded_price
            + package_margin
        )

        context["pkg_price_details"] = {
            "hotel_costs":             hotel_costs,
            "total_hotel_price":       total_hotel_price,
            "total_map_price":         total_map_price,
            "vehicle_price":           vehicle_price,
            "vehicle_price_per_day":   vehicle_price_per_day,
            "vehicle_days":            vehicle_days,
            "vehicle_season_name":     vehicle_season_name,
            "vehicle_name":            vehicle_name,
            "embedded_vehicle_costs":  embedded_vehicle_costs,
            "total_embedded_price":    total_embedded_price,
            "package_margin":          package_margin,
            "total_price":             total_price,
            "nights":                  nights,
            "guests":                  guests,
            "selected_hotels":         selected_hotels,
            "check_in":                check_in_str,
            "check_out":               check_out_str,
            "tax":                     pkg.get("tax", "0"),
        }
        context["step"] = "pkg_show_itinerary"
        save_context(state, context)
        return card_pkg_summary(context)

    except Exception as e:
        logger.error(f"calculate_and_show_price error: {e}", exc_info=True)
        return {"type": "text", "content": f"Error calculating price: {str(e)}"}


# ─────────────────────────────────────────────────────────────
# CONFIRM PACKAGE BOOKING
# ─────────────────────────────────────────────────────────────

def confirm_package_booking(context: Dict, phone: str, business_phone: str, state, reset_fn) -> Dict:
    pd          = context.get("pkg_price_details", {})
    total_price = pd.get("total_price", 0)
    try:
        total_str = fp(total_price)
    except (ValueError, TypeError):
        total_str = f"Rs.{total_price}"

    pkg_name = context.get("selected_package", {}).get("package_name", "Package")
    ref      = f"PKG{datetime.now().strftime('%Y%m%d%H%M%S')}"
    logger.info(f"✅ PACKAGE BOOKING CONFIRMED: {ref}")
    reset_fn(phone, business_phone, state)
    return {
        "type": "text",
        "content": (
            f"✅ *BOOKING CONFIRMED!* 🎉\n\n"
            f"📦 *Package:* {pkg_name}\n"
            f"💵 *Total:* {total_str}\n"
            f"🔖 *Reference:* {ref}\n\n"
            f"Thank you for booking with us!\n"
            f"Have a wonderful trip. ✈️\n\n"
            f"Now to start a new booking!"
        ),
    }


# ─────────────────────────────────────────────────────────────
# GENERATE AND SEND PDF
# ─────────────────────────────────────────────────────────────

def generate_and_send_pdf(context: Dict, phone: str, business_phone: str, state) -> Dict:
    from datetime import datetime
    from services.pdf_generator import generate_package_pdf, send_pdf_via_whatsapp
    from database.database import get_whatsapp_config

    pkg = context.get("selected_package", {})
    if not pkg:
        return {"type": "text", "content": "No package selected. Please select a package first."}

    pkg_name = pkg.get("package_name") or pkg.get("title", "package")
    safe_name = "".join(c for c in pkg_name[:30] if c.isalnum() or c in (" ", "-", "_")).rstrip()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    os.makedirs("generated_pdfs", exist_ok=True)
    pdf_path = f"generated_pdfs/{safe_name}_{timestamp}.pdf"

    try:
        # Generate PDF
        generate_package_pdf(package_data=pkg, context=context, output_path=pdf_path)
        
        # Get sender config
        sender_config = get_whatsapp_config(business_phone)
        sender_phone_number_id = sender_config.get("phone_number_id") if sender_config else None
        
        # Send via WhatsApp
        caption = f"📄 *{pkg_name}* - Travel Package Details\n\n✅ *PDF Generated Successfully!*"
        result = send_pdf_via_whatsapp(
            to_phone=phone,
            pdf_path=pdf_path,
            caption=caption,
            sender_phone_number_id=sender_phone_number_id,
        )
        
        if result:
            return {"type": "buttons", "buttons": [{"text": "BOOK NOW", "value": "pkg_book_now"}]}
        return {"type": "text", "content": "⚠️ *PDF Generation Failed*\n\nPlease try again or click BOOK NOW."}
        
    except Exception as e:
        logger.error(f"generate_and_send_pdf error: {e}")
        return {"type": "text", "content": f"❌ *Error generating PDF:* {str(e)}"}