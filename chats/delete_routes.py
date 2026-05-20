# chats/delete_routes.py

from flask import request, jsonify
from database.database import messages, users
import re


def register_delete_routes(app):
    """Register DELETE routes - ONLY APIs used in WordPress dashboard"""

    @app.route('/delete-user-chats-only', methods=['DELETE', 'OPTIONS'])
    def delete_user_chats_only():
        """Delete ALL messages for a user BUT keep the user (clear chat only)"""
        if request.method == 'OPTIONS':
            return '', 200
        
        try:
            data = request.json
            user_phone = data.get('user_phone')
            
            if not user_phone:
                return jsonify({"error": "user_phone is required"}), 400
            
            # Clean phone number
            clean_phone = re.sub(r'[^\d]', '', user_phone)
            if len(clean_phone) == 10:
                clean_phone = '91' + clean_phone
            
            result = messages.delete_many({"user_phone": clean_phone})
            
            # Reset message count for user
            users.update_one(
                {"user_phone": clean_phone},
                {"$set": {"total_messages": 0}}
            )
            
            return jsonify({
                "success": True,
                "deleted_count": result.deleted_count,
                "message": f"Cleared {result.deleted_count} messages. User remains in system."
            }), 200
            
        except Exception as e:
            print(f"Error clearing user chats: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/delete-user-completely', methods=['DELETE', 'OPTIONS'])
    def delete_user_completely():
        """Delete user completely: ALL messages AND remove from users collection"""
        if request.method == 'OPTIONS':
            return '', 200
        
        try:
            data = request.json
            user_phone = data.get('user_phone')
            
            if not user_phone:
                return jsonify({"error": "user_phone is required"}), 400
            
            # Clean phone number
            clean_phone = re.sub(r'[^\d]', '', user_phone)
            if len(clean_phone) == 10:
                clean_phone = '91' + clean_phone
            
            # Delete all messages
            messages_result = messages.delete_many({"user_phone": clean_phone})
            
            # Delete user from users collection
            users_result = users.delete_one({"user_phone": clean_phone})
            
            return jsonify({
                "success": True,
                "messages_deleted": messages_result.deleted_count,
                "user_deleted": users_result.deleted_count > 0,
                "message": f"User deleted completely with {messages_result.deleted_count} messages"
            }), 200
            
        except Exception as e:
            print(f"Error deleting user completely: {e}")
            return jsonify({"error": str(e)}), 500