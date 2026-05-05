"""策略模組"""
from strategies.base import BaseStrategy, Indicators
from strategies.trend_following import TrendFollowingStrategy
from strategies.ema_momentum import EMAMomentumStrategy
from strategies.anti_market_bb import AntiMarketBBStrategy
from strategies.sperandeo_reversal import SperandeoReversalStrategy
from strategies.brooks_trend import BrooksTrendStrategy

STRATEGY_MAP = {
    "trend":                    TrendFollowingStrategy,
    "ema_momentum":             EMAMomentumStrategy,
    "anti_market_bb":           AntiMarketBBStrategy,
    "sperandeo_reversal":       SperandeoReversalStrategy,
    "brooks_trend":             BrooksTrendStrategy,
}
