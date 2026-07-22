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


def find_any_welcome_template(waba_id: str):
    """
    Scan ALL templates on Meta for this WABA and return the first REAL custom
    template found — explicitly skipping 'hello_world' which is Meta's default
    template that exists in every single WhatsApp Business account and is NOT
    a usable welcome template for this chatbot.

    Returns the template dict if a real custom template is found, or None if
    the WABA has no custom templates yet (only hello_world or nothing).
    """
    # Names to always skip — Meta defaults that exist in every account
    SKIP_TEMPLATES = {"hello_world"}

    try:
        all_templates = list_templates(waba_id)
        for t in all_templates:
            name = t.get("name", "")
            if name in SKIP_TEMPLATES:
                logger.info(f"⏭️  Skipping default Meta template '{name}' — not a custom template")
                continue
            # Found a real custom template — reuse it
            logger.info(
                f"✅ Existing custom template found — reusing '{name}' "
                f"(status={t.get('status')}, category={t.get('category')}) "
                f"for WABA {waba_id}"
            )
            return t
        logger.info(f"ℹ️  No custom template found on Meta for WABA {waba_id} (only defaults). Will create new.")
    except Exception as e:
        logger.error(f"❌ find_any_welcome_template error: {e}")
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
        "category": "MARKETING",
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