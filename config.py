"""
多市場多策略交易系統 — 配置文件 v2.4
"""
import os
# ═══════════════════════════════════════════════════════════════
# Hyperliquid 帳戶設定
# ═══════════════════════════════════════════════════════════════
HL_SECRET = os.environ.get("HL_SECRET", "").strip()
HL_ACCOUNT = os.environ.get("HL_ACCOUNT", "").strip()
HL_API_URL = "https://api.hyperliquid.xyz"
# ═══════════════════════════════════════════════════════════════
# 總資金與風控
# ═══════════════════════════════════════════════════════════════
TOTAL_CAPITAL = 425.0
DAILY_LOSS_LIMIT_PCT = 0.15
DAILY_LOSS_LIMIT = TOTAL_CAPITAL * DAILY_LOSS_LIMIT_PCT
RISK_FREE_MARGIN_PCT = 0.10
MAX_CONSECUTIVE_LOSSES = 5
CIRCUIT_BREAKER_COOLDOWN = 3600
# ═══════════════════════════════════════════════════════════════
# 市場配置 v2.4
# ═══════════════════════════════════════════════════════════════
MARKETS = {
    "ETH": {
        "coin": "ETH",
        "capital_pct": 0.25,
        "leverage": 5,
        "sz_decimals": 4,
        "timeframe": "1h",
        "max_positions": 1,
        "strategy": "trend",
        "default_strategy": "trend",
        "strategies": ["brooks_trend", "anti_market_bb", "sperandeo_reversal", "trend", "ema_momentum"],
    },
    "DOGE": {
        "coin": "DOGE",
        "capital_pct": 0.15,
        "leverage": 5,
        "sz_decimals": 0,
        "timeframe": "1h",
        "max_positions": 1,
        "strategy": "ema_momentum",
        "default_strategy": "ema_momentum",
        "strategies": ["brooks_trend", "anti_market_bb", "sperandeo_reversal", "trend", "ema_momentum"],
    },
    "ZEC": {
        "coin": "ZEC",
        "capital_pct": 0.15,
        "leverage": 5,
        "sz_decimals": 2,
        "timeframe": "1h",
        "max_positions": 1,
        "strategy": "ema_momentum",
        "default_strategy": "ema_momentum",
        "strategies": ["brooks_trend", "anti_market_bb", "sperandeo_reversal", "trend", "ema_momentum"],
    },
}
# ═══════════════════════════════════════════════════════════════
# 策略參數 v2.4
# ═══════════════════════════════════════════════════════════════
STRATEGY_PARAMS = {
    # --- 趨勢跟蹤（EMA交叉+MACD+量能）---
    "trend": {
        "ema_fast": 20,
        "ema_slow": 50,
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
        "atr_period": 14,
        "atr_sl_mult": 1.0,
        "atr_tp_mult": 1.3,
        "trailing_stop_atr": 1.5,
        "volume_confirm": True,
        "min_bars_hold": 3,
        "max_bars_hold": 24,
        "use_maker": True,
    },
    # --- EMA 動量策略 ---
    "ema_momentum": {
        "ema_fast": 8,
        "ema_mid": 21,
        "ema_slow": 55,
        "atr_period": 14,
        "atr_sl_mult": 1.0,
        "atr_tp_mult": 1.3,
        "trailing_stop_atr": 1.2,
        "rsi_period": 14,
        "rsi_filter_low": 35,
        "rsi_filter_high": 65,
        "min_bars_hold": 2,
        "max_bars_hold": 18,
        "use_maker": True,
    },
}
# ═══════════════════════════════════════════════════════════════
# 手續費
# ═══════════════════════════════════════════════════════════════
MAKER_FEE = 0.00010   # 0.010%
TAKER_FEE = 0.00035   # 0.035%
# ═══════════════════════════════════════════════════════════════
# 日誌
# ═══════════════════════════════════════════════════════════════
LOG_DIR = "logs"
TRADE_LOG = os.path.join(LOG_DIR, "trades.jsonl")
SYSTEM_LOG = os.path.join(LOG_DIR, "system.log")
# ═══════════════════════════════════════════════════════════════
# 數據
# ═══════════════════════════════════════════════════════════════
DATA_DIR = "data"
CANDLE_BUFFER_SIZE = 500
