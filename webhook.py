from flask import render_template, Flask, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO, join_room
from agent.session_manager import start_session_manager
import json
import os
import logging
from dotenv import load_dotenv
from datetime import datetime
import re
from chats.routes import register_chat_routes
from chats.delete_routes import register_delete_routes
from chats.message_handler import process_incoming_message
from chats.queue_manager import user_queue_manager
from database.database import (
    save_or_update_whatsapp_number,
    get_whatsapp_config,
    update_whatsapp_metadata,
    get_all_active_whatsapp_numbers
)
from services.meta_api import get_whatsapp_number_metadata

load_dotenv('.env')

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
)
logger = logging.getLogger(__name__)

ACCESS_TOKEN = os.getenv('ACCESS_TOKEN')
VERIFY_TOKEN = os.getenv('VERIFY_TOKEN')

app = Flask(__name__)

CORS(
    app,
    resources={r"/*": {"origins": "*"}},
    supports_credentials=True,
    allow_headers=["Content-Type", "Authorization", "ngrok-skip-browser-warning"],
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],  
    automatic_options=True    
)

  
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode='threading',
    cors_credentials=True,
    logger=False,
    engineio_logger=False,
    ping_timeout=60,       
    ping_interval=25,
)

app.socketio = socketio

from bot import _agent as travel_agent    
 
def _get_session(session_key: str):
    """Return the live session dict for a given key, or None."""
    return travel_agent.sessions.get(session_key)
 
def _reset_session(user_phone: str, business_phone: str, state: dict):
    """Hard-reset a user's session (called by session manager)."""
    travel_agent._reset_to_welcome(user_phone, business_phone, state)
 
start_session_manager(
    get_session_fn = _get_session,
    reset_fn       = _reset_session,
    openai_client  = travel_agent.client,   # reuse existing OpenAI client
)


# ── SOCKET EVENTS ─────────────────────────────────────────────────────────────

@socketio.on('join')
def handle_join_legacy(data):
    room = data.get('room') or data.get('display_phone_number')
    if room:
        join_room(room)
        logger.info(f"🔗 Client joined room (legacy): {room}")

