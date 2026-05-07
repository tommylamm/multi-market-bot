"""
多時間框架 (MTF) 確認過濾器
從 1h K線合成 4h K線，判斷大級別趨勢方向，過濾逆勢信號
"""
import numpy as np
from strategies.base import Indicators


class MTFFilter:
    """多時間框架趨勢過濾器"""

    def __init__(self, ema_fast: int = 20, ema_slow: int = 50):
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow

    def synthesize_4h_from_1h(self, closes_1h, highs_1h, lows_1h, volumes_1h):
        """從 1h K線合成 4h K線"""
        n = len(closes_1h)
        remainder = n % 4
        if remainder > 0:
            closes_1h = closes_1h[remainder:]
            highs_1h = highs_1h[remainder:]
            lows_1h = lows_1h[remainder:]
            volumes_1h = volumes_1h[remainder:]
        n = len(closes_1h)
        n_4h = n // 4
        if n_4h < 2:
            return np.array([]), np.array([]), np.array([]), np.array([])
        closes_4h = np.zeros(n_4h)
        highs_4h = np.zeros(n_4h)
        lows_4h = np.zeros(n_4h)
        volumes_4h = np.zeros(n_4h)
        for i in range(n_4h):
            start = i * 4
            end = start + 4
            closes_4h[i] = closes_1h[end - 1]
            highs_4h[i] = np.max(highs_1h[start:end])
            lows_4h[i] = np.min(lows_1h[start:end])
            volumes_4h[i] = np.sum(volumes_1h[start:end])
        return closes_4h, highs_4h, lows_4h, volumes_4h

    def get_higher_tf_trend(self, closes_1h, highs_1h, lows_1h, volumes_1h):
        """獲取 4h 趨勢方向"""
        closes_4h, highs_4h, lows_4h, volumes_4h = self.synthesize_4h_from_1h(
            closes_1h, highs_1h, lows_1h, volumes_1h
        )
        min_required = max(self.ema_fast, self.ema_slow) + 5
        if len(closes_4h) < min_required:
            return None, 0.0, "4h數據不足"
        ema_fast = Indicators.ema(closes_4h, self.ema_fast)
        ema_slow = Indicators.ema(closes_4h, self.ema_slow)
        macd_line, signal_line, histogram = Indicators.macd(closes_4h)
        current_ema_fast = ema_fast[-1]
        current_ema_slow = ema_slow[-1]
        current_histogram = histogram[-1]
        current_close = closes_4h[-1]
        if any(np.isnan(x) for x in [current_ema_fast, current_ema_slow, current_histogram]):
            return None, 0.0, "指標計算中"
        ema_bullish = current_ema_fast > current_ema_slow
        macd_bullish = current_histogram > 0
        price_above_slow = current_close > current_ema_slow
        ema_diff_pct = abs(current_ema_fast - current_ema_slow) / current_ema_slow if current_ema_slow > 0 else 0
        bull_score = sum([ema_bullish, macd_bullish, price_above_slow])
        bear_score = sum([not ema_bullish, not macd_bullish, not price_above_slow])
        if bull_score >= 2:
            strength = min(1.0, ema_diff_pct * 100 + 0.3 * bull_score)
            return "long", strength, "4h多頭"
        elif bear_score >= 2:
            strength = min(1.0, ema_diff_pct * 100 + 0.3 * bear_score)
            return "short", strength, "4h空頭"
        else:
            return None, 0.0, "4h震盪"

    def should_allow_signal(self, signal_direction, closes_1h, highs_1h, lows_1h, volumes_1h, strategy_type="trend"):
        """判斷信號是否與 4h 趨勢一致"""
        if signal_direction is None:
            return True, "無信號"
        if strategy_type in ("bollinger_reversion", "mean_reversion", "vwap_reversion"):
            return True, "MTF跳過(均值回歸)"
        trend_dir, trend_strength, trend_reason = self.get_higher_tf_trend(
            closes_1h, highs_1h, lows_1h, volumes_1h
        )
        if trend_dir is None:
            return True, f"MTF通過(4h無趨勢)"
        if signal_direction == trend_dir:
            return True, f"MTF通過({signal_direction}與{trend_reason}一致)"
        return False, f"MTF阻止({signal_direction}與{trend_reason}衝突)"
