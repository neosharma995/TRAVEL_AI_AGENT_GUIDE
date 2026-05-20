# bot.py
import copy
from dotenv import load_dotenv
from agent.ai_agent import AIHotelAgent

load_dotenv()

_agent = AIHotelAgent()


def process_message(user_input: str, phone: str, state: dict,
                    sender_phone_number_id: str = None) -> dict:
    if not user_input or not user_input.strip():
        return {"type": "text", "content": "Hi! Are you looking for hotels or travel packages?"}

    display_phone = _resolve_display_phone(sender_phone_number_id)
    
    try:
        response = _agent.execute(phone, user_input, state, business_phone=display_phone)
        
      
        session_key = f"{display_phone}:{phone}"
        if session_key in _agent.sessions:
            state["data"] = copy.deepcopy(_agent.sessions[session_key].get("context", {}))
        
        return response
        
    except Exception as e:
        import logging
        import traceback
        logger = logging.getLogger(__name__)
        logger.error(f"❌ Bot error for {phone}: {e}")
        traceback.print_exc()
        
        
        return {
            "type": "buttons",
            "content": "⚠️ *Something went wrong!*\n\nPlease choose an option:",
            "buttons": [
                {"text": "🔄 Retry", "value": "retry_action"},
                {"text": "❌ Exit to Main Menu", "value": "exit_booking"},
            ]
        }


def _resolve_display_phone(sender_phone_number_id: str) -> str:
    """Look up display phone number from DB using the Meta phone_number_id."""
    if not sender_phone_number_id:
        return "default"
    try:
        from database.database import get_whatsapp_config
        config = get_whatsapp_config(sender_phone_number_id)
        if config:
            phone = (
                config.get("display_phone_number_raw")
                or config.get("display_number")
                or config.get("phone_number")
                or sender_phone_number_id
            )
            return "".join(filter(str.isdigit, str(phone))) or sender_phone_number_id
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"resolve_display_phone error: {e}")
    return sender_phone_number_id


def reset_session(phone: str, sender_phone_number_id: str = None):
    display_phone = _resolve_display_phone(sender_phone_number_id)
    _agent.reset_session(phone, business_phone=display_phone)