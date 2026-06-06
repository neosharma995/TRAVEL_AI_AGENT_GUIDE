 
# plan_checker.py  

import requests
import logging
import os
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

_BLOCK_ON_HTTP = {404, 403}


def _get_config() -> tuple[str, str]:
    """
    Reads .env fresh on every call.
    WP_API_BASE can be ANY of these — all produce the correct URL:
      https://site.com
      https://site.com/wp-json
      https://site.com/wp-json/hm/v1       
      https://site.com/wp-json/hm/v1/
    Returns (clean_domain, bot_secret)
    """
    load_dotenv('.env', override=True)

    raw    = os.getenv("WP_API_BASE", "").strip().strip('"').rstrip("/")
    secret = os.getenv("BOT_SECRET_KEY", "")

 
    for suffix in ["/wp-json/hm/v1", "/wp-json/hm", "/wp-json", "/hm/v1", "/hm"]:
        if raw.endswith(suffix):
            raw = raw[: -len(suffix)]
            break

    domain = raw.rstrip("/")
    return domain, secret


def is_bot_allowed(phone: str) -> tuple[bool, str]:
    """
    Hits WP REST API fresh on EVERY call — no cache, no stale data.
    Returns (True,  'active')       → bot may run
    Returns (False, reason_string)  → block bot, send sorry message
    """
    wp_base, secret = _get_config()

    if not wp_base:
        logger.error("[PlanChecker] WP_API_BASE not set in .env — BLOCKING")
        return False, "config_error"

    url     = f"{wp_base}/wp-json/hm/v1/bot-status"
    headers = {"X-Bot-Secret": secret} if secret else {}

    print(f"[PlanChecker] Calling → {url}?phone={phone}")

    try:
        resp = requests.get(url, params={"phone": phone}, headers=headers, timeout=5)
        print(f"[PlanChecker] HTTP {resp.status_code}: {resp.text[:200]}")

        if resp.status_code == 200:
            data       = resp.json()
            bot_active = bool(data.get("bot_active", False))
            reason     = data.get("reason", "unknown")
            logger.info(f"[PlanChecker] {phone} → active={bot_active}, reason={reason}")
            return bot_active, reason

        if resp.status_code in _BLOCK_ON_HTTP:
            logger.warning(f"[PlanChecker] {phone} → HTTP {resp.status_code} → BLOCKED")
            return False, f"http_{resp.status_code}"

        if resp.status_code >= 500:
            logger.warning(f"[PlanChecker] WP server error {resp.status_code} → fail-open")
            return True, "wp_server_error_fail_open"

        logger.warning(f"[PlanChecker] Unexpected HTTP {resp.status_code} → BLOCKED")
        return False, f"unexpected_http_{resp.status_code}"

    except requests.exceptions.Timeout:
        logger.warning(f"[PlanChecker] Timeout → fail-open")
        return True, "timeout_fail_open"

    except Exception as e:
        logger.error(f"[PlanChecker] Exception: {e}")
        return True, "exception_fail_open"


def invalidate_cache(phone: str) -> None:
    """No-op — caching disabled. Kept so imports don't break."""
    pass


def get_expired_response(reason: str = "", business_phone: str = "") -> dict:
    wp_base, _ = _get_config()
    contact_line = ""
    if business_phone:
        digits = business_phone.lstrip("+").strip()
        if len(digits) == 12 and digits.startswith("91"):
            formatted = "+{} {} {}".format(digits[:2], digits[2:7], digits[7:])
        else:
            formatted = "+{}".format(digits)
        contact_line = "\n📞 *Call us:* {}\n".format(formatted)

    body = (
       
        "🙏 *We Apologize for the Inconvenience*\n"
        "Our automated assistant is temporarily unavailable.\n"
        "✅ A member of our support team will connect with you\n"
        "shortly and assist you personally.\n"
        + contact_line +
        "Thank you for your patience. We look forward to helping you! 🙏"
    )

    return {"type": "text", "content": body}