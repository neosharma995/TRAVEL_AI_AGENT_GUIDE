# chats/message_handler.py  ── WITH PLAN EXPIRY CHECK
 

import json
import re
from datetime import datetime
from database.database import (
    messages, get_or_create_user, increment_user_message_count,
    get_whatsapp_config, update_username
)
from bot import process_message
from chats.whatsapp_sender import send_whatsapp_message
from plan_checker import is_bot_allowed, get_expired_response, invalidate_cache   # ← NEW
import os
from dotenv import load_dotenv

load_dotenv('.env')

 
agent_active_sessions = {}

 
def normalize_phone_number(phone_number):
    if not phone_number:
        return None
    normalized = re.sub(r'[^\d]', '', str(phone_number))
    if normalized.startswith('0'):
        normalized = normalized[1:]
    return normalized


def _serialize_response(response):
    """Convert bot response dict → JSON string for DB storage."""
    if not response:
        return json.dumps({"type": "text", "content": ""})

    msg_type = response.get("type", "text")

    if msg_type == "text":
        return json.dumps({"type": "text", "content": response.get("content", "")})

    elif msg_type in ("buttons", "buttons_grid"):
        return json.dumps({
            "type": msg_type,
            "content": response.get("content", ""),
            "buttons": response.get("buttons", [])
        })

    elif msg_type == "image":
        return json.dumps({
            "type": "image",
            "content": response.get("content", ""),
            "caption": response.get("caption", "")
        })

    elif msg_type == "multi":
        clean_responses = []
        for r in response.get("responses", []):
            sub_type = r.get("type", "text")
            if sub_type == "text":
                clean_responses.append({"type": "text", "content": r.get("content", "")})
            elif sub_type in ("buttons", "buttons_grid"):
                clean_responses.append({
                    "type": sub_type,
                    "content": r.get("content", ""),
                    "buttons": r.get("buttons", [])
                })
            elif sub_type == "image":
                clean_responses.append({
                    "type": "image",
                    "content": r.get("content", ""),
                    "caption": r.get("caption", "")
                })
            else:
                clean_responses.append({"type": sub_type, "content": r.get("content", "")})
        return json.dumps({"type": "multi", "responses": clean_responses})

    else:
        return json.dumps({"type": msg_type, "content": response.get("content", "")})

 

