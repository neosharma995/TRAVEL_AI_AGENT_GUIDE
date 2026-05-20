# chats/whatsapp_sender.py — with dynamic phone number from database

import requests
import re
import os
import time
import logging
from dotenv import load_dotenv
from chats.queue_manager import rate_limiter
from database.database import get_whatsapp_config

load_dotenv('.env')
logger = logging.getLogger(__name__)

ACCESS_TOKEN = os.getenv('ACCESS_TOKEN')


def safe_post(url: str, headers: dict, data: dict, retries: int = 3):
    """POST with exponential backoff retry."""
    for attempt in range(1, retries + 1):
        try:
            rate_limiter.acquire()
            res = requests.post(url, headers=headers, json=data, timeout=15)

            if res.status_code == 200:
                logger.info(f"✅ POST successful (attempt {attempt})")
                return res

            if res.status_code == 429:
                wait = 2 ** attempt
                logger.warning(f"⚠️ Meta 429 rate limit — waiting {wait}s (attempt {attempt})")
                time.sleep(wait)
                continue

            logger.warning(f"⚠️ HTTP {res.status_code} on attempt {attempt}: {res.text[:200]}")

        except requests.exceptions.Timeout:
            logger.warning(f"⏰ Timeout on attempt {attempt}")
        except requests.exceptions.ConnectionError:
            logger.warning(f"🔌 Connection error on attempt {attempt}")
        except Exception as e:
            logger.warning(f"❓ Unexpected error on attempt {attempt}: {e}")

        if attempt < retries:
            time.sleep(attempt)

    logger.error(f"❌ All {retries} attempts failed")
    return None


def send_whatsapp_message(to_phone: str, response: dict, sender_phone_number_id: str):
    """Main entry point - requires sender_phone_number_id"""
    sender_config = get_whatsapp_config(sender_phone_number_id)

    if not sender_config:
        logger.error(f"❌ No active config found for sender: {sender_phone_number_id}")
        return None

    url = f"https://graph.facebook.com/v18.0/{sender_config['phone_number_id']}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    try:
        if response.get("type") == "multi":
            responses = response.get("responses", [])
            logger.info(f"📤 Sending {len(responses)} messages to {to_phone}")

            for i, single_response in enumerate(responses):
                send_single_message(to_phone, single_response, url, headers)
                if i < len(responses) - 1:
                    time.sleep(0.5)
            return True

        return send_single_message(to_phone, response, url, headers)

    except Exception as e:
        logger.exception(f"❌ send_whatsapp_message error: {e}")
        return None


def send_single_message(to_phone: str, response: dict, url: str, headers: dict):
    """Send a single message — handles text, buttons, buttons_grid, image, image with buttons."""
    try:
        msg_type = response.get("type", "text")
        logger.info(f"📨 Sending {msg_type} message to {to_phone}")

        # ── IMAGE with buttons (interactive image message) ──────────────────────
        if msg_type == "image":
            image_url = response.get("content", "")
            caption = response.get("caption", "")
            buttons = response.get("buttons", [])
            
            if buttons and len(buttons) > 0:
                # Send as interactive image with buttons (WhatsApp supports this)
                return _send_image_with_buttons(to_phone, image_url, caption, buttons, url, headers)
            else:
                # Plain image without buttons
                data = {
                    "messaging_product": "whatsapp",
                    "to": to_phone,
                    "type": "image",
                    "image": {
                        "link": image_url,
                        "caption": caption
                    }
                }
                res = safe_post(url, headers, data)
                return res.json() if res and res.status_code == 200 else None

        # ── BUTTONS (plain, max 3 per batch) ──────────────────────────────────
        elif msg_type == "buttons":
            content = response.get("content", "")
            buttons = response.get("buttons", [])

            if not buttons:
                return send_single_message(to_phone, {"type": "text", "content": content}, url, headers)

            return _send_buttons_in_batches(to_phone, content, buttons, url, headers)

        # ── BUTTONS_GRID (many buttons → WhatsApp list message) ───────────────
        elif msg_type == "buttons_grid":
            content  = response.get("content", "")
            buttons  = response.get("buttons", [])

            if not buttons:
                return send_single_message(to_phone, {"type": "text", "content": content}, url, headers)

            return _send_list_message(to_phone, content, buttons, url, headers)

        # ── TEXT (default) ────────────────────────────────────────────────────
        else:
            text_content = response.get("content", "")
            if not text_content:
                return None
            data = _text_message(to_phone, text_content)
            res = safe_post(url, headers, data)
            return res.json() if res and res.status_code == 200 else None

    except Exception as e:
        logger.exception(f"❌ send_single_message error: {e}")
        return None



def _send_image_with_buttons(to_phone: str, image_url: str, caption: str, buttons: list, url: str, headers: dict):
    """
    Send an image with interactive buttons (WhatsApp supports this).
    Note: WhatsApp only allows up to 3 buttons on an interactive message.
    """
    wb = []
    for btn in buttons[:3]:
        title = _clean_button_text(btn["text"], 20)
        value = str(btn["value"])[:256]
        wb.append({
            "type": "reply",
            "reply": {"id": value, "title": title}
        })
    
    data = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "header": {
                "type": "image",
                "image": {"link": image_url}
            },
            "body": {"text": caption[:1024] if caption else " "},
            "action": {"buttons": wb}
        }
    }
    
    res = safe_post(url, headers, data)
    if res and res.status_code == 200:
        logger.info(f"✅ Image with buttons sent to {to_phone}")
        return res.json()
    else:
        # Fallback: send image and buttons separately
        logger.warning(f"⚠️ Image with buttons failed, falling back to separate messages")
        # Send image first
        img_data = {
            "messaging_product": "whatsapp",
            "to": to_phone,
            "type": "image",
            "image": {"link": image_url, "caption": caption}
        }
        safe_post(url, headers, img_data)
        time.sleep(0.3)
        # Then send buttons
        return _send_buttons_in_batches(to_phone, "Select an option:", buttons, url, headers)

