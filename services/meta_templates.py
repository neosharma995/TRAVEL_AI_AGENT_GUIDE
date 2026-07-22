# services/meta_templates.py

import os
import requests
import logging

logger = logging.getLogger(__name__)
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
GRAPH_VERSION = "v18.0"

TEMPLATE_LANGUAGE = "en_US"

DEFAULT_BODY = (
    "Welcome to {{1}},\n\n"
    "I'm your personal travel assistant from {{2}}\n\n"
    "How can I help you today?"
)

# 🔥 default example values shown to Meta reviewers only
DEFAULT_EXAMPLE_1 = "himmanav"
DEFAULT_EXAMPLE_2 = "himmanav travel agent"


def list_templates(waba_id: str, name_filter: str = None):
    """List all templates registered under a WABA."""
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{waba_id}/message_templates"
    params = {"limit": 100}
    if name_filter:
        params["name"] = name_filter
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    try:
        res = requests.get(url, headers=headers, params=params, timeout=10)
        res.raise_for_status()
        return res.json().get("data", [])
    except Exception as e:
        logger.error(f"❌ list_templates error: {e}")
        return []


def get_welcome_template(waba_id: str, template_name: str):
    """Return this exact numbered template from Meta if it exists (any status)."""
    for t in list_templates(waba_id, name_filter=template_name):
        if t.get("name") == template_name and t.get("language") == TEMPLATE_LANGUAGE:
            return t
    return None


def create_welcome_template(waba_id: str, template_name: str):
    """
    Submit a uniquely-named welcome template (e.g. welcome_message_template_5).
    NOTE: returns PENDING immediately — approval is async (minutes to ~48h).
    Do not block the webhook/response waiting for approval.
    """
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{waba_id}/message_templates"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "name": template_name,
        "language": TEMPLATE_LANGUAGE,
        "category": "UTILITY",
        "components": [
            {
                "type": "BODY",
                "text": DEFAULT_BODY,
                "example": {"body_text": [[DEFAULT_EXAMPLE_1, DEFAULT_EXAMPLE_2]]},
            }
        ],
    }
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=15)
        if res.status_code in (200, 201):
            logger.info(f"✅ Template '{template_name}' submitted for review: {res.json()}")
            return res.json()
        logger.error(f"❌ create_welcome_template('{template_name}') failed: {res.status_code} {res.text}")
        return None
    except Exception as e:
        logger.error(f"❌ create_welcome_template error: {e}")
        return None