@socketio.on('send_message_websocket')
def handle_ws_send(data):
    logger.info("=" * 60)
    logger.info("📨 WebSocket send_message_websocket triggered")
    logger.info(f"📦 Raw data received: {data}")
    
    phone = data.get('user_phone')
    message = data.get('message')
    display_no = data.get('display_phone_number')
    
    logger.info(f"📱 Extracted values:")
    logger.info(f"   - user_phone: {phone}")
    logger.info(f"   - message: {message}")
    logger.info(f"   - display_phone_number: {display_no}")
    
    # Get proper phone_number_id from database by searching with display_number
    phone_number_id = None
    actual_display_number = display_no
    
    if not display_no:
        logger.error("❌ Missing display_phone_number in request")
        return
    
    try:
        from database.database import whatsapp_numbers
        
        # Search by display_number (NOT phone_number_id)
        normalized_display = re.sub(r'[^\d]', '', str(display_no))
        logger.info(f"🔍 Looking up WhatsApp config for normalized display number: {normalized_display}")
        
        config = whatsapp_numbers.find_one({
            "$or": [
                {"display_number": normalized_display},
                {"display_phone_number_raw": normalized_display},
                {"display_phone_number": {"$regex": f".*{normalized_display}$"}}
            ],
            "is_active": True
        })
        
        logger.info(f"📋 Config retrieved: {config}")
        
        if config:
            phone_number_id = config.get('phone_number_id')
            actual_display_number = config.get('display_number') or config.get('display_phone_number_raw')
            logger.info(f"✅ Found phone_number_id: {phone_number_id}")
            logger.info(f"📞 Normalized display number: {actual_display_number}")
        else:
            logger.error(f"❌ No WhatsApp config found for display number: {display_no}")
            logger.error(f"   Please check that number {display_no} is registered in whatsapp_numbers collection")
            return
            
    except Exception as e:
        logger.error(f"❌ Error fetching WhatsApp config: {e}", exc_info=True)
        return
    
    # Validate required fields
    if not phone:
        logger.error("❌ Missing user_phone in request")
        return
    
    if not message:
        logger.error("❌ Missing message content")
        return
    
    if not phone_number_id:
        logger.error(f"❌ No phone_number_id resolved for display_no: {display_no}")
        return
    
    logger.info(f"✅ All validations passed")
    
    try:
        from chats.whatsapp_sender import send_whatsapp_message
        from database.database import messages as msg_col, get_or_create_user
        
        # Get or create user
        logger.info(f"👤 Getting/Creating user for phone: {phone}")
        user = get_or_create_user(phone, actual_display_number, phone_number_id)
        logger.info(f"✅ User retrieved/created: user_id={user.get('user_id')}")
        
        # Save message to database
        message_doc = {
            "user_phone": phone,
            "user_id": user["user_id"],
            "message": message,
            "from": "partner",
            "timestamp": datetime.utcnow(),
            "display_phone_number_raw": actual_display_number,
            "sender_phone_number_id": phone_number_id
        }
        
        logger.info(f"💾 Saving message to database")
        insert_result = msg_col.insert_one(message_doc)
        logger.info(f"✅ Message saved to DB with _id: {insert_result.inserted_id}")
        
        # Send via WhatsApp API
        logger.info(f"📤 Attempting to send WhatsApp message via API...")
        
        result = send_whatsapp_message(
            phone,
            {"type": "text", "content": message},
            phone_number_id  # This now contains the actual phone_number_id from Meta
        )
        
        logger.info(f"📊 send_whatsapp_message result: {result}")
        
        if result:
            logger.info(f"✅✅✅ SUCCESS: Agent message sent to {phone}")
            
            # Emit back to confirm delivery
            emit_new_message(phone, {
                "from": "partner",
                "message": {"type": "text", "content": message},
                "timestamp": datetime.utcnow().isoformat() + 'Z'
            }, actual_display_number)
            logger.info(f"✅ Confirmation emitted")
        else:
            logger.error(f"❌❌❌ FAILED: WhatsApp API call failed for {phone}")
            
    except Exception as e:
        logger.error(f"❌❌❌ Exception in handle_ws_send: {e}", exc_info=True)
    
    logger.info("=" * 60)


# ── EMIT HELPER ───────────────────────────────────────────────────────────────

def emit_new_message(user_phone, message_data, display_phone_number):
    """
    Emit a message (user, bot, or system) to the frontend room.
    display_phone_number is the room key — must match what frontend joins.
    """
    try:
        socketio.emit('new_message', {
            'user_phone': user_phone,
            'message': message_data
        }, room=display_phone_number)
        logger.info(
            f"📡 Emitted [{message_data.get('from')}] message "
            f"to room {display_phone_number} for {user_phone}"
        )
    except Exception as e:
        logger.error(f"❌ emit_new_message error: {e}")


app.emit_new_message = emit_new_message


# ── AUTO TEMPLATE HELPER ──────────────────────────────────────────────────────

