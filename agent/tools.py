from typing import Dict, Any, List, Optional
import requests
import logging
from datetime import datetime
import math
from dotenv import load_dotenv
import os
load_dotenv('.env')
BASE = os.getenv('WP_API_BASE')
logger = logging.getLogger(__name__)

CATEGORIES_API          = f"{BASE}/hotel-categories"
HOTELS_BY_CATEGORY_API  = f"{BASE}/hotel-categories"
ALL_HOTELS_API          = f"{BASE}/hotels"
PACKAGES_API            = f"{BASE}/packages"
ROOM_CATEGORIES_API     = f"{BASE}/room-categories"
VEHICLE_CATEGORIES_API  = f"{BASE}/vehicle"
VEHICLE_BY_TYPE_API     = f"{BASE}/vehicle"
ROOM_PRICES_API         = f"{BASE}/room-prices"
VEHICLE_PRICES_API      = f"{BASE}/vehicle-prices"
ACTIVITIES_PRICES_API   = f"{BASE}/activities-prices"

 
def _get_display_phone(sender_phone_number_id: str) -> str:
    try:
        from database.database import get_whatsapp_config
        config = get_whatsapp_config(sender_phone_number_id)
        if config:
            phone = (
                config.get("display_phone_number_raw")
                or config.get("display_number")
                or config.get("phone_number")
                or ""
            )
            phone = "".join(filter(str.isdigit, str(phone)))
            logger.info(f"Resolved display phone: {phone} for sender: {sender_phone_number_id}")
            return phone
        logger.warning(f"No config found for sender: {sender_phone_number_id}")
        return ""
    except Exception as e:
        logger.error(f"_get_display_phone error: {e}")
        return ""


