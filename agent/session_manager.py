# agent/session_manager.py

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, Callable, Optional

logger = logging.getLogger(__name__)

 

# PRODUCTION:
SESSION_DURATION_HOURS  = 24     
REMINDER_INTERVAL_HOURS = 4      
REMINDER_MAX_COUNT      = 6      
CHECK_INTERVAL_SECS     = 60

 
# SESSION_DURATION_HOURS  = 0.083    
# REMINDER_INTERVAL_HOURS = 0.008    
# REMINDER_MAX_COUNT      = 6
# CHECK_INTERVAL_SECS     = 10

 
_timers: Dict[str, dict] = {}
_lock   = threading.Lock()


def touch(session_key: str):
    """
    Call every time a user sends a message.
    - If new session  → start the 24h clock NOW
    - If existing     → do NOT reset session_started_at (24h clock keeps running)
                        but reminder_count and last_reminder_at stay too
                        (already-sent reminders are already counted)
    """
    now = datetime.utcnow()
    with _lock:
        if session_key not in _timers:
 
            _timers[session_key] = {
                "session_started_at": now,
                "last_reminder_at":   None,
                "reminder_count":     0,
            }
            logger.info(f"🆕 New session timer started: {session_key} | expires at {now + timedelta(hours=SESSION_DURATION_HOURS)}")
        else:
 
            logger.info(
                f"⏱️ Session active: {session_key} | "
                f"reminders sent: {_timers[session_key]['reminder_count']}/{REMINDER_MAX_COUNT}"
            )


def remove(session_key: str):
    """Remove timer entry after reset or booking confirmed."""
    with _lock:
        _timers.pop(session_key, None)
    logger.info(f"🗑️ Timer removed: {session_key}")

 
def _generate_reminder_text(context: dict, openai_client, reminder_number: int) -> str:
    destination    = context.get("destination", "")
    service_type   = context.get("service_type", "")
    selected_hotel = context.get("selected_hotel", "")
    selected_pkg   = (context.get("selected_package") or {}).get("package_name", "")
    step     = context.get("step", "")
    guests   = context.get("guests", "")
    check_in = context.get("check_in", "")

    summary_parts = []
    if service_type:   summary_parts.append(f"Service: {service_type}")
    if destination:    summary_parts.append(f"Destination: {destination}")
    if selected_hotel: summary_parts.append(f"Hotel: {selected_hotel}")
    if selected_pkg:   summary_parts.append(f"Package: {selected_pkg}")
    if guests:         summary_parts.append(f"Guests: {guests}")
    if check_in:       summary_parts.append(f"Check-in: {check_in}")
    if step:           summary_parts.append(f"Last step: {step}")

    summary = ", ".join(summary_parts) if summary_parts else "user had just started browsing"

    prompt = (
        f"You are a friendly travel booking assistant on WhatsApp.\n"
        f"A user stopped responding mid-conversation. Here is where they left off:\n"
        f"{summary}\n\n"
        f"This is reminder {reminder_number} of {REMINDER_MAX_COUNT}. "
        f"Write a short warm 1-2 sentence message asking if they want to continue. "
        f"Make it slightly different from a standard reminder — vary tone and wording each time. "
        f"Plain text only, no formatting, no buttons. "
        f"End with something like 'Would you like to continue?'"
    )

    try:
        resp = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
            temperature=0.9,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"LLM reminder failed: {e}")
        if destination:
            return f"Hi! You were looking at {service_type or 'travel'} options for {destination}. Would you like to continue?"
        return "Hi! You left a booking in progress. Would you like to continue?"


 
def _send_reminder(user_phone: str, business_phone: str, context: dict, openai_client, reminder_number: int):
    try:
        from database.database import get_whatsapp_config
        from chats.whatsapp_sender import send_whatsapp_message

        config          = get_whatsapp_config(business_phone)
        phone_number_id = config.get("phone_number_id") if config else None

        if not phone_number_id:
            logger.warning(f"⚠️ No phone_number_id for {business_phone} — skipping reminder")
            return

        reminder_text = _generate_reminder_text(context, openai_client, reminder_number)
        logger.info(f"📝 Reminder #{reminder_number} text: {reminder_text}")

        message = {
            "type":    "buttons",
            "content": reminder_text,
            "buttons": [
                {"text": "✅ Yes, Continue", "value": "resume_session"},
                {"text": "❌ No, Exit",       "value": "exit_session"},
            ],
        }

        result = send_whatsapp_message(user_phone, message, phone_number_id)
        logger.info(f"📩 Reminder #{reminder_number}/{REMINDER_MAX_COUNT} sent to {user_phone} | result: {result}")

    except Exception as e:
        logger.error(f"❌ _send_reminder error for {user_phone}: {e}", exc_info=True)


 
def _checker_loop(
    get_session_fn: Callable[[str], Optional[dict]],
    reset_fn:       Callable[[str, str, dict], None],
    openai_client,
):
    logger.info("🔁 SessionManager checker loop started")
    while True:
        time.sleep(CHECK_INTERVAL_SECS)

        now = datetime.utcnow()
        logger.info(f"🔍 SessionManager tick | active timers: {len(_timers)}")

        with _lock:
            keys = list(_timers.keys())

        for sk in keys:
            with _lock:
                entry = _timers.get(sk)
            if not entry:
                continue

            session_started = entry["session_started_at"]
            last_reminder   = entry["last_reminder_at"]
            reminder_count  = entry["reminder_count"]

 
            session_age_hours = (now - session_started).total_seconds() / 3600

 
            since_last_hours = (
                (now - last_reminder).total_seconds() / 3600
                if last_reminder
                else session_age_hours
            )

            parts          = sk.split(":", 1)
            business_phone = parts[0] if len(parts) == 2 else "default"
            user_phone     = parts[1] if len(parts) == 2 else parts[0]

            logger.info(
                f"  → {sk} | session age: {session_age_hours*60:.1f}min | "
                f"reminders: {reminder_count}/{REMINDER_MAX_COUNT} | "
                f"since last reminder: {since_last_hours*3600:.0f}s"
            )

 
            if session_age_hours >= SESSION_DURATION_HOURS:
                logger.info(f"🔄 24H EXPIRED for {sk} — hard reset")
                state = {}
                reset_fn(user_phone, business_phone, state)
                remove(sk)
                continue

 
            if reminder_count >= REMINDER_MAX_COUNT:
                logger.info(f"  ✅ All {REMINDER_MAX_COUNT} reminders sent for {sk} — waiting for 24h reset")
                continue

 
            if since_last_hours >= REMINDER_INTERVAL_HOURS:
                reminder_number = reminder_count + 1
                logger.info(f"📣 Time for reminder #{reminder_number} → {sk}")
                session = get_session_fn(sk)
                context = session.get("context", {}) if session else {}
                _send_reminder(user_phone, business_phone, context, openai_client, reminder_number)
                with _lock:
                    if sk in _timers:
                        _timers[sk]["reminder_count"]   = reminder_number
                        _timers[sk]["last_reminder_at"] = now


 
def start_session_manager(
    get_session_fn: Callable,
    reset_fn:       Callable,
    openai_client,
):
    t = threading.Thread(
        target=_checker_loop,
        args=(get_session_fn, reset_fn, openai_client),
        daemon=True,
        name="SessionManager",
    )
    t.start()
    logger.info("✅ SessionManager background thread started")