def process_incoming_message(
    message_data,
    sender_phone_number_id=None,
    emit_fn=None,
    display_phone_number=None
):
    user_phone   = message_data.get('from')
    user_message = ""

   
    if 'text' in message_data:
        user_message = message_data['text']['body'].strip()
    elif 'interactive' in message_data:
        interactive = message_data['interactive']
        if interactive['type'] == 'button_reply':
            user_message = interactive['button_reply']['id']
        elif interactive['type'] == 'list_reply':
            user_message = interactive['list_reply']['id']
    elif 'button' in message_data:
        user_message = message_data['button']['payload']

    print(f"📱 {user_phone} → {user_message}")

    
    display_phone_number_raw = None
    if display_phone_number:
        display_phone_number_raw = normalize_phone_number(display_phone_number)
    elif sender_phone_number_id:
        sender_config = get_whatsapp_config(sender_phone_number_id)
        if sender_config:
            dn = sender_config.get("display_phone_number_raw") or sender_config.get("display_number")
            if dn:
                display_phone_number_raw = normalize_phone_number(dn)
                display_phone_number = display_phone_number_raw

    
    user    = get_or_create_user(user_phone, display_phone_number_raw)
    user_id = user["user_id"]

     
    messages.insert_one({
        "user_phone":             user_phone,
        "user_id":                user_id,
        "message":                user_message,
        "from":                   "user",
        "timestamp":              datetime.utcnow(),
        "sender_phone_number_id": sender_phone_number_id,
        "display_phone_number_raw": display_phone_number_raw
    })

   
    if emit_fn and display_phone_number:
        emit_fn(
            user_phone=user_phone,
            message_data={
                "from":      "user",
                "message":   user_message,
                "timestamp": datetime.utcnow().isoformat() + 'Z'
            },
            display_phone_number=display_phone_number
        )

 
    business_phone = display_phone_number_raw or normalize_phone_number(sender_phone_number_id)

    if not business_phone:
     
        print(f"⚠️  No business_phone resolved for sender_id={sender_phone_number_id} — blocking bot")
        bot_allowed, expiry_reason = False, "no_business_phone"
    else:
        print(f"🔍 Plan check → business: {business_phone}  consumer: {user_phone}")
        bot_allowed, expiry_reason = is_bot_allowed(business_phone)

    if not bot_allowed:
        print(f"🚫 Bot DISABLED — business {business_phone} plan inactive (reason: {expiry_reason})")
        print(f"   Consumer {user_phone} will receive sorry message")

     
   
        already_taken_over = is_agent_active(user_phone)

        if not already_taken_over:
      
            agent_takeover_chat(user_phone)
            print(f"👤 Auto agent-takeover triggered for consumer {user_phone}")
            response = get_expired_response(reason=expiry_reason, business_phone=business_phone)
            _save_and_emit_bot_response(
                response, user_phone, user_id,
                sender_phone_number_id, display_phone_number_raw,
                display_phone_number, emit_fn
            )
            send_whatsapp_message(user_phone, response, sender_phone_number_id)
        else:
    
            print(f"🔇 Agent already in control for {user_phone} — not resending sorry message")
        return

 
    if is_agent_active(user_phone):
 
        agent_release_chat(user_phone)
        print(f"🤖 Plan active — auto-released agent, bot taking back control for {user_phone}")
 
    increment_user_message_count(user_phone)

    if user_message.lower().startswith("my name is") or user_message.lower().startswith("i am"):
        name = user_message.replace("my name is", "").replace("i am", "").strip()
        update_username(user_phone, name)
        print(f"📝 Updated username for {user_phone}: {name}")

   
    state = {
        "user_phone":             user_phone,
        "step":                   "greeting",
        "context":                {},
        "sender_phone_number_id": sender_phone_number_id,
        "user_id":                user_id,
        "display_phone_number_raw": display_phone_number_raw,
    }

   
    try:
        response = process_message(
            user_input=user_message,
            phone=user_phone,
            state=state,
            sender_phone_number_id=sender_phone_number_id,
        )
    except Exception as e:
        print("❌ Bot error:", e)
        import traceback
        traceback.print_exc()
        response = {
            "type":    "buttons",
            "content": "⚠️ *Something went wrong!*\n\nPlease choose an option:",
            "buttons": [
                {"text": "🔄 Retry",            "value": "retry_action"},
                {"text": "❌ Exit to Main Menu", "value": "exit_booking"},
            ]
        }

   
    _save_and_emit_bot_response(
        response, user_phone, user_id,
        sender_phone_number_id, display_phone_number_raw,
        display_phone_number, emit_fn
    )
    send_whatsapp_message(user_phone, response, sender_phone_number_id)


 

def _save_and_emit_bot_response(
    response, user_phone, user_id,
    sender_phone_number_id, display_phone_number_raw,
    display_phone_number, emit_fn
):
    serialized = _serialize_response(response)
    messages.insert_one({
        "user_phone":             user_phone,
        "user_id":                user_id,
        "message":                serialized,
        "from":                   "bot",
        "timestamp":              datetime.utcnow(),
        "sender_phone_number_id": sender_phone_number_id,
        "display_phone_number_raw": display_phone_number_raw
    })
    print(f"💾 Saved bot msg ({response.get('type')}): {serialized[:120]}…")

    if emit_fn and display_phone_number:
        try:
            emit_fn(
                user_phone=user_phone,
                message_data={
                    "from":      "bot",
                    "message":   response,
                    "timestamp": datetime.utcnow().isoformat() + 'Z'
                },
                display_phone_number=display_phone_number
            )
            print(f"📡 Emitted bot reply for {user_phone}")
        except Exception as e:
            print(f"⚠️ Failed to emit bot reply: {e}")

 
def agent_takeover_chat(user_phone, agent_phone=None):
    agent_active_sessions[user_phone] = {
        "active":        True,
        "agent_phone":   agent_phone,
        "taken_over_at": datetime.utcnow()
    }
    print(f"👤 Agent took over chat for {user_phone}")
    return True


def agent_release_chat(user_phone):
    """
    Call this when agent releases the chat (user upgrades their plan).
    Also clears the plan-checker cache so next message re-checks WP.
    """
    if user_phone in agent_active_sessions:
        del agent_active_sessions[user_phone]
        invalidate_cache(user_phone)   
        print(f"🤖 Bot restored for {user_phone}")
        return True
    return False


def is_agent_active(user_phone):
    session = agent_active_sessions.get(user_phone)
    return bool(session and session.get("active"))