def _ensure_template_for_number(phone_number_id: str, waba_id: str):
    """
    Called automatically when Meta fires a registration/update event for a
    phone number. Ensures this number has a welcome template:
      1. DB already has mapping  → do nothing (already set up)
      2. DB miss + Meta has real custom template → reuse it, save to DB
      3. DB miss + Meta has no custom template   → create new, save to DB
    This runs in the webhook handler so it must never raise — all errors logged.
    """
    try:
        from database.database import (
            get_template_mapping, save_template_mapping,
            get_next_template_index, save_waba_id,
        )
        from services.meta_templates import (
            find_any_welcome_template, create_welcome_template, DEFAULT_BODY,
        )

        # Always persist waba_id — may not be stored yet for brand-new numbers
        if waba_id:
            save_waba_id(phone_number_id, waba_id)

        # ── Step 1: DB cache hit → nothing to do ─────────────────────────────
        existing_mapping = get_template_mapping(phone_number_id)
        if existing_mapping:
            mapped_name = existing_mapping.get("template_name", "")
            # If DB points to hello_world (Meta default), ignore — create real template
            if mapped_name in ("hello_world",):
                logger.info(
                    f"⏭️  DB mapping for {phone_number_id} is '{mapped_name}' "
                    f"(Meta default) — will create a real template instead"
                )
            else:
                logger.info(
                    f"✅ Template already mapped for {phone_number_id}: "
                    f"'{mapped_name}' — skipping creation"
                )
                return

        # ── Step 2: Scan Meta for any existing real template ─────────────────
        existing_template = find_any_welcome_template(waba_id)
        if existing_template:
            template_name = existing_template.get("name")
            status        = existing_template.get("status", "UNKNOWN")
            body_text     = DEFAULT_BODY
            for component in existing_template.get("components", []):
                if component.get("type") == "BODY":
                    body_text = component.get("text", DEFAULT_BODY)
                    break
            save_template_mapping(phone_number_id, waba_id, template_name, status, body_text)
            logger.info(
                f"♻️  Reused existing Meta template '{template_name}' "
                f"for new number {phone_number_id}"
            )
            return

        # ── Step 3: No real template on Meta → create a fresh one ────────────
        index         = get_next_template_index()
        template_name = f"welcome_message_template_{index}"
        logger.info(
            f"🆕 Auto-creating template '{template_name}' "
            f"for newly registered number {phone_number_id}"
        )
        create_welcome_template(waba_id, template_name)
        save_template_mapping(phone_number_id, waba_id, template_name, "PENDING", DEFAULT_BODY)
        logger.info(f"✅ Template '{template_name}' submitted and mapped to {phone_number_id}")

    except Exception as e:
        logger.error(
            f"❌ _ensure_template_for_number error for {phone_number_id}: {e}",
            exc_info=True,
        )


# ── CORS HEADERS ──────────────────────────────────────────────────────────────

@app.before_request
def handle_preflight():
    if request.method == 'OPTIONS':
        response = app.make_default_options_response()
        response.headers.update({
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type, Authorization, ngrok-skip-browser-warning',
            'Access-Control-Allow-Methods': 'GET, POST, PUT, PATCH, DELETE, OPTIONS',
            'Access-Control-Allow-Credentials': 'true',
            'Access-Control-Max-Age': '3600',
        })
        return response


# ── REGISTER ROUTES ───────────────────────────────────────────────────────────

register_chat_routes(app)
register_delete_routes(app)


# ── WEBHOOK VERIFY (GET) ──────────────────────────────────────────────────────

@app.route('/webhook', methods=['GET'])
def verify_webhook():
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')

    if mode == 'subscribe' and token == VERIFY_TOKEN:
        return challenge, 200

    return "Verification failed", 403


# ── HOME & STATUS ─────────────────────────────────────────────────────────────

@app.route('/')
def home():
    return render_template('index.html')


@app.route('/status')
def status():
    return jsonify({"ok": True})


# ── WEBHOOK RECEIVE (POST) ────────────────────────────────────────────────────

