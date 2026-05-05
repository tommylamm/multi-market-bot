"""
多市場多策略交易系統 — 配置文件 v2.3
更新：優化 PAXG 和 SOL 的策略參數，增加信號觸發頻率
更新：緊急審查並優化 OIL 策略，切換為支撐阻力策略
更新：為 PAXG 實施「極高靈敏度」優化方案
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
# 市場配置 v2.3
# 每個市場有：
#   - strategies: 候選策略列表（按優先級排列）
#   - default_strategy: 啟動時使用的策略
#   - strategy: 兼容舊版的字段（= default_strategy）
# 自適應切換：連虧3次或勝率<35%時自動切換到下一個候選策略
# ═══════════════════════════════════════════════════════════════
MARKETS = {
    "BTC": {
        "coin": "BTC",
        "capital_pct": 0.25,
        "leverage": 5,
        "sz_decimals": 5,
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
# 策略參數 v2.3
# 每個策略的參數獨立配置
# v2.1 新增：SOL 和 PAXG 專屬參數（更靈敏的觸發條件）
# v2.2 新增：OIL 專屬參數（適應震盪市）
# v2.3 新增：PAXG 極致靈敏參數
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
    # --- 趨勢跟蹤（無量能確認，適合低流動性市場）---
    "trend_no_vol": {
        "ema_fast": 20,
        "ema_slow": 50,
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
        "atr_period": 14,
        "atr_sl_mult": 1.0,
        "atr_tp_mult": 1.3,
        "trailing_stop_atr": 1.5,
        "volume_confirm": False,
        "min_bars_hold": 3,
        "max_bars_hold": 24,
        "use_maker": True,
    },
    # --- EMA 動量策略（通用版）---
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
    # ═══════════════════════════════════════════════════════════
    # SOL 專屬策略參數 v2.1
    # SOL 特性：高波動、動量強、趨勢明顯
    # ═══════════════════════════════════════════════════════════
    "ema_momentum_sol": {
        "ema_fast": 5,
        "ema_mid": 13,
        "ema_slow": 34,
        "atr_period": 10,
        "atr_sl_mult": 1.0,
        "atr_tp_mult": 1.3,
        "rsi_period": 10,
        "rsi_filter_low": 35,
        "rsi_filter_high": 65,
        "min_bars_hold": 2,
        "max_bars_hold": 25,
        "use_maker": True,
    },
    "breakout_sol": {
        "lookback_period": 12,
        "atr_period": 10,
        "breakout_atr_mult": 0.3,
        "atr_sl_mult": 1.2,
        "atr_tp_mult": 1.3,
        "volume_spike_mult": 0.8,
        "min_bars_hold": 2,
        "max_bars_hold": 30,
        "use_maker": True,
        "session_filter": False,
    },
    "vwap_reversion_sol": {
        "vwap_period": 15,
        "deviation_threshold": 1.2,
        "rsi_period": 10,
        "rsi_oversold": 30,
        "rsi_overbought": 70,
        "atr_period": 10,
        "atr_sl_mult": 1.2,
        "atr_tp_mult": 1.3,
        "min_bars_hold": 1,
        "max_bars_hold": 12,
        "use_maker": True,
        "use_maker": True,
    },
    # ═══════════════════════════════════════════════════════════════
    # PAXG 專屬策略參數 v2.3
    # PAXG 特性：極低波動、均值回歸強、趨勢緩慢
    # 優化方向：極致靈敏的支撐阻力策略
    # ═══════════════════════════════════════════════════════════
    "vwap_reversion_paxg": {
        "vwap_period": 12,
        "deviation_threshold": 0.8,
        "rsi_period": 10,
        "rsi_oversold": 38,
        "rsi_overbought": 62,
        "atr_period": 10,
        "atr_sl_mult": 0.8,
        "atr_tp_mult": 1.5,
        "min_bars_hold": 1,
        "max_bars_hold": 12,
        "use_maker": True,
        "use_maker": True,
    },
    "rsi_pullback_paxg": {
        "ema_trend_period": 30,
        "rsi_period": 10,
        "rsi_pullback_low": 42,
        "rsi_pullback_high": 58,
        "atr_period": 10,
        "atr_sl_mult": 0.8,
        "atr_tp_mult": 1.5,
        "min_bars_hold": 1,
        "max_bars_hold": 15,
        "use_maker": True,
        "use_maker": True,
    },
    "support_resistance_paxg": {
        "lookback_period": 15,      # 極致縮短回看（原 30）→ 捕捉極短線平台
        "proximity_atr": 1.2,       # 極致放寬接近門檻（原 0.8）→ 只要靠近就開倉
        "atr_period": 10,
        "atr_sl_mult": 0.5,        # 更窄止損，適應黃金低波動
        "atr_tp_mult": 1.2,        # 降低止盈目標，確保能獲利了結
        "min_bars_hold": 1,
        "max_bars_hold": 20,
        "use_maker": True,
        "use_maker": True,
    },
    # ═══════════════════════════════════════════════════════════
    # OIL 專屬策略參數 v2.2
    # OIL 特性：當前呈現震盪市特徵，適合支撐阻力策略
    # ═══════════════════════════════════════════════════════════
    "support_resistance_oil": {
        "lookback_period": 40,      # 稍微縮短回看週期，更快適應近期支撐阻力
        "proximity_atr": 0.6,       # 稍微增加接近範圍，提高觸發頻率
        "atr_period": 14,
        "atr_sl_mult": 1.0,        # 稍微放寬止損，避免被隨機波動掃出
        "atr_tp_mult": 1.3,        # 保持良好的風險回報比
        "min_bars_hold": 2,
        "max_bars_hold": 30,
        "use_maker": True,
        "use_maker": True,
    },
    # ═══════════════════════════════════════════════════════════
    # 通用策略參數（保持不變）
    # ═══════════════════════════════════════════════════════════
    "rsi_pullback": {
        "ema_trend_period": 50,
        "rsi_period": 14,
        "rsi_pullback_low": 40,
        "rsi_pullback_high": 60,
        "atr_period": 14,
        "atr_sl_mult": 1.0,
        "atr_tp_mult": 1.3,
        "min_bars_hold": 2,
        "max_bars_hold": 20,
        "use_maker": True,
        "use_maker": True,
    },
    "vwap_reversion": {
        "vwap_period": 20,
        "deviation_threshold": 1.5,
        "rsi_period": 14,
        "rsi_oversold": 35,
        "rsi_overbought": 65,
        "atr_period": 14,
        "atr_sl_mult": 1.0,
        "atr_tp_mult": 1.8,
        "min_bars_hold": 1,
        "max_bars_hold": 15,
        "use_maker": True,
        "use_maker": True,
    },
    "support_resistance": {
        "lookback_period": 50,
        "proximity_atr": 0.5,
        "atr_period": 14,
        "atr_sl_mult": 0.8,
        "atr_tp_mult": 1.8,
        "min_bars_hold": 2,
        "max_bars_hold": 20,
        "use_maker": True,
        "use_maker": True,
    },
    "breakout": {
        "lookback_period": 20,
        "atr_period": 14,
        "breakout_atr_mult": 0.5,
        "atr_sl_mult": 1.0,
        "atr_tp_mult": 3.0,
        "volume_spike_mult": 1.2,
        "min_bars_hold": 2,
        "max_bars_hold": 40,
        "use_maker": True,
        "session_filter": False,
    },
    "mean_reversion": {
        "rsi_period": 14,
        "rsi_oversold": 30,
        "rsi_overbought": 70,
        "bb_period": 20,
        "bb_std": 2.0,
        "atr_period": 14,
        "atr_sl_mult": 1.2,
        "atr_tp_mult": 1.5,
        "min_bars_hold": 1,
        "max_bars_hold": 20,
        "use_maker": True,
        "use_maker": True,
    },
    "bollinger_reversion": {
        "bb_period": 20,
        "bb_std": 2.0,
        "rsi_period": 14,
        "rsi_oversold": 30,
        "rsi_overbought": 70,
        "atr_period": 14,
        "atr_sl_mult": 1.2,
        "atr_tp_mult": 1.5,
        "squeeze_threshold": 0.02,
        "max_bb_width": 0.08,
        "volume_confirm": True,
        "max_bars_hold": 12,
        "tsl_activation_atr": 1.0,
        "tsl_distance_atr": 0.8,
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
