# chats/message_handler.py - FIXED with Database Storage

import json
import re
from datetime import datetime
from database.database import messages, get_or_create_user, increment_user_message_count, get_whatsapp_config, update_username, db
from bot import process_message
from chats.whatsapp_sender import send_whatsapp_message
import os
from dotenv import load_dotenv
from plan_checker import is_bot_allowed, get_expired_response


load_dotenv('.env')

# REMOVE this line - NO MORE in-memory dictionary
# agent_active_sessions = {}


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
        return json.dumps({
            "type": "text",
            "content": response.get("content", "")
        })

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
        return json.dumps({
            "type": msg_type,
            "content": response.get("content", "")
        })


def agent_takeover_chat(user_phone, agent_phone=None):
    """Agent takes over the chat - STORE IN DATABASE"""
    try:
       
        db.agent_sessions.update_one(
            {"user_phone": user_phone},
            {"$set": {
                "active": True,
                "agent_phone": agent_phone,
                "taken_over_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }},
            upsert=True
        )
        print(f"✅ Agent took over chat for {user_phone} (saved to DB)")
        return True
    except Exception as e:
        print(f"❌ Error in agent_takeover_chat: {e}")
        return False


def agent_release_chat(user_phone):
    """Release chat back to bot"""
    try:
       
        result = db.agent_sessions.delete_one({"user_phone": user_phone})
        if result.deleted_count > 0:
            print(f"✅ Bot released for {user_phone} (removed from DB)")
            return True
        else:
            print(f"⚠️ No active session found for {user_phone}")
            return False
    except Exception as e:
        print(f"❌ Error in agent_release_chat: {e}")
        return False


def is_agent_active(user_phone):
    """Check if agent is actively handling this chat - CHECK DATABASE"""
    try:
        session = db.agent_sessions.find_one({"user_phone": user_phone, "active": True})
        is_active = session is not None
        if is_active:
            print(f"🔍 Agent ACTIVE for {user_phone}")
        else:
            print(f"🔍 Agent NOT active for {user_phone}")
        return is_active
    except Exception as e:
        print(f"❌ Error checking agent status: {e}")
        return False


def process_incoming_message(message_data, sender_phone_number_id=None, emit_fn=None, display_phone_number=None):
    """
    Process incoming WhatsApp message.
    """
    user_phone = message_data.get('from')
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

     
    agent_in_control = is_agent_active(user_phone)

    if agent_in_control:
        print(f"👤 Agent is in control for {user_phone} - bot DISABLED")
        
        
        user = get_or_create_user(user_phone, display_phone_number_raw)
        user_id = user["user_id"]

        messages.insert_one({
            "user_phone": user_phone,
            "user_id": user_id,
            "message": user_message,
            "from": "user",
            "timestamp": datetime.utcnow(),
            "sender_phone_number_id": sender_phone_number_id,
            "display_phone_number_raw": display_phone_number_raw
        })

       
        if emit_fn and display_phone_number:
            emit_fn(
                user_phone=user_phone,
                message_data={
                    "from": "user",
                    "message": user_message,
                    "timestamp": datetime.utcnow().isoformat() + 'Z'
                },
                display_phone_number=display_phone_number
            )
        
       
        print(f"✅ Message saved, bot response SKIPPED (agent in control)")
        return

    
 
    print(f"🤖 Agent NOT in control - processing with bot for {user_phone}")

 
    from plan_checker import is_bot_allowed, get_expired_response

    check_phone = display_phone_number_raw or user_phone
    bot_allowed, reason = is_bot_allowed(check_phone)

    if not bot_allowed:
        print(f"🚫 Plan expired for {user_phone} — reason: {reason}. Auto agent takeover.")

         
        already_taken = is_agent_active(user_phone)

        if not already_taken:
           
            user = get_or_create_user(user_phone, display_phone_number_raw)
            user_id = user["user_id"]

            messages.insert_one({
                "user_phone": user_phone,
                "user_id": user_id,
                "message": user_message,
                "from": "user",
                "timestamp": datetime.utcnow(),
                "sender_phone_number_id": sender_phone_number_id,
                "display_phone_number_raw": display_phone_number_raw
            })

           
            if emit_fn and display_phone_number:
                emit_fn(
                    user_phone=user_phone,
                    message_data={
                        "from": "user",
                        "message": user_message,
                        "timestamp": datetime.utcnow().isoformat() + 'Z'
                    },
                    display_phone_number=display_phone_number
                )

           
            agent_takeover_chat(user_phone, agent_phone="system_plan_expired")

           
            expired_response = get_expired_response(reason=reason)
            if sender_phone_number_id:
                try:
                    send_whatsapp_message(user_phone, expired_response, sender_phone_number_id)
                except Exception as e:
                    print(f"❌ Failed to send expired message: {e}")

            
            messages.insert_one({
                "user_phone": user_phone,
                "user_id": user_id,
                "message": json.dumps(expired_response),
                "from": "bot",
                "timestamp": datetime.utcnow(),
                "sender_phone_number_id": sender_phone_number_id,
                "display_phone_number_raw": display_phone_number_raw
            })

           
            if emit_fn and display_phone_number:
                emit_fn(
                    user_phone=user_phone,
                    message_data={
                        "from": "system",
                        "message": {
                            "type": "text",
                            "content": "⚠️ Plan expired. Bot auto-paused for this user. Click Restart Bot after renewing."
                        },
                        "timestamp": datetime.utcnow().isoformat() + 'Z'
                    },
                    display_phone_number=display_phone_number
                )

        else:
            
            print(f"⚠️ Already taken over for {user_phone}, skipping duplicate takeover.")

            user = get_or_create_user(user_phone, display_phone_number_raw)
            user_id = user["user_id"]

            messages.insert_one({
                "user_phone": user_phone,
                "user_id": user_id,
                "message": user_message,
                "from": "user",
                "timestamp": datetime.utcnow(),
                "sender_phone_number_id": sender_phone_number_id,
                "display_phone_number_raw": display_phone_number_raw
            })

            if emit_fn and display_phone_number:
                emit_fn(
                    user_phone=user_phone,
                    message_data={
                        "from": "user",
                        "message": user_message,
                        "timestamp": datetime.utcnow().isoformat() + 'Z'
                    },
                    display_phone_number=display_phone_number
                )

        return   
   

    user = get_or_create_user(user_phone, display_phone_number_raw)
    user_id = user["user_id"]

    increment_user_message_count(user_phone)

 
    if user_message.lower().startswith("my name is") or user_message.lower().startswith("i am"):
        name = user_message.replace("my name is", "").replace("i am", "").strip()
        update_username(user_phone, name)
        print(f"📝 Updated username for {user_phone}: {name}")

 
    messages.insert_one({
        "user_phone": user_phone,
        "user_id": user_id,
        "message": user_message,
        "from": "user",
        "timestamp": datetime.utcnow(),
        "sender_phone_number_id": sender_phone_number_id,
        "display_phone_number_raw": display_phone_number_raw
    })

    
    if emit_fn and display_phone_number:
        emit_fn(
            user_phone=user_phone,
            message_data={
                "from": "user",
                "message": user_message,
                "timestamp": datetime.utcnow().isoformat() + 'Z'
            },
            display_phone_number=display_phone_number
        )

    
    state = {
        "user_phone": user_phone,
        "step": "greeting",
        "context": {},
        "sender_phone_number_id": sender_phone_number_id,
        "user_id": user_id,
        "display_phone_number_raw": display_phone_number_raw
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
            "type": "buttons",
            "content": "⚠️ *Something went wrong!*\n\nPlease choose an option:",
            "buttons": [
                {"text": "🔄 Retry", "value": "retry_action"},
                {"text": "❌ Exit to Main Menu", "value": "exit_booking"},
            ]
        }

     
    serialized = _serialize_response(response)
    messages.insert_one({
        "user_phone": user_phone,
        "user_id": user_id,
        "message": serialized,
        "from": "bot",
        "timestamp": datetime.utcnow(),
        "sender_phone_number_id": sender_phone_number_id,
        "display_phone_number_raw": display_phone_number_raw
    })

    print(f"💾 Saved bot msg ({response.get('type')}): {serialized[:120]}…")

   
    if emit_fn and display_phone_number:
        try:
            emit_fn(
                user_phone=user_phone,
                message_data={
                    "from": "bot",
                    "message": response,
                    "timestamp": datetime.utcnow().isoformat() + 'Z'
                },
                display_phone_number=display_phone_number
            )
            print(f"📡 Emitted bot reply to frontend for {user_phone}")
        except Exception as e:
            print(f"⚠️ Failed to emit bot reply: {e}")

    
    send_whatsapp_message(user_phone, response, sender_phone_number_id)