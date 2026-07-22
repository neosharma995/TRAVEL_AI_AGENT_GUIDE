# database/database.py

from pymongo import MongoClient, ReturnDocument
import os
import re
from datetime import datetime

# MongoDB connection
client = MongoClient("mongodb+srv://raaj73906:Raaj6230097248@cluster0.fsyzvmn.mongodb.net/")
db = client["chat_db"]

messages = db["messages"]
mapping = db["mapping"]
whatsapp_numbers = db["whatsapp_numbers"]
users = db["users"]
message_templates = db["message_templates"]   # stores per-account template mapping
counters = db["counters"]                      # stores auto-incrementing template index


def normalize_phone_number(phone_number):
    """Normalize phone number - remove +, spaces, special characters"""
    if not phone_number:
        return None
    normalized = re.sub(r'[^\d]', '', str(phone_number))
    if normalized.startswith('0'):
        normalized = normalized[1:]
    return normalized


def save_or_update_whatsapp_number(phone_number_id, metadata=None):
    """Save or update WhatsApp number in database"""
    existing = whatsapp_numbers.find_one({"phone_number_id": phone_number_id})
    
    if existing:
        update_data = {
            "updated_at": datetime.utcnow(),
            "last_webhook_received": datetime.utcnow()
        }
        if metadata:
            if "display_phone_number" in metadata:
                raw_number = metadata["display_phone_number"]
                metadata["display_phone_number_raw"] = normalize_phone_number(raw_number)
                metadata["display_number"] = normalize_phone_number(raw_number)
            update_data.update(metadata)
        
        whatsapp_numbers.update_one(
            {"phone_number_id": phone_number_id},
            {"$set": update_data}
        )
        return existing, False
    else:
        display_raw = None
        display_normalized = None
        if metadata and metadata.get("display_phone_number"):
            display_raw = metadata["display_phone_number"]
            display_normalized = normalize_phone_number(display_raw)
        
        new_record = {
            "phone_number_id": phone_number_id,
            "display_number": display_normalized,
            "display_phone_number": display_raw,
            "display_phone_number_raw": display_normalized,
            "verified_name": metadata.get("verified_name") if metadata else None,
            "quality_rating": metadata.get("quality_rating") if metadata else None,
            "status": metadata.get("status") if metadata else "active",
            "partner_id": None,
            "waba_id": None,
            "is_active": True,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "last_webhook_received": datetime.utcnow()
        }
        if metadata:
            new_record.update(metadata)
        
        whatsapp_numbers.insert_one(new_record)
        return new_record, True


def get_whatsapp_config(identifier):
    """Works with phone_number_id OR display_number"""
    config = whatsapp_numbers.find_one({
        "phone_number_id": identifier,
        "is_active": True
    })
    
    if not config:
        normalized = normalize_phone_number(identifier)
        config = whatsapp_numbers.find_one({
            "$or": [
                {"display_number": normalized},
                {"display_phone_number_raw": normalized}
            ],
            "is_active": True
        })
    
    if not config:
        return None
    
    return {
        "phone_number_id": config.get("phone_number_id"),
        "display_number": config.get("display_number") or config.get("display_phone_number_raw"),
        "display_phone_number_raw": config.get("display_phone_number_raw"),
        "verified_name": config.get("verified_name"),
        "waba_id": config.get("waba_id"),
        "is_active": config.get("is_active", True)
    }


def update_whatsapp_metadata(phone_number_id, metadata):
    """Update metadata for a WhatsApp number"""
    if metadata and "display_phone_number" in metadata:
        metadata["display_phone_number_raw"] = normalize_phone_number(metadata["display_phone_number"])
        metadata["display_number"] = normalize_phone_number(metadata["display_phone_number"])
    
    whatsapp_numbers.update_one(
        {"phone_number_id": phone_number_id},
        {"$set": metadata}
    )


def get_all_active_whatsapp_numbers():
    """Get all active WhatsApp numbers"""
    return list(whatsapp_numbers.find({"is_active": True}))


# ══════════════════════════════════════════════════════════════
# WABA ID (WhatsApp Business Account ID) FUNCTIONS
# ══════════════════════════════════════════════════════════════