class TravelTools:

    def __init__(self, sender_phone_number_id: str = None, display_phone: str = None):
        if display_phone:
            self.phone = "".join(filter(str.isdigit, str(display_phone)))
        elif sender_phone_number_id:
            self.phone = _get_display_phone(sender_phone_number_id)
        else:
            self.phone = ""
            logger.warning("TravelTools created without phone")

        # Fix for Hostinger WAF blocking Python requests
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        logger.info(f"TravelTools initialized with phone={self.phone}")

    def _phone_params(self) -> Dict:
        if self.phone:
            return {"phone": self.phone}
        return {}

    # ── CATEGORIES ────────────────────────────────────────────────────────────

    def get_categories(self) -> Dict[str, Any]:
        try:
            response = self.session.get(CATEGORIES_API, timeout=30)
            response.raise_for_status()
            data = response.json()
            if data and data.get("status") and data.get("data"):
                categories = [{"name": cat.get("category_name")} for cat in data["data"]]
                return {"success": True, "categories": categories}
            return {"success": False, "error": "No categories found", "categories": []}
        except Exception as e:
            logger.error(f"Categories error: {e}")
            return {"success": False, "error": str(e), "categories": []}

    # ── HOTELS BY CATEGORY ────────────────────────────────────────────────────

    def search_hotels_by_category(self, category: str, location: str = None) -> Dict[str, Any]:
        try:
            params = self._phone_params()
            response = self.session.get(HOTELS_BY_CATEGORY_API, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if not data.get("status"):
                return {"success": False, "error": "API error", "hotels": []}

            selected = None
            for cat_data in data.get("data", []):
                if cat_data.get("category_name", "").lower() == category.lower():
                    selected = cat_data
                    break

            if not selected:
                return {"success": False, "message": f"No category '{category}'", "hotels": []}

            hotels = selected.get("hotels", [])
            filtered = []
            
            # Log for debugging
            logger.info(f"🔍 Searching for {category} hotels in: {location}")
            
            for hotel in hotels:
                hotel_location = hotel.get("location", "").strip()
                hotel_name = hotel.get("name", "Unknown")
                
                logger.info(f"   Checking: {hotel_name} | Location: '{hotel_location}'")
                
                # EXACT location matching (case-insensitive)
                if location:
                    # Only include if hotel location EXACTLY matches user's location
                    if hotel_location.lower() == location.lower():
                        logger.info(f"   ✅ MATCH: {hotel_name} is in {location}")
                        filtered.append({
                            "name": hotel.get("name", "").split(",")[0],
                            "full_name": hotel.get("name"),
                            "location": hotel_location,
                            "image": hotel.get("image"),
                            "description": hotel.get("description", "")[:300],
                            "category": category,
                            "original_data": hotel
                        })
                    else:
                        logger.info(f"   ❌ SKIP: {hotel_name} is in {hotel_location}, not {location}")
                else:
                    # No location filter - return all hotels
                    filtered.append({
                        "name": hotel.get("name", "").split(",")[0],
                        "full_name": hotel.get("name"),
                        "location": hotel_location,
                        "image": hotel.get("image"),
                        "description": hotel.get("description", "")[:300],
                        "category": category,
                        "original_data": hotel
                    })

            logger.info(f"📊 Returning {len(filtered)} hotels for {category} in {location}")
            
            return {
                "success": True,
                "category": category,
                "location": location,
                "hotels": filtered,
                "count": len(filtered)
            }
        except Exception as e:
            logger.error(f"Search hotels error: {e}")
            return {"success": False, "error": str(e), "hotels": []}

    # ── HOTEL ROOMS ───────────────────────────────────────────────────────────

    def get_hotel_rooms(self, hotel_name: str) -> Dict[str, Any]:
        try:
            params = self._phone_params()
            response = self.session.get(ALL_HOTELS_API, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            all_hotels = data.get("hotels", [])

            search_name = hotel_name.replace("Hotel", "").strip().lower()
            selected = None

            for hotel in all_hotels:
                hotel_api_name = hotel.get("hotel_name", "").lower()
                if (search_name == hotel_api_name or
                        search_name in hotel_api_name or
                        hotel_api_name in search_name):
                    selected = hotel
                    break

            if not selected:
                for hotel in all_hotels:
                    if hotel_name.lower() in hotel.get("hotel_name", "").lower():
                        selected = hotel
                        break

            if not selected:
                return {"success": False, "error": f"Hotel '{hotel_name}' not found"}

            rooms = selected.get("rooms", [])
            if not rooms:
                return {"success": False, "error": "No rooms available"}

            formatted_rooms = []
            for room in rooms:
                formatted_rooms.append({
                    "category": room.get("room_category", "Standard"),
                    "type": room.get("room_type", "Regular"),
                    "minimum_capacity": int(room.get("minimum_capacity", 1)),
                    "maximum_capacity": int(room.get("maximum_capacity", 2)),
                    "extra_person_capacity": int(room.get("extra_person_capacity", 1)),
                    "base_price": int(room.get("base_price", 0)),
                    "extra_person_price": int(room.get("extra_person_price", 0)),
                    "images": room.get("room_images", []),
                    "facilities": room.get("facilities", []),
                    "seasons": room.get("seasons", [])
                })

            full_hotel_details = {
                "hotel_name": selected.get("hotel_name"),
                "category": selected.get("category", ""),
                "location": selected.get("location", ""),
                "description": selected.get("description", ""),
                "phones": selected.get("phones", []),
                "emails": selected.get("emails", []),
                "extra_services": selected.get("extra_services", []),
                "gallery": selected.get("gallery", []),
            }

            return {
                "success": True,
                "hotel_name": selected.get("hotel_name"),
                "hotel_location": selected.get("location"),
                "meal_plan": {
                    "map_price": int(selected.get("meal_plan", {}).get("map_price", 0)),
                    "cp_price": int(selected.get("meal_plan", {}).get("cp_price", 0)),
                    "ep_price": 0
                },
                "tax": selected.get("tax", "0"),
                "rooms": formatted_rooms,
                "total_rooms": len(formatted_rooms),
                "hotel_gallery": selected.get("gallery", []),
                "full_hotel_details": full_hotel_details,
            }

        except requests.exceptions.Timeout:
            logger.error(f"Timeout fetching rooms for {hotel_name}")
            return {"success": False, "error": "Server timeout. Please try again."}
        except Exception as e:
            logger.error(f"Get rooms error: {e}")
            return {"success": False, "error": str(e)}

    # ── ALL HOTELS IN LOCATION ────────────────────────────────────────────────

    def get_all_hotels_in_location(self, location: str) -> Dict[str, Any]:
        try:
            params = self._phone_params()
            response = self.session.get(HOTELS_BY_CATEGORY_API, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            all_hotels = []
            for cat_data in data.get("data", []):
                for hotel in cat_data.get("hotels", []):
                    if location.lower() in hotel.get("location", "").lower():
                        all_hotels.append({
                            "name": hotel.get("name", "").split(",")[0],
                            "category": cat_data.get("category_name"),
                            "location": hotel.get("location"),
                            "image": hotel.get("image"),
                            "description": hotel.get("description", "")[:200]
                        })
            return {"success": True, "hotels": all_hotels, "count": len(all_hotels)}
        except Exception as e:
            return {"success": False, "error": str(e), "hotels": []}

    # ── PACKAGES ──────────────────────────────────────────────────────────────

    def get_packages(self, destination: str = None, cities: list = None) -> Dict[str, Any]:
        try:
            params = self._phone_params()
            response = self.session.get(PACKAGES_API, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            all_packages = data if isinstance(data, list) else data.get("packages", data.get("data", []))

            
            search_terms = []
            if cities:
                search_terms = [c.lower() for c in cities if c]
            elif destination:
                search_terms = [destination.lower()]

            if search_terms:
                def package_matches(p):
                    pkg_text = (
                        str(p.get("locations", [])).lower()
                        + p.get("title", "").lower()
                        + p.get("package_name", "").lower()
                    )
                  
                    return any(term in pkg_text for term in search_terms)

                matched = [p for p in all_packages if package_matches(p)]
                return {"success": True, "packages": matched, "count": len(matched)}

            return {"success": True, "packages": all_packages, "count": len(all_packages)}
        except Exception as e:
            logger.error(f"Packages error: {e}")
            return {"success": False, "error": str(e), "packages": []}

   

    def get_hotels_in_location_for_package(self, location: str, hotel_category: str = None) -> Dict[str, Any]:
        try:
            params = self._phone_params()
            response = self.session.get(HOTELS_BY_CATEGORY_API, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            matched = []
            for cat_data in data.get("data", []):
                cat_name = cat_data.get("category_name", "")
                if hotel_category and cat_name.lower() != hotel_category.lower():
                    continue
                for hotel in cat_data.get("hotels", []):
                    hotel_loc = hotel.get("location", "")
                    if location.lower() in hotel_loc.lower():
                        matched.append({
                            "name": hotel.get("name", "").split(",")[0],
                            "location": hotel_loc,
                            "category": cat_name,
                            "image": hotel.get("image", ""),
                            "description": hotel.get("description", "")[:200],
                        })
            return {"success": True, "hotels": matched, "count": len(matched)}
        except Exception as e:
            logger.error(f"Hotels for package error: {e}")
            return {"success": False, "error": str(e), "hotels": []}

    # ── VEHICLES ──────────────────────────────────────────────────────────────

    def get_vehicle_categories(self) -> Dict[str, Any]:
        try:
            response = self.session.get(VEHICLE_CATEGORIES_API, timeout=30)
            response.raise_for_status()
            data = response.json()
            if data.get("status") and data.get("categories"):
                return {"success": True, "vehicle_categories": data.get("categories", [])}
            return {"success": False, "error": "No vehicle categories found", "vehicle_categories": []}
        except Exception as e:
            logger.error(f"Vehicle categories error: {e}")
            return {"success": False, "error": str(e), "vehicle_categories": []}

    def get_vehicles_by_type(self, vehicle_type: str) -> Dict[str, Any]:
        try:
            params = {**self._phone_params(), "include": vehicle_type.lower()}
            response = self.session.get(VEHICLE_BY_TYPE_API, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            vehicles = []
            raw = data if isinstance(data, list) else data.get("vehicles", data.get("data", []))
            for v in raw:
                vehicles.append({
                    "id": v.get("id"),
                    "name": v.get("name") or v.get("vehicle_name", ""),
                    "type": v.get("type") or vehicle_type,
                    "capacity": v.get("capacity") or v.get("seating_capacity", ""),
                    "price": v.get("price") or v.get("price_per_day") or v.get("flat_price", 0),
                    "image": v.get("image") or v.get("vehicle_image", ""),
                    "description": v.get("description", ""),
                })
            return {"success": True, "vehicles": vehicles, "vehicle_type": vehicle_type}
        except Exception as e:
            logger.error(f"Vehicle by type error: {e}")
            return {"success": False, "error": str(e), "vehicles": []}

    # ── ROOM CATEGORIES ───────────────────────────────────────────────────────

    def get_room_categories(self) -> Dict[str, Any]:
        try:
            response = self.session.get(ROOM_CATEGORIES_API, timeout=30)
            response.raise_for_status()
            data = response.json()
            if data.get("status") and data.get("room_categories"):
                return {"success": True, "room_categories": data.get("room_categories", [])}
            return {"success": False, "error": "No room categories found", "room_categories": []}
        except Exception as e:
            logger.error(f"Room categories error: {e}")
            return {"success": False, "error": str(e), "room_categories": []}

    # ── PRICE HELPERS ─────────────────────────────────────────────────────────

    @staticmethod
    def get_room_prices() -> Dict[str, Any]:
        try:
            session = requests.Session()
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json",
            })
            response = session.get(ROOM_PRICES_API, timeout=30)
            response.raise_for_status()
            data = response.json()
            if data.get("status") and data.get("prices"):
                return {"success": True, "prices": data.get("prices", {})}
            return {"success": False, "error": "No room prices found", "prices": {}}
        except Exception as e:
            logger.error(f"Room prices error: {e}")
            return {"success": False, "error": str(e), "prices": {}}

    @staticmethod
    def get_vehicle_prices() -> Dict[str, Any]:
        try:
            session = requests.Session()
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json",
            })
            response = session.get(VEHICLE_PRICES_API, timeout=30)
            response.raise_for_status()
            data = response.json()
            if data.get("status") and data.get("prices"):
                return {"success": True, "prices": data.get("prices", {})}
            return {"success": False, "error": "No vehicle prices found", "prices": {}}
        except Exception as e:
            logger.error(f"Vehicle prices error: {e}")
            return {"success": False, "error": str(e), "prices": {}}

    # ── DATE VALIDATION ───────────────────────────────────────────────────────

    @staticmethod
    def validate_dates(check_in: str, check_out: str) -> Dict[str, Any]:
        try:
            today = datetime.now().date()
            check_in_date = datetime.strptime(check_in, "%Y-%m-%d").date()
            check_out_date = datetime.strptime(check_out, "%Y-%m-%d").date()

            if check_in_date < today:
                return {
                    "valid": False,
                    "error": f"Check-in date {check_in} is in the past. Please provide a future date."
                }
            if check_out_date <= check_in_date:
                return {
                    "valid": False,
                    "error": "Check-out date must be after check-in date. Please provide valid dates."
                }
            nights = (check_out_date - check_in_date).days
            return {"valid": True, "nights": nights, "check_in": str(check_in_date), "check_out": str(check_out_date)}
        except ValueError:
            return {"valid": False, "error": "Invalid date format. Please use YYYY-MM-DD format."}

    # ── SEASON MATCHING ───────────────────────────────────────────────────────

    @staticmethod
    def find_matching_season(seasons: List[Dict], check_in_date: datetime, check_out_date: datetime) -> Optional[Dict]:
        try:
            for season in seasons:
                starting_date_str = season.get("starting_date", "")
                end_date_str = season.get("end_date", "")
                if not starting_date_str or not end_date_str:
                    continue
                try:
                    if "-" in starting_date_str:
                        parts = starting_date_str.split("-")
                        if len(parts[0]) == 4:
                            season_start = datetime.strptime(starting_date_str, "%Y-%m-%d")
                            season_end = datetime.strptime(end_date_str, "%Y-%m-%d")
                        else:
                            season_start = datetime.strptime(starting_date_str, "%d-%m-%Y")
                            season_end = datetime.strptime(end_date_str, "%d-%m-%Y")
                    else:
                        continue
                except ValueError:
                    continue

                # ── FIX: compare month/day only — ignore the year on season dates ──
                s_md  = (season_start.month, season_start.day)
                e_md  = (season_end.month,   season_end.day)
                ci_md = (check_in_date.month, check_in_date.day)
                co_md = (check_out_date.month, check_out_date.day)

                if s_md > e_md:           # season wraps year-end (e.g. Dec–Mar)
                    if ci_md >= s_md or ci_md <= e_md:
                        return season
                    if co_md >= s_md or co_md <= e_md:
                        return season
                else:                     # normal season within one calendar year
                    if s_md <= ci_md <= e_md:
                        return season
                    if s_md <= co_md <= e_md:
                        return season

            return None
        except Exception as e:
            logger.error(f"Season matching error: {e}")
            return None

    # ── ROOM PRICE ────────────────────────────────────────────────────────────

    @staticmethod
    def calculate_room_price(room: Dict, check_in: str, check_out: str, guests: int) -> Dict[str, Any]:
        try:
            check_in_date = datetime.strptime(check_in, "%Y-%m-%d")
            check_out_date = datetime.strptime(check_out, "%Y-%m-%d")
            nights = (check_out_date - check_in_date).days

            if nights <= 0:
                return {"success": False, "error": "Check-out date must be after check-in date"}

            min_capacity = int(room.get("minimum_capacity", room.get("min_capacity", 1)))
            max_capacity = int(room.get("maximum_capacity", room.get("max_capacity", 2)))

            seasons = room.get("seasons", [])
            matching_season = TravelTools.find_matching_season(seasons, check_in_date, check_out_date)

            if matching_season:
                price_per_night = int(matching_season.get("price", 0))
                extra_price = int(matching_season.get("extra_price", 0))
                season_name = matching_season.get("season_name", "Unknown")
            else:
                price_per_night = int(room.get("base_price", 0))
                extra_price = int(room.get("extra_person_price", 0))
                season_name = "Regular Rate"

            rooms_needed = math.ceil(guests / max_capacity)
            extra_people = max(0, guests - (rooms_needed * min_capacity))
            room_total = rooms_needed * price_per_night * nights
            extra_total = extra_people * extra_price * nights
            grand_total = room_total + extra_total

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
                "seasonal_base_price": price_per_night,
                "seasonal_extra_price": extra_price,
            }
        except Exception as e:
            logger.error(f"Price calculation error: {e}")
            return {"success": False, "error": str(e)}

    # ── MEAL PRICE ────────────────────────────────────────────────────────────

    @staticmethod
    def calculate_meal_price(meal_type: str, meal_plan_data: Dict, guests: int, nights: int) -> Dict[str, Any]:
        try:
            meal_type_lower = meal_type.lower()
            if meal_type_lower == "ep":
                price_per_person = 0
            else:
                prices = {
                    "map": int(meal_plan_data.get("map_price", 0)),
                    "cp": int(meal_plan_data.get("cp_price", 0)),
                }
                price_per_person = prices.get(meal_type_lower, 0)

            total = price_per_person * guests * nights
            names = {
                "map": "MAP (Breakfast + Dinner)",
                "cp": "CP (Breakfast only)",
                "ep": "EP (No meals)"
            }
            return {
                "success": True,
                "meal_type": meal_type,
                "meal_name": names.get(meal_type_lower, meal_type),
                "price_per_person": price_per_person,
                "total_meal_price": total
            }
        except Exception as e:
            logger.error(f"Meal price error: {e}")
            return {"success": False, "error": str(e)}

    # ── PACKAGE PRICE ─────────────────────────────────────────────────────────

    @staticmethod
    def calculate_package_price(
        room_category: Dict, vehicle_category: Dict,
        check_in: str, check_out: str, guests: int,
        want_activities: bool = False
    ) -> Dict[str, Any]:
        try:
            check_in_date = datetime.strptime(check_in, "%Y-%m-%d")
            check_out_date = datetime.strptime(check_out, "%Y-%m-%d")
            nights = (check_out_date - check_in_date).days

            room_prices_result = TravelTools.get_room_prices()
            vehicle_prices_result = TravelTools.get_vehicle_prices()

            room_name = room_category.get("name", "")
            vehicle_name = vehicle_category.get("name", "")

            room_price_per_night = 0
            if room_prices_result.get("success"):
                room_price_per_night = room_prices_result.get("prices", {}).get(room_name, 0)

            vehicle_price_per_night = 0
            if vehicle_prices_result.get("success"):
                vehicle_price_per_night = vehicle_prices_result.get("prices", {}).get(vehicle_name, 0)

            room_total = room_price_per_night * nights * guests
            vehicle_total = vehicle_price_per_night * nights

            activities_price_per_night = 0
            try:
                act_session = requests.Session()
                act_session.headers.update({
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "application/json",
                })
                act_response = act_session.get(ACTIVITIES_PRICES_API, timeout=30)
                if act_response.status_code == 200:
                    act_data = act_response.json()
                    if act_data.get("status"):
                        activities_price_per_night = int(act_data.get("price_per_person_per_night", 0))
            except Exception:
                activities_price_per_night = 0

            activities_total = activities_price_per_night * nights * guests if want_activities else 0
            grand_total = room_total + vehicle_total + activities_total

            return {
                "success": True,
                "nights": nights,
                "guests": guests,
                "room_category": room_name,
                "vehicle_category": vehicle_name,
                "room_price_per_night": room_price_per_night,
                "vehicle_price_per_night": vehicle_price_per_night,
                "activities_price_per_night": activities_price_per_night,
                "room_total": room_total,
                "vehicle_total": vehicle_total,
                "activities_total": activities_total,
                "want_activities": want_activities,
                "grand_total": grand_total
            }
        except Exception as e:
            logger.error(f"Package price calculation error: {e}")
            return {"success": False, "error": str(e)}


# ── TOOL DEFINITIONS ──────────────────────────────────────────────
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_categories",
            "description": "Get all hotel categories",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_hotels_by_category",
            "description": "Search hotels by category and optional location",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "location": {"type": "string"}
                },
                "required": ["category"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_all_hotels_in_location",
            "description": "Get all hotels in a specific location",
            "parameters": {
                "type": "object",
                "properties": {"location": {"type": "string"}},
                "required": ["location"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_hotel_rooms",
            "description": "Get all rooms for a specific hotel",
            "parameters": {
                "type": "object",
                "properties": {"hotel_name": {"type": "string"}},
                "required": ["hotel_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_packages",
            "description": "Fetch travel packages, optionally filtered by destination",
            "parameters": {
                "type": "object",
                "properties": {"destination": {"type": "string"}},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "validate_dates",
            "description": "Validate check-in and check-out dates",
            "parameters": {
                "type": "object",
                "properties": {
                    "check_in": {"type": "string"},
                    "check_out": {"type": "string"}
                },
                "required": ["check_in", "check_out"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_room_price",
            "description": "Calculate price for selected room",
            "parameters": {
                "type": "object",
                "properties": {
                    "room": {"type": "object"},
                    "check_in": {"type": "string"},
                    "check_out": {"type": "string"},
                    "guests": {"type": "integer"}
                },
                "required": ["room", "check_in", "check_out", "guests"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_meal_price",
            "description": "Calculate meal plan price",
            "parameters": {
                "type": "object",
                "properties": {
                    "meal_type": {"type": "string"},
                    "meal_plan_data": {"type": "object"},
                    "guests": {"type": "integer"},
                    "nights": {"type": "integer"}
                },
                "required": ["meal_type", "meal_plan_data", "guests", "nights"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_room_categories",
            "description": "Get all room categories",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_vehicle_categories",
            "description": "Get all vehicle category names",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_vehicles_by_type",
            "description": "Fetch vehicles filtered by type",
            "parameters": {
                "type": "object",
                "properties": {"vehicle_type": {"type": "string"}},
                "required": ["vehicle_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_hotels_in_location_for_package",
            "description": "Get hotels in a location for package itinerary",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string"},
                    "hotel_category": {"type": "string"}
                },
                "required": ["location"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_package_price",
            "description": "Calculate total price for travel package",
            "parameters": {
                "type": "object",
                "properties": {
                    "room_category": {"type": "object"},
                    "vehicle_category": {"type": "object"},
                    "check_in": {"type": "string"},
                    "check_out": {"type": "string"},
                    "guests": {"type": "integer"},
                    "want_activities": {"type": "boolean"}
                },
                "required": ["room_category", "vehicle_category", "check_in", "check_out", "guests"]
            }
        }
    },
]