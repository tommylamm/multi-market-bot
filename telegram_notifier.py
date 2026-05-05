"""
Telegram notification helper.
Safely no-ops when credentials are missing.
"""

import os
import time
from datetime import datetime, timezone
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


# ---------------------------------------------------------------------------
# Structured notification helpers — only send useful, non-spammy messages
# ---------------------------------------------------------------------------

def _fmt_direction(d: str) -> str:
    return "LONG" if d == "long" else "SHORT"


def notify_trade_open(market: str, direction: str, price: float, size: float,
                      strategy: str = "", reason: str = ""):
    """A new position was opened."""
    d = _fmt_direction(direction)
    msg = f"🟢 OPEN {d}\n{market} @ {price:.2f} x {size}"
    if strategy:
        msg += f"\nStrategy: {strategy}"
    if reason:
        msg += f"\nReason: {reason}"
    send_telegram(msg)


def notify_trade_close(market: str, direction: str, price: float,
                       pnl: float, reason: str = ""):
    """A position was closed."""
    d = _fmt_direction(direction)
    emoji = "🟢" if pnl > 0 else "🔴"
    msg = f"{emoji} CLOSE {d}\n{market} @ {price:.2f}\nPnL: ${pnl:+.2f}"
    if reason:
        msg += f"\nReason: {reason}"
    send_telegram(msg)


def notify_emergency_close(market: str, direction: str, price: float,
                           pnl: float, reason: str):
    """Stop-loss / take-profit / emergency stop triggered."""
    d = _fmt_direction(direction)
    msg = (f"🚨 EMERGENCY CLOSE\n{market} {d} @ {price:.2f}\n"
           f"PnL: ${pnl:+.2f}\n{reason}")
    send_telegram(msg)


def notify_circuit_breaker(action: str, daily_pnl: float, limit: float):
    """Daily loss circuit breaker triggered or released."""
    if action == "triggered":
        msg = (f"⚠️ CIRCUIT BREAKER\nDaily loss ${daily_pnl:+.2f} "
               f"exceeds limit ${limit:.2f}\nTrading halted for 1 hour")
    else:
        msg = "✅ CIRCUIT BREAKER RELEASED\nTrading resumed"
    send_telegram(msg)


def notify_market_paused(market: str, consecutive_losses: int, minutes: int):
    """A market was paused due to consecutive losses."""
    msg = (f"⏸️ MARKET PAUSED\n{market}\n"
           f"{consecutive_losses} consecutive losses\n"
           f"Paused for {minutes} minutes")
    send_telegram(msg)


def notify_system_start(markets: str, total_capital: float, live: bool):
    """System started."""
    mode = "LIVE" if live else "SIMULATION"
    msg = (f"🚀 SYSTEM STARTED\nMode: {mode}\n"
           f"Capital: ${total_capital:.0f}\nMarkets: {markets}")
    send_telegram(msg)


def notify_system_shutdown(total_pnl: float, daily_pnl: float,
                           balance: float, total_trades: int, uptime_h: float):
    """System shutting down."""
    msg = (f"🛑 SYSTEM SHUTDOWN\n"
           f"Uptime: {uptime_h:.1f}h | Trades: {total_trades}\n"
           f"Total PnL: ${total_pnl:+.2f}\n"
           f"Daily PnL: ${daily_pnl:+.2f}\n"
           f"Balance: ${balance:.2f}")
    send_telegram(msg)


def notify_periodic_status(total_pnl: float, daily_pnl: float,
                           balance: float, active_positions: str,
                           uptime_h: float):
    """Periodic status update (every few hours)."""
    msg = (f"📊 STATUS @ {uptime_h:.1f}h\n"
           f"PnL: ${total_pnl:+.2f} (today ${daily_pnl:+.2f})\n"
           f"Balance: ${balance:.2f}")
    if active_positions:
        msg += f"\nPositions: {active_positions}"
    send_telegram(msg)