def save_waba_id(phone_number_id: str, waba_id: str):
    """
    Store the WABA ID against this phone_number_id.
    Called from the webhook — Meta sends this as entry['id'] on every payload.
    """
    if not phone_number_id or not waba_id:
        return
    whatsapp_numbers.update_one(
        {"phone_number_id": phone_number_id},
        {"$set": {
            "waba_id": waba_id,
            "waba_id_updated_at": datetime.utcnow()
        }}
    )


def get_waba_id(phone_number_id: str):
    """Fetch the WABA ID for a given phone_number_id."""
    if not phone_number_id:
        return None
    doc = whatsapp_numbers.find_one({"phone_number_id": phone_number_id})
    return doc.get("waba_id") if doc else None


# ══════════════════════════════════════════════════════════════
# NUMBERED TEMPLATE ASSIGNMENT
# (welcome_message_template_0, _1, _2 ... _100, _101, and so on)
# ══════════════════════════════════════════════════════════════

def get_next_template_index() -> int:
    """
    Atomic global counter → returns 0, 1, 2, 3 ... 100, 101, and so on.
    Never repeats, even with concurrent webhooks from different accounts.
    """
    counter = counters.find_one_and_update(
        {"_id": "welcome_template_index"},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )
    return counter["seq"] - 1   # start at 0


def get_template_mapping(phone_number_id: str):
    """Check if THIS account already has a template assigned."""
    if not phone_number_id:
        return None
    return message_templates.find_one({"phone_number_id": phone_number_id})


def save_template_mapping(phone_number_id: str, waba_id: str, template_name: str,
                           status: str, body_text: str):
    """Save which numbered template belongs to this account."""
    message_templates.update_one(
        {"phone_number_id": phone_number_id},
        {"$set": {
            "waba_id": waba_id,
            "template_name": template_name,
            "status": status,
            "body_text": body_text,
            "updated_at": datetime.utcnow()
        }},
        upsert=True
    )


# ══════════════════════════════════════════════════════════════
# USER MANAGEMENT FUNCTIONS
# ══════════════════════════════════════════════════════════════

def get_next_user_id():
    """Generate next user ID starting from 101"""
    last_user = users.find_one(sort=[("user_id", -1)])
    if last_user and last_user.get("user_id"):
        return last_user["user_id"] + 1
    return 101


def get_or_create_user(user_phone, display_phone_number_raw=None, whatsapp_phone_number_id=None):
    """
    Get existing user or create new one with relation to WhatsApp number
    """
    existing_user = users.find_one({"user_phone": user_phone})
    
    if existing_user:
        update_data = {"last_seen": datetime.utcnow()}
        
        if display_phone_number_raw and not existing_user.get("whatsapp_number_id"):
            update_data["whatsapp_number_id"] = whatsapp_phone_number_id
            update_data["display_phone_number_raw"] = display_phone_number_raw
        
        users.update_one({"_id": existing_user["_id"]}, {"$set": update_data})
        return existing_user
    
    new_user_id = get_next_user_id()
    new_user = {
        "user_id": new_user_id,
        "user_phone": user_phone,
        "username": None,
        "whatsapp_number_id": whatsapp_phone_number_id,
        "display_phone_number_raw": display_phone_number_raw,
        "created_at": datetime.utcnow(),
        "last_seen": datetime.utcnow(),
        "total_messages": 0,
        "is_active": True
    }
    users.insert_one(new_user)
    print(f"✅ New user created: ID={new_user_id}, Phone={user_phone}, WhatsApp={display_phone_number_raw}")
    return new_user


def update_username(user_phone, username):
    """Update user's username"""
    users.update_one(
        {"user_phone": user_phone},
        {"$set": {"username": username, "updated_at": datetime.utcnow()}}
    )


def get_user_by_phone(user_phone):
    """Get user by phone number"""
    return users.find_one({"user_phone": user_phone})


def get_user_by_id(user_id):
    """Get user by user_id"""
    return users.find_one({"user_id": user_id})


def increment_user_message_count(user_phone):
    """Increment total message count for user"""
    users.update_one(
        {"user_phone": user_phone},
        {"$inc": {"total_messages": 1}}
    )


def get_users_by_whatsapp_number(display_phone_number_raw):
    """Get all users who chatted with a specific WhatsApp business number"""
    return list(users.find(
        {"display_phone_number_raw": display_phone_number_raw},
        {"_id": 0}
    ).sort("last_seen", -1))