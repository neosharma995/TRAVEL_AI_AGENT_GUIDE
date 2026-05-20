# database/database.py

from pymongo import MongoClient
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
            "is_active": True,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "last_webhook_received": datetime.utcnow()
        }
        if metadata:
            new_record.update(metadata)
        
        whatsapp_numbers.insert_one(new_record)
        return new_record, True


def get_whatsapp_config(phone_number_id):
    """Get WhatsApp configuration from database"""
    config = whatsapp_numbers.find_one({
        "phone_number_id": phone_number_id,
        "is_active": True
    })
    
    if not config:
        return None
    
    return {
        "phone_number_id": config.get("phone_number_id"),
        "display_number": config.get("display_number") or config.get("display_phone_number_raw"),
        "display_phone_number_raw": config.get("display_phone_number_raw"),
        "verified_name": config.get("verified_name"),
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
        # Update last_seen
        update_data = {"last_seen": datetime.utcnow()}
        
        # Update whatsapp_number_id if not set
        if display_phone_number_raw and not existing_user.get("whatsapp_number_id"):
            update_data["whatsapp_number_id"] = whatsapp_phone_number_id
            update_data["display_phone_number_raw"] = display_phone_number_raw
        
        users.update_one({"_id": existing_user["_id"]}, {"$set": update_data})
        return existing_user
    
    # Create new user with relation to WhatsApp number
    new_user_id = get_next_user_id()
    new_user = {
        "user_id": new_user_id,
        "user_phone": user_phone,
        "username": None,
        "whatsapp_number_id": whatsapp_phone_number_id,  # 🔥 Which WhatsApp number they chatted with
        "display_phone_number_raw": display_phone_number_raw,  # 🔥 The business number
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

def get_next_user_id():
    """Generate next user ID starting from 101"""
    last_user = users.find_one(sort=[("user_id", -1)])
    if last_user and last_user.get("user_id"):
        return last_user["user_id"] + 1
    return 101