# services/pdf_generator.py
import os
import re
import logging
import base64
from datetime import datetime
from typing import Dict, Any, Optional
from pathlib import Path

from jinja2 import Template
import requests

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _fp(price) -> str:
    """Format price to ₹ X,XXX"""
    try:
        return f"₹ {float(str(price).replace(',', '')):,.0f}"
    except (ValueError, TypeError):
        return f"₹ {price}"


def _fetch_image_base64(url: str) -> Optional[str]:
    """
    Fetch an image from a URL and return it as a base64 data-URI.
    Handles hotlink protection by using multiple headers and fallbacks.
    """
    if not url:
        return None

    if not url.startswith(("http://", "https://")):
        logger.warning(f"Skipping non-absolute image URL: {url}")
        return None

    headers_list = [
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://google.com/",
        },
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0",
            "Accept": "image/webp,*/*",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://facebook.com/",
        },
        {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "image/jpeg,image/png,image/webp",
            "Referer": "https://bing.com/",
        },
        {
            "User-Agent": "Mozilla/5.0 (compatible; TravelBot/1.0)",
            "Accept": "image/*",
        }
    ]

    for headers in headers_list:
        try:
            resp = requests.get(url, timeout=15, headers=headers)
            if resp.status_code == 200:
                content_type = resp.headers.get("content-type", "")
                if "image" in content_type:
                    img_b64 = base64.b64encode(resp.content).decode("utf-8")
                    content_type_clean = content_type.split(";")[0].strip()
                    logger.info(f"✅ Image fetched: {url[:80]}...")
                    return f"data:{content_type_clean};base64,{img_b64}"
                else:
                    logger.debug(f"Response is {content_type}, not image: {url[:80]}...")
                    continue
        except Exception as e:
            logger.debug(f"Fetch failed ({headers.get('User-Agent','')[:30]}): {e}")
            continue

    logger.warning(f"❌ Failed to fetch image after {len(headers_list)} attempts: {url[:80]}...")
    return None


def _create_placeholder_base64(text: str = "Image Coming Soon") -> str:
    """Create a base64 encoded placeholder SVG image."""
    svg_template = f'''<svg xmlns="http://www.w3.org/2000/svg" width="800" height="400" viewBox="0 0 800 400">
        <defs>
            <linearGradient id="grad" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" style="stop-color:#1a3a5c;stop-opacity:1" />
                <stop offset="100%" style="stop-color:#2d6a9a;stop-opacity:1" />
            </linearGradient>
        </defs>
        <rect width="800" height="400" fill="url(#grad)"/>
        <text x="400" y="190" font-family="Arial, sans-serif" font-size="28" fill="#ffffff" text-anchor="middle" font-weight="bold">🏔️ {text}</text>
        <text x="400" y="230" font-family="Arial, sans-serif" font-size="14" fill="#c9a84c" text-anchor="middle">Image will be available soon</text>
    </svg>'''

    svg_bytes = svg_template.encode('utf-8')
    b64_str = base64.b64encode(svg_bytes).decode('utf-8')
    return f"data:image/svg+xml;base64,{b64_str}"   # ← BUG FIX: was b64_str not {b64_str}


# ══════════════════════════════════════════════════════════════════════════════
# MAIN PDF GENERATOR
# ══════════════════════════════════════════════════════════════════════════════

def generate_package_pdf(
    package_data: Dict,
    context: Dict,
    output_path: str,
) -> str:
    """
    Generate a travel package PDF from an HTML/Jinja2 template.
    """
    from weasyprint import HTML

    # ── Load template ────────────────────────────────────────────────────────
    template_path = Path(__file__).parent / "pdf_template.html"
    if not template_path.exists():
        raise FileNotFoundError(f"PDF template not found: {template_path}")

    with open(template_path, "r", encoding="utf-8") as f:
        html_template = f.read()

    # ── Extract package fields ───────────────────────────────────────────────
    pkg_name   = package_data.get("package_name") or package_data.get("title", "Travel Package")
    pkg_image  = package_data.get("package_image", "")
    itinerary  = package_data.get("itinerary", [])
    inclusions = package_data.get("inclusion", [])
    exclusions = package_data.get("exclusion", [])
    activities = package_data.get("activities", [])
    locations  = package_data.get("locations", [])

    # ── Extract pricing / booking context ────────────────────────────────────
    pd           = context.get("pkg_price_details", {})
    guests       = pd.get("guests",  context.get("guests", 1))
    nights       = pd.get("nights",  len(itinerary) if itinerary else 5)
    check_in     = context.get("check_in", "")
    check_out    = context.get("check_out", "")
    dest         = context.get("destination", ", ".join(locations[:2]) if locations else "Himalayan Escape")
    hotel_cat    = context.get("hotel_category", "Premium")
    room_cat     = context.get("room_category", "Double Sharing")
    vehicle_name = pd.get("vehicle_name", "Tempo Traveller")

    total_hotel   = pd.get("total_hotel_price", 0)
    total_map     = pd.get("total_map_price", 0)
    vehicle_price = pd.get("vehicle_price", 0)
    pkg_margin    = pd.get("package_margin", 0)
    total_price   = pd.get("total_price", 0)

    # ── Format prices ────────────────────────────────────────────────────────
    hotel_price_fmt    = _fp(total_hotel)
    map_price_fmt      = _fp(total_map)
    vehicle_price_fmt  = _fp(vehicle_price) if vehicle_price > 0 else ""
    service_charge_fmt = _fp(pkg_margin)    if pkg_margin   > 0 else ""
    total_price_fmt    = _fp(total_price)

    # ── Fetch cover image as base64 ──────────────────────────────────────────
    logger.info(f"Fetching cover image: {pkg_image}")
    cover_img_b64 = _fetch_image_base64(pkg_image) or _create_placeholder_base64(pkg_name[:30])

    # ── Process itinerary + fetch day images ─────────────────────────────────
    processed_itinerary = []
    for idx, day in enumerate(itinerary):
        day_image_url = (
            day.get("image") or
            day.get("image_url") or
            (day.get("gallery", [])[0] if day.get("gallery") else None) or
            (day.get("images", [])[0]  if day.get("images")  else None) or
            (day.get("photos", [])[0]  if day.get("photos")  else None) or
            pkg_image
        )

        logger.info(f"Day {idx+1} image URL: {day_image_url[:80] if day_image_url else 'None'}")
        day_img_b64 = (_fetch_image_base64(day_image_url) if day_image_url else None) \
                      or _create_placeholder_base64(f"Day {idx+1}")

        # Strip HTML tags from overview
        overview = day.get("overview", day.get("description", ""))
        if overview:
            overview = re.sub(r'<[^>]+>', ' ', overview)
            overview = re.sub(r'\s+', ' ', overview).strip()

        processed_itinerary.append({
            "title":    day.get("title", f"Day {idx + 1}"),
            "location": day.get("stay_location") or day.get("location", dest),
            "overview": overview[:600] if overview else "Experience the beauty of this destination.",
            "image":    day_img_b64,
        })

    # ── Build template context ───────────────────────────────────────────────
    template_data = {
        "package_name":   pkg_name.strip(),
        "destination":    dest,
        "nights":         nights,
        "guests":         guests,
        "check_in":       check_in,
        "check_out":      check_out,
        "hotel_category": hotel_cat,
        "room_category":  room_cat,
        "vehicle_name":   vehicle_name,
        "hotel_price":    hotel_price_fmt,
        "map_price":      map_price_fmt,
        "vehicle_price":  vehicle_price_fmt,
        "service_charge": service_charge_fmt,
        "total_price":    total_price_fmt,
        "cover_image":    cover_img_b64,
        "itinerary":      processed_itinerary,
        "locations":      locations or [dest],
        "inclusions": [inc.strip() for inc in inclusions if inc and inc.strip()] or [
            "Accommodation as per itinerary",
            "MAP Meals (Breakfast & Dinner)",
            "All transfers & sightseeing",
            "Driver allowances, toll, parking",
        ],
        "exclusions": [exc.strip() for exc in exclusions if exc and exc.strip()] or [
            "5% GST applicable extra",
            "Personal expenses",
            "Entry fees & monument tickets",
            "Travel insurance",
        ],
        "activities": [act.strip() for act in activities if act and act.strip()] or [
            "River Rafting",
            "Paragliding",
            "Mountain Trekking",
            "Local Sightseeing",
        ],
    }

    # ── Render HTML ──────────────────────────────────────────────────────────
    template = Template(html_template)
    html_content = template.render(**template_data)

    # Save HTML preview for debugging
    html_debug_path = output_path.replace(".pdf", "_preview.html")
    with open(html_debug_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    logger.info(f"📄 HTML preview saved: {html_debug_path}")

    # ── Generate PDF with WeasyPrint ─────────────────────────────────────────
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    HTML(
        string=html_content,
        base_url=str(template_path.parent),
    ).write_pdf(output_path)

    logger.info(f"✅ PDF generated: {output_path}")
    return output_path


# ══════════════════════════════════════════════════════════════════════════════
# WHATSAPP HELPERS  (unchanged from original)
# ══════════════════════════════════════════════════════════════════════════════

def download_pdf_from_url(pdf_url: str, package_name: str) -> Optional[str]:
    try:
        os.makedirs("generated_pdfs", exist_ok=True)
        pkg_clean = "".join(
            c for c in package_name[:30] if c.isalnum() or c in (" ", "-", "_")
        ).rstrip()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"generated_pdfs/{pkg_clean}_{ts}.pdf"
        resp = requests.get(pdf_url, timeout=30)
        if resp.status_code == 200:
            with open(filename, "wb") as f:
                f.write(resp.content)
            return filename
        logger.error(f"PDF download failed: {resp.status_code}")
        return None
    except Exception as e:
        logger.error(f"PDF download error: {e}")
        return None


def upload_pdf_to_whatsapp(
    pdf_path: str,
    sender_phone_number_id: str,
    access_token: str,
) -> Optional[str]:
    try:
        url = f"https://graph.facebook.com/v18.0/{sender_phone_number_id}/media"
        with open(pdf_path, "rb") as f:
            files = {
                "file": (os.path.basename(pdf_path), f, "application/pdf"),
                "messaging_product": (None, "whatsapp"),
                "type": (None, "application/pdf"),
            }
            headers = {"Authorization": f"Bearer {access_token}"}
            resp = requests.post(url, headers=headers, files=files)
        if resp.status_code == 200:
            media_id = resp.json().get("id")
            logger.info(f"✅ PDF uploaded to WhatsApp, media_id: {media_id}")
            return media_id
        logger.error(f"WhatsApp upload failed: {resp.status_code} {resp.text}")
        return None
    except Exception as e:
        logger.error(f"WhatsApp upload error: {e}")
        return None


def send_pdf_via_whatsapp(
    to_phone: str,
    pdf_path: str,
    caption: str = "",
    sender_phone_number_id: str = None,
) -> Optional[dict]:
    ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
    if not ACCESS_TOKEN:
        logger.error("ACCESS_TOKEN environment variable not set")
        return None

    try:
        if not sender_phone_number_id:
            try:
                from database.database import get_all_active_whatsapp_numbers
                active = get_all_active_whatsapp_numbers()
                if active:
                    sender_phone_number_id = active[0]["phone_number_id"]
                else:
                    logger.error("No active WhatsApp number found")
                    return None
            except ImportError:
                logger.error("Database module not available")
                return None

        media_id = upload_pdf_to_whatsapp(pdf_path, sender_phone_number_id, ACCESS_TOKEN)
        if not media_id:
            logger.error("PDF upload failed")
            return None

        url = f"https://graph.facebook.com/v18.0/{sender_phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": to_phone,
            "type": "document",
            "document": {
                "id": media_id,
                "caption": caption or "📄 Your travel package details",
                "filename": os.path.basename(pdf_path),
            },
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        if resp.status_code == 200:
            logger.info(f"✅ PDF sent to {to_phone}")
            return resp.json()
        logger.error(f"WhatsApp send failed: {resp.status_code}")
        return None
    except Exception as e:
        logger.error(f"send_pdf_via_whatsapp error: {e}")
        return None


def generate_and_send_pdf_v2(
    context: Dict,
    phone: str,
    business_phone: str,
    state,
) -> Dict:
    try:
        from database.database import get_whatsapp_config

        pkg = context.get("selected_package", {})
        if not pkg:
            return {"type": "text", "content": "No package selected. Please select a package first."}

        pkg_name = pkg.get("package_name") or pkg.get("title", "package")
        safe_name = "".join(
            c for c in pkg_name[:30] if c.isalnum() or c in (" ", "-", "_")
        ).rstrip()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        os.makedirs("generated_pdfs", exist_ok=True)
        pdf_path = f"generated_pdfs/{safe_name}_{timestamp}.pdf"

        generate_package_pdf(package_data=pkg, context=context, output_path=pdf_path)

        sender_config = get_whatsapp_config(business_phone)
        sender_phone_number_id = sender_config.get("phone_number_id") if sender_config else None

        caption = f"📄 *{pkg_name}* - Travel Package Details\n\n✅ *PDF Generated Successfully!*"
        result = send_pdf_via_whatsapp(
            to_phone=phone,
            pdf_path=pdf_path,
            caption=caption,
            sender_phone_number_id=sender_phone_number_id,
        )

        if result:
            return {
                "type": "buttons",
                "buttons": [
                    {"text": "📥 VIEW PDF", "value": "view_pdf"},
                    {"text": "BOOK NOW",   "value": "pkg_book_now"},
                ],
            }
        return {
            "type": "text",
            "content": "⚠️ *PDF Generation Failed*\n\nPlease try again or click BOOK NOW.",
        }

    except Exception as e:
        logger.error(f"generate_and_send_pdf_v2 error: {e}", exc_info=True)
        return {"type": "text", "content": f"❌ *Error generating PDF:* {str(e)}"}
        