# ── HELPERS ───────────────────────────────────────────────────────────────────

def _text_message(to: str, text: str) -> dict:
    text = text.strip()
    if len(text) > 4000:
        text = text[:3997] + "..."
    return {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text or "Hello 👋"}
    }


def _button_message(to: str, text: str, buttons: list) -> dict:
    """Build an interactive button payload (max 3 buttons)."""
    wb = []
    for btn in buttons[:3]:
        title = _clean_button_text(btn["text"], 20)
        value = str(btn["value"])[:256]
        wb.append({
            "type": "reply",
            "reply": {"id": value, "title": title}
        })

    body_text = text.strip() or "Choose an option:"

    if not wb:
        return _text_message(to, body_text)

    return {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {"buttons": wb}
        }
    }


def _send_buttons_in_batches(to: str, content: str, buttons: list, url: str, headers: dict):
    """Send plain buttons 3 at a time (WhatsApp limit)."""
    batches = [buttons[i:i+3] for i in range(0, len(buttons), 3)]

    data = _button_message(to, content, batches[0])
    res  = safe_post(url, headers, data)

    if res and res.status_code == 200:
        for batch in batches[1:]:
            time.sleep(0.4)
            safe_post(url, headers, _button_message(to, "📋 More options", batch))
        return res.json()
    else:
        # Fallback to plain text if buttons fail
        return safe_post(url, headers, _text_message(to, content))


def _send_list_message(to: str, content: str, buttons: list, url: str, headers: dict):
    """
    Send a WhatsApp List Message for buttons_grid.
    
    WhatsApp list messages support up to 10 sections × 10 rows = 100 items.
    We split every 10 buttons into one section.
    If there are more than 100 buttons we truncate (very unlikely for hotels/categories).
    
    Falls back to batched plain buttons if there are ≤ 3 items (list needs ≥ 1 row
    but interactive buttons look nicer for very small sets).
    """
    if len(buttons) <= 3:
        # For tiny sets, plain interactive buttons look cleaner than a list
        return _send_buttons_in_batches(to, content, buttons, url, headers)

    # Build sections (max 10 rows each, max 10 sections)
    MAX_ROWS_PER_SECTION = 10
    MAX_SECTIONS = 10
    all_buttons = buttons[:MAX_ROWS_PER_SECTION * MAX_SECTIONS]  # hard cap at 100

    sections = []
    for i in range(0, len(all_buttons), MAX_ROWS_PER_SECTION):
        chunk = all_buttons[i:i + MAX_ROWS_PER_SECTION]
        rows  = []
        for btn in chunk:
            row_title = _clean_button_text(btn["text"], 24)
            row_id    = str(btn["value"])[:200]
            rows.append({"id": row_id, "title": row_title})
        sections.append({"rows": rows})

    body_text   = content.strip() or "Please choose an option:"
    # WhatsApp body text limit is 1024 chars
    if len(body_text) > 1024:
        body_text = body_text[:1021] + "..."

    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": body_text},
            "action": {
                "button": "Select Option",   # The button label that opens the list
                "sections": sections
            }
        }
    }

    res = safe_post(url, headers, data)

    if res and res.status_code == 200:
        logger.info(f"✅ List message sent to {to} with {len(all_buttons)} options")
        return res.json()
    else:
        # Fallback: send as batched plain buttons
        logger.warning(f"⚠️ List message failed for {to}, falling back to button batches")
        return _send_buttons_in_batches(to, content, buttons, url, headers)


def _clean_button_text(text: str, max_len: int) -> str:
    text = re.sub(r'[^\w\s₹\-\.\/\?\!\u2600-\u26FF\u2700-\u27BF]', '', str(text))
    text = re.sub(r'\s+', ' ', text).strip()
    if len(text) > max_len:
        text = text[:max_len - 2] + ".."
    return text or "Option"


# ── CONVENIENCE FUNCTIONS (unchanged API) ─────────────────────────────────────

def send_raw_text(to_phone: str, text: str, sender_phone_number_id: str):
    sender_config = get_whatsapp_config(sender_phone_number_id)
    if not sender_config:
        return False

    url = f"https://graph.facebook.com/v18.0/{sender_config['phone_number_id']}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    res = safe_post(url, headers, _text_message(to_phone, text))
    return res and res.status_code == 200


def send_raw_buttons(to_phone: str, text: str, buttons: list, sender_phone_number_id: str):
    sender_config = get_whatsapp_config(sender_phone_number_id)
    if not sender_config:
        return False

    url = f"https://graph.facebook.com/v18.0/{sender_config['phone_number_id']}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    return bool(_send_buttons_in_batches(to_phone, text, buttons, url, headers))