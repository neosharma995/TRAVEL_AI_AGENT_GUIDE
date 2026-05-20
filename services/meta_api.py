# services/meta_api.py

import requests
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def get_whatsapp_number_metadata(phone_number_id, access_token):
    """
    Fetch phone number metadata from Meta API
    Returns: dict with phone number details
    """
    try:
        url = f"https://graph.facebook.com/v18.0/{phone_number_id}"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        # Get basic phone number info
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            # Get quality rating
            quality_url = f"https://graph.facebook.com/v18.0/{phone_number_id}/quality"
            quality_resp = requests.get(quality_url, headers=headers, timeout=10)
            
            quality_data = quality_resp.json() if quality_resp.status_code == 200 else {}
            
            metadata = {
                "display_phone_number": data.get("display_phone_number"),
                "verified_name": data.get("verified_name"),
                "status": data.get("status", "active"),
                "quality_rating": quality_data.get("quality_rating", "unknown"),
                "last_fetched": datetime.utcnow()
            }
            
            logger.info(f"✅ Fetched metadata for {phone_number_id}: {metadata['display_phone_number']}")
            return metadata
        else:
            logger.error(f"❌ Failed to fetch metadata for {phone_number_id}: {response.status_code}")
            return None
            
    except Exception as e:
        logger.error(f"❌ Error fetching metadata: {e}")
        return None