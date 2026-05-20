# chats/routes.py

from flask import request, jsonify
from datetime import datetime
from database.database import messages, users, get_whatsapp_config, get_all_active_whatsapp_numbers, whatsapp_numbers, get_next_user_id
from chats.whatsapp_sender import send_whatsapp_message
import re


def normalize_phone_number(phone_number):
    """Normalize phone number for consistent matching"""
    if not phone_number:
        return None
    normalized = re.sub(r'[^\d]', '', str(phone_number))
    if normalized.startswith('0'):
        normalized = normalized[1:]
    return normalized


def register_chat_routes(app):
    """Register all chat-related routes - ONLY APIs used in WordPress dashboard"""

    @app.route('/get-users-by-whatsapp-number', methods=['GET', 'OPTIONS'])
    def get_users_by_whatsapp_number():
        """Get all users for a specific WhatsApp business number"""
        if request.method == 'OPTIONS':
            return '', 200
        
        display_phone_number = request.args.get("display_phone_number")
        
        if not display_phone_number:
            return jsonify({"error": "display_phone_number is required"}), 400
        
        try:
            normalized = normalize_phone_number(display_phone_number)
            
            users_list = list(users.find(
                {"display_phone_number_raw": normalized},
                {"_id": 0}
            ).sort("last_seen", -1))
            
            result = []
            for user in users_list:
                user_messages = list(messages.find({
                    "user_phone": user["user_phone"],
                    "display_phone_number_raw": normalized
                }).sort("timestamp", 1))
                
                last_msg = user_messages[-1] if user_messages else None
                
                result.append({
                    "user_id": user["user_id"],
                    "user_phone": user["user_phone"],
                    "username": user.get("username"),
                    "total_messages": len(user_messages),
                    "created_at": user.get("created_at"),
                    "last_seen": user.get("last_seen"),
                    "last_message": str(last_msg.get("message", ""))[:100] if last_msg else None,
                    "last_message_time": last_msg.get("timestamp") if last_msg else None
                })
            
            return jsonify({
                "success": True,
                "display_phone_number": display_phone_number,
                "total_users": len(result),
                "users": result
            }), 200
            
        except Exception as e:
            print(f"Error in get_users_by_whatsapp_number: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/get-chats', methods=['GET', 'OPTIONS'])
    def get_chats():
        """Get chat history for a user"""
        if request.method == 'OPTIONS':
            return '', 200
            
        user_phone = request.args.get("user_phone")
        display_phone_number = request.args.get("display_phone_number")

        if not user_phone:
            return jsonify({"error": "user_phone is required"}), 400

        query = {"user_phone": user_phone}
        if display_phone_number:
            normalized = normalize_phone_number(display_phone_number)
            query["display_phone_number_raw"] = normalized
        
        chats = list(messages.find(query).sort("timestamp", 1))

        for c in chats:
            c["_id"] = str(c["_id"])

        return jsonify({
            "success": True,
            "chats": chats,
            "count": len(chats)
        })

    @app.route('/send-message', methods=['POST', 'OPTIONS'])
    def send_message():
        """Send message from partner to user"""
        if request.method == 'OPTIONS':
            return '', 200
            
        data = request.json
        user_phone = data.get("user_phone")
        message = data.get("message")
        display_phone_number = data.get("display_phone_number")
        
        if not user_phone:
            return jsonify({"error": "user_phone is required"}), 400
        
        if not message:
            return jsonify({"error": "message is required"}), 400
        
        user = users.find_one({"user_phone": user_phone})
        if not user:
            return jsonify({"error": f"User {user_phone} not found"}), 404
        
        actual_user_id = user["user_id"]
        
        sender_phone_number_id = None
        if display_phone_number:
            normalized = normalize_phone_number(display_phone_number)
            wa_config = whatsapp_numbers.find_one({
                "$or": [
                    {"display_phone_number_raw": normalized},
                    {"display_number": normalized}
                ]
            })
            if wa_config:
                sender_phone_number_id = wa_config["phone_number_id"]
                display_phone_number = wa_config.get("display_phone_number_raw") or wa_config.get("display_number")
        
        if not sender_phone_number_id:
            active_numbers = get_all_active_whatsapp_numbers()
            if active_numbers:
                sender_phone_number_id = active_numbers[0]["phone_number_id"]
                display_phone_number = active_numbers[0].get("display_phone_number_raw") or active_numbers[0].get("display_number")
            else:
                return jsonify({"error": "No active WhatsApp number found"}), 500
        
        messages.insert_one({
            "user_phone": user_phone,
            "user_id": actual_user_id,
            "message": message,
            "from": "partner",
            "timestamp": datetime.utcnow(),
            "display_phone_number_raw": display_phone_number,
            "sender_phone_number_id": sender_phone_number_id
        })
        
        from chats.whatsapp_sender import send_whatsapp_message
        result = send_whatsapp_message(user_phone, {
            "type": "text",
            "content": message
        }, sender_phone_number_id)
        
        if result:
            return jsonify({"status": "sent", "success": True})
        else:
            return jsonify({"status": "failed", "success": False}), 500

    @app.route('/create-user-if-not-exists', methods=['POST', 'OPTIONS'])
    def create_user_if_not_exists():
        """Create user ONLY if not exists for THIS SPECIFIC business number"""
        if request.method == 'OPTIONS':
            return '', 200
        
        try:
            data = request.json
            user_phone = data.get('user_phone')
            username = data.get('username')
            display_phone_number = data.get('display_phone_number')
            
            if not user_phone:
                return jsonify({"error": "user_phone is required"}), 400
            
            if not display_phone_number:
                return jsonify({"error": "display_phone_number is required"}), 400
            
            clean_phone = re.sub(r'[^\d]', '', user_phone)
            if len(clean_phone) == 10:
                clean_phone = '91' + clean_phone
            elif len(clean_phone) == 12 and clean_phone.startswith('91'):
                clean_phone = clean_phone
            else:
                clean_phone = '91' + clean_phone[-10:] if len(clean_phone) >= 10 else clean_phone
            
            normalized_display = normalize_phone_number(display_phone_number)
            
            existing_user = users.find_one({
                "user_phone": clean_phone,
                "display_phone_number_raw": normalized_display
            })
            
            if existing_user:
                existing_user.pop('_id', None)
                return jsonify({
                    "success": True,
                    "user": existing_user,
                    "is_new": False,
                    "message": "User already exists for this WhatsApp business number"
                }), 200
            
            new_user_id = get_next_user_id()
            new_user = {
                "user_id": new_user_id,
                "user_phone": clean_phone,
                "username": username,
                "whatsapp_number_id": None,
                "display_phone_number_raw": normalized_display,
                "created_at": datetime.utcnow(),
                "last_seen": datetime.utcnow(),
                "total_messages": 0,
                "is_active": True
            }
            users.insert_one(new_user)
            
            new_user.pop('_id', None)
            
            return jsonify({
                "success": True,
                "user": new_user,
                "is_new": True,
                "message": f"User {clean_phone} created for {normalized_display}"
            }), 200
            
        except Exception as e:
            print(f"Error in create_user_if_not_exists: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/validate-whatsapp-number', methods=['GET', 'OPTIONS'])
    def validate_whatsapp_number():
        """Validate if a WhatsApp business number is registered and active"""
        if request.method == 'OPTIONS':
            return '', 200
        
        display_phone_number = request.args.get("display_phone_number")
        
        if not display_phone_number:
            return jsonify({"error": "display_phone_number is required"}), 400
        
        try:
            normalized = normalize_phone_number(display_phone_number)
            
            whatsapp_config = whatsapp_numbers.find_one({
                "$or": [
                    {"display_phone_number_raw": normalized},
                    {"display_number": normalized}
                ]
            })
            
            if not whatsapp_config:
                return jsonify({
                    "success": False,
                    "valid": False,
                    "message": f"WhatsApp number {display_phone_number} is not registered in the system"
                }), 200
            
            if not whatsapp_config.get('is_active', False):
                return jsonify({
                    "success": False,
                    "valid": False,
                    "message": f"WhatsApp number {display_phone_number} is inactive"
                }), 200
            
            return jsonify({
                "success": True,
                "valid": True,
                "message": f"WhatsApp number {display_phone_number} is valid and active"
            }), 200
            
        except Exception as e:
            print(f"Error in validate_whatsapp_number: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/update-username', methods=['PATCH', 'OPTIONS'])
    def update_username():
        """Update username for a user"""
        if request.method == 'OPTIONS':
            response = jsonify({'success': True})
            response.headers.add('Access-Control-Allow-Origin', '*')
            response.headers.add('Access-Control-Allow-Headers', 'Content-Type, Authorization, ngrok-skip-browser-warning')
            response.headers.add('Access-Control-Allow-Methods', 'PATCH, OPTIONS')
            return response, 200
        
        try:
            data = request.json
            user_phone = data.get('user_phone')
            username = data.get('username')
            display_phone_number = data.get('display_phone_number')
            
            if not user_phone:
                return jsonify({"error": "user_phone is required"}), 400
            
            if not username:
                return jsonify({"error": "username is required"}), 400
            
            if not display_phone_number:
                return jsonify({"error": "display_phone_number is required"}), 400
            
            clean_phone = re.sub(r'[^\d]', '', user_phone)
            if len(clean_phone) == 10:
                clean_phone = '91' + clean_phone
            
            normalized_display = normalize_phone_number(display_phone_number)
            
            user = users.find_one({
                "user_phone": clean_phone,
                "display_phone_number_raw": normalized_display
            })
            
            if not user:
                return jsonify({"error": "User not found for this WhatsApp business number"}), 404
            
            result = users.update_one(
                {"_id": user["_id"]},
                {"$set": {
                    "username": username,
                    "updated_at": datetime.utcnow()
                }}
            )
            
            if result.modified_count > 0:
                return jsonify({
                    "success": True,
                    "message": "Username updated successfully",
                    "user_phone": clean_phone,
                    "username": username
                }), 200
            else:
                return jsonify({
                    "success": True,
                    "message": "Username unchanged (same value)",
                    "user_phone": clean_phone,
                    "username": username
                }), 200
            
        except Exception as e:
            print(f"Error in update_username: {e}")
            return jsonify({"error": str(e)}), 500