"""策略模組 v2.2 — 新增 Bollinger Band 均值回歸策略"""
from strategies.base import BaseStrategy, Indicators
from strategies.trend_following import TrendFollowingStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.breakout import BreakoutStrategy
from strategies.rsi_pullback import RSIPullbackStrategy
from strategies.vwap_reversion import VWAPReversionStrategy
from strategies.ema_momentum import EMAMomentumStrategy
from strategies.support_resistance import SupportResistanceStrategy
from strategies.anti_market_bb import AntiMarketBBStrategy
from strategies.sperandeo_reversal import SperandeoReversalStrategy
from strategies.brooks_trend import BrooksTrendStrategy
from strategies.bollinger_reversion import BollingerReversionStrategy

STRATEGY_MAP = {
    # === 通用策略 ===
    "trend": TrendFollowingStrategy,
    "trend_no_vol": TrendFollowingStrategy,
    "mean_reversion": MeanReversionStrategy,
    "breakout": BreakoutStrategy,
    "rsi_pullback": RSIPullbackStrategy,
    "vwap_reversion": VWAPReversionStrategy,
    "ema_momentum": EMAMomentumStrategy,
    "support_resistance": SupportResistanceStrategy,
    "anti_market_bb": AntiMarketBBStrategy,
    "sperandeo_reversal": SperandeoReversalStrategy,
    "brooks_trend": BrooksTrendStrategy,
    "bollinger_reversion": BollingerReversionStrategy,
    # === SOL 專屬策略 ===
    "ema_momentum_sol": EMAMomentumStrategy,
    "breakout_sol": BreakoutStrategy,
    "vwap_reversion_sol": VWAPReversionStrategy,
    # === PAXG 專屬策略 ===
    "vwap_reversion_paxg": VWAPReversionStrategy,
    "rsi_pullback_paxg": RSIPullbackStrategy,
    "support_resistance_paxg": SupportResistanceStrategy,
    # === OIL 專屬策略 ===
    "support_resistance_oil": SupportResistanceStrategy,
}