@app.route('/webhook', methods=['POST'])
def webhook():
    """
    FIX: Always returns 200 immediately.
    All processing is handed to user_queue_manager which runs in background.
    WhatsApp requires 200 within 5 seconds — never block here.
    """
    try:
        data = request.get_json(silent=True)

        if not data:
            logger.warning("⚠️ Webhook received empty/invalid JSON")
            return jsonify({"status": "ok"}), 200

        logger.info("📨 Incoming webhook")

        if 'entry' in data:
            for entry in data['entry']:
                waba_id = entry.get('id')   # 🔥 NEW — WhatsApp Business Account ID

                for change in entry.get('changes', []):
                    value = change.get('value', {})

                    metadata = value.get('metadata', {})
                    phone_number_id = metadata.get('phone_number_id')

                    if phone_number_id:
                        try:
                            config, is_new = save_or_update_whatsapp_number(phone_number_id)

                            # 🔥 NEW — always sync waba_id (cheap, idempotent)
                            if waba_id:
                                from database.database import save_waba_id
                                save_waba_id(phone_number_id, waba_id)

                            # ── Ensure this number has a welcome template ─────
                            # Called on EVERY message — returns instantly from DB
                            # cache if template already exists. Only hits Meta API
                            # the very first time a number has no template mapped.
                            if waba_id:
                                try:
                                    _ensure_template_for_number(phone_number_id, waba_id)
                                except Exception as te:
                                    logger.error(f"❌ Template ensure error for {phone_number_id}: {te}")

                            if is_new:
                                logger.info(f"📱 New number: {phone_number_id}")
                                meta_metadata = get_whatsapp_number_metadata(
                                    phone_number_id, ACCESS_TOKEN
                                )
                                if meta_metadata:
                                    update_whatsapp_metadata(phone_number_id, meta_metadata)
                            else:
                                logger.info(f"🔄 Existing number: {phone_number_id}")

                        except Exception as e:
                            logger.error(f"❌ Phone number save error: {e}")

                    for message_data in value.get('messages', []):
                        phone = message_data.get('from', 'unknown')

                        # Resolve display phone number for room routing
                        display_phone_number = phone_number_id
                        if phone_number_id:
                            try:
                                sender_config = get_whatsapp_config(phone_number_id)
                                if sender_config:
                                    display_phone_number = (
                                        sender_config.get("display_phone_number_raw")
                                        or sender_config.get("display_number")
                                        or phone_number_id
                                    )
                            except Exception as e:
                                logger.error(f"❌ Config lookup error: {e}")

                        # Enqueue — returns immediately, processed in background
                        try:
                            user_queue_manager.enqueue(
                                phone=phone,
                                message_data=message_data,
                                handler_fn=process_incoming_message,
                                sender_phone_number_id=phone_number_id,
                                emit_fn=emit_new_message,
                                display_phone_number=display_phone_number
                            )
                        except Exception as e:
                            logger.error(f"❌ Queue enqueue error for {phone}: {e}")

                    # ── Auto-create template on number registration events ────
                    # Meta fires these fields when a number is added/registered:
                    #   • phone_number_quality_update — number status changes
                    #   • account_update             — account verified/banned etc.
                    # phone_number_id comes from value directly for these events.
                    field = change.get('field', '')
                    if field in ('phone_number_quality_update', 'account_update'):
                        event_phone_id = value.get('phone_number_id') or phone_number_id
                        if event_phone_id and waba_id:
                            logger.info(
                                f"📲 Number registration event detected "
                                f"(field='{field}') for {event_phone_id} — "
                                f"ensuring template exists"
                            )
                            try:
                                _ensure_template_for_number(event_phone_id, waba_id)
                            except Exception as e:
                                logger.error(
                                    f"❌ Auto template creation failed for "
                                    f"{event_phone_id}: {e}"
                                )

    except Exception as e:
        # FIX: ALWAYS return 200 even if we crash — WhatsApp must not retry
        logger.error(f"❌ Webhook processing error: {e}", exc_info=True)

    return jsonify({"status": "ok"}), 200


# ── AGENT TAKEOVER ────────────────────────────────────────────────────────────

