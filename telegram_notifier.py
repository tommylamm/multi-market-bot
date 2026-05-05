"""
Telegram notification helper.
Safely no-ops when credentials are missing.
"""

import os
from typing import Optional

import requests

TELEGRAM_API_BASE = "https://api.telegram.org"
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()


def _enabled() -> bool:
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


def send_telegram(message: str, timeout: int = 10) -> bool:
    """Send a Telegram message. Returns True on success, False otherwise."""
    if not message or not _enabled():
        return False

    url = f"{TELEGRAM_API_BASE}/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        return resp.status_code == 200
    except Exception:
        return False