@app.route('/agent/takeover', methods=['POST'])
def agent_takeover():
    """Agent takes over a chat."""
    try:
        data = request.get_json()
        user_phone = data.get('user_phone')
        agent_phone = data.get('agent_phone', 'Agent')
        agent_name = data.get('agent_name', agent_phone)
        display_phone_number = data.get('display_phone_number')

        if not user_phone:
            return jsonify({"error": "user_phone required"}), 400

        from chats.message_handler import agent_takeover_chat
        agent_takeover_chat(user_phone, agent_phone)

        try:
            config = get_whatsapp_config(display_phone_number) if display_phone_number else None
            phone_number_id = config.get('phone_number_id') if config else None

            if phone_number_id:
                from chats.whatsapp_sender import send_whatsapp_message
                send_whatsapp_message(
                    user_phone,
                    {
                        "type": "text",
                        "content": f"👤 You are now connected with a live agent."
                    },
                    phone_number_id
                )
        except Exception as e:
            logger.error(f"❌ Failed to send WhatsApp takeover message: {e}")

        emit_new_message(
            user_phone=user_phone,
            message_data={
                "from": "system",
                "message": {
                    "type": "text",
                    "content": f"👤 Agent {agent_name} has taken over the chat. Ai Agent responses are now disabled."
                },
                "timestamp": datetime.utcnow().isoformat() + 'Z'
            },
            display_phone_number=display_phone_number
        )

        return jsonify({"success": True, "message": "Agent has taken over"}), 200

    except Exception as e:
        logger.error(f"❌ agent_takeover error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


# ── AGENT RELEASE ─────────────────────────────────────────────────────────────

@app.route('/agent/release', methods=['POST'])
def agent_release():
    """Release chat back to bot."""
    try:
        data = request.get_json()
        user_phone = data.get('user_phone')
        display_phone_number = data.get('display_phone_number')

        if not user_phone:
            return jsonify({"error": "user_phone required"}), 400

        from chats.message_handler import agent_release_chat
        agent_release_chat(user_phone)

        try:
            config = get_whatsapp_config(display_phone_number) if display_phone_number else None
            phone_number_id = config.get('phone_number_id') if config else None

            if phone_number_id:
                from chats.whatsapp_sender import send_whatsapp_message
                send_whatsapp_message(
                    user_phone,
                    {
                        "type": "text",
                        "content": "🤖 You have been reconnected with our Ai Agent."
                    },
                    phone_number_id
                )
        except Exception as e:
            logger.error(f"❌ Failed to send WhatsApp release message: {e}")

        emit_new_message(
            user_phone=user_phone,
            message_data={
                "from": "system",
                "message": {
                    "type": "text",
                    "content": "🤖 Bot has resumed control. You can now use bot features again."
                },
                "timestamp": datetime.utcnow().isoformat() + 'Z'
            },
            display_phone_number=display_phone_number
        )

        return jsonify({"success": True, "message": "Bot resumed"}), 200

    except Exception as e:
        logger.error(f"❌ agent_release error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


# ── AGENT STATUS ──────────────────────────────────────────────────────────────

@app.route('/agent/status/<user_phone>', methods=['GET'])
def agent_status(user_phone):
    """Check if agent is active for this chat."""
    from chats.message_handler import is_agent_active
    return jsonify({
        "agent_active": is_agent_active(user_phone),
        "user_phone": user_phone
    }), 200


# ── PHONE NUMBER ROUTES ───────────────────────────────────────────────────────

@app.route('/phone-numbers', methods=['GET'])
def list_phone_numbers():
    numbers = get_all_active_whatsapp_numbers()
    return jsonify({"numbers": numbers}), 200


@app.route('/phone-number/<phone_number_id>', methods=['GET'])
def get_phone_number(phone_number_id):
    config = get_whatsapp_config(phone_number_id)
    if config:
        return jsonify(config), 200
    return jsonify({"error": "Not found"}), 404


@app.route('/sync-number-metadata/<phone_number_id>', methods=['POST'])
def sync_number_metadata(phone_number_id):
    metadata = get_whatsapp_number_metadata(phone_number_id, ACCESS_TOKEN)
    if metadata:
        update_whatsapp_metadata(phone_number_id, metadata)
        return jsonify({"status": "success", "metadata": metadata}), 200
    return jsonify({"error": "Failed"}), 400


# ── HEALTH & QUEUE ────────────────────────────────────────────────────────────

@app.route('/health', methods=['GET', 'OPTIONS'])
def health():
    if request.method == 'OPTIONS':
        return '', 200
    stats = user_queue_manager.stats()
    return jsonify({"status": "ok", "queue": stats})


@app.route('/queue/stats', methods=['GET'])
def queue_stats():
    return jsonify(user_queue_manager.stats())

@app.route('/plan/status', methods=['GET'])    
def plan_status():
    
    try:
        from plan_checker import is_bot_allowed
        owner_phone = request.args.get('owner_phone')
        if not owner_phone:
            return jsonify({"error": "owner_phone required"}), 400

        bot_allowed, reason = is_bot_allowed(owner_phone)
        return jsonify({
            "plan_active": bot_allowed,
            "reason": reason
        }), 200
    except Exception as e:
        logger.error(f"❌ plan_status error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/agent/release-all', methods=['POST'])
def release_all_agents():
    """
    Restart Bot button — verifies plan is active via WordPress,
    then releases ALL agent sessions for this business number at once.
    No need to go user by user.
    """
    try:
        from plan_checker import is_bot_allowed
        from chats.message_handler import agent_release_chat

        data = request.get_json()
        display_phone_number = data.get('display_phone_number')
        owner_phone = data.get('owner_phone')  # business owner's phone to check plan

        if not display_phone_number:
            return jsonify({"error": "display_phone_number required"}), 400

        if not owner_phone:
            return jsonify({"error": "owner_phone required"}), 400

        # Step 1: Verify plan is active before releasing anything
        bot_allowed, reason = is_bot_allowed(owner_phone)
        if not bot_allowed:
            return jsonify({
                "success": False,
                "error": f"Plan still not active ({reason}). Please renew your plan first."
            }), 403

        # Step 2: Find ALL agent sessions for this business number
        # Get all users under this display_phone_number
        from database.database import whatsapp_numbers, db
        import re

        normalized = re.sub(r'[^\d]', '', str(display_phone_number))

        # Get all agent sessions that are active
        active_sessions = list(db.agent_sessions.find({"active": True}))

        if not active_sessions:
            return jsonify({
                "success": True,
                "message": "No active agent sessions found. Bot is already running.",
                "released_count": 0
            }), 200

        # Step 3: Release every active session
        released_count = 0
        released_phones = []

        for session in active_sessions:
            user_phone = session.get('user_phone')
            if not user_phone:
                continue

            try:
                agent_release_chat(user_phone)
                released_phones.append(user_phone)
                released_count += 1

                # Send WhatsApp message to each user that bot is back
                try:
                    config = get_whatsapp_config(display_phone_number)
                    phone_number_id = config.get('phone_number_id') if config else None
                    if phone_number_id:
                        from chats.whatsapp_sender import send_whatsapp_message
                        send_whatsapp_message(
                            user_phone,
                            {
                                "type": "text",
                                "content": "🤖 Our AI assistant is back online and ready to help you!"
                            },
                            phone_number_id
                        )
                except Exception as e:
                    logger.error(f"❌ Failed to send restart message to {user_phone}: {e}")

                # Emit system message to dashboard for each user
                emit_new_message(
                    user_phone=user_phone,
                    message_data={
                        "from": "system",
                        "message": {
                            "type": "text",
                            "content": "✅ Bot restarted. AI assistant is now active for this user."
                        },
                        "timestamp": datetime.utcnow().isoformat() + 'Z'
                    },
                    display_phone_number=display_phone_number
                )

            except Exception as e:
                logger.error(f"❌ Failed to release session for {user_phone}: {e}")

        logger.info(f"✅ Released {released_count} agent sessions for {display_phone_number}")

        return jsonify({
            "success": True,
            "message": f"Bot restarted for {released_count} user(s).",
            "released_count": released_count,
            "released_phones": released_phones
        }), 200

    except Exception as e:
        logger.error(f"❌ release_all_agents error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

# ── ENTRYPOINT ────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    logger.info("🚀 WhatsApp Bot starting with REALTIME (threading mode)...")
    socketio.run(
        app,
        port=5000,
        host='0.0.0.0',
        debug=False,
        use_reloader=False,
        allow_unsafe_werkzeug=True
    )