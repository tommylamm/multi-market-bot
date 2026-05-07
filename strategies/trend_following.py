"""
趨勢跟蹤策略 (Trend Following)
適用市場：BTC, CL_OIL（原油）
邏輯：EMA 交叉確認方向 + MACD 動能確認 + 成交量放大過濾
"""

import numpy as np
from typing import Optional
from strategies.base import BaseStrategy, Signal, Indicators


class TrendFollowingStrategy(BaseStrategy):
    """
    趨勢跟蹤策略
    - 使用 EMA 20/50 交叉判斷趨勢方向
    - MACD 柱狀圖確認動能
    - 成交量放大作為進場確認
    - ATR 動態止損止盈 + 通用追蹤止損
    """

    def generate_signal(
        self,
        closes: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        volumes: np.ndarray,
        current_position: Optional[str] = None,
        entry_price: float = 0.0,
        bars_held: int = 0,
    ) -> Signal:
        self.bar_count += 1

        # 需要足夠的歷史數據
        min_bars = max(
            self.params.get("ema_slow", 50) + 5,
            self.params.get("macd_slow", 26) + self.params.get("macd_signal", 9) + 5,
        )
        if len(closes) < min_bars:
            return Signal(direction=None, strength=0, reason="數據不足")

        # === 計算指標 ===
        ema_fast = Indicators.ema(closes, self.params.get("ema_fast", 20))
        ema_slow = Indicators.ema(closes, self.params.get("ema_slow", 50))
        macd_line, signal_line, histogram = Indicators.macd(
            closes,
            self.params.get("macd_fast", 12),
            self.params.get("macd_slow", 26),
            self.params.get("macd_signal", 9),
        )
        atr = Indicators.atr(highs, lows, closes, self.params.get("atr_period", 14))
        vol_sma = Indicators.volume_sma(volumes, 20)

        # 取最新值
        curr_price = closes[-1]
        curr_ema_fast = ema_fast[-1]
        curr_ema_slow = ema_slow[-1]
        curr_hist = histogram[-1]
        prev_hist = histogram[-2] if len(histogram) > 1 else 0
        curr_atr = atr[-1]
        curr_vol = volumes[-1]
        avg_vol = vol_sma[-1] if not np.isnan(vol_sma[-1]) else volumes[-1]

        # === 如果有持倉，只返回策略特有的退出條件 ===
        # （sl/tp/trailing 止損已由 portfolio_manager 直接呼叫 should_close() 處理，此處不重複）
        if current_position is not None:
            # 策略特有退出：EMA 趨勢反轉
            if current_position == "long" and curr_ema_fast < curr_ema_slow:
                return Signal(direction=None, strength=0.8, reason="EMA 死叉，趨勢反轉")
            elif current_position == "short" and curr_ema_fast > curr_ema_slow:
                return Signal(direction=None, strength=0.8, reason="EMA 金叉，趨勢反轉")

            # 策略特有退出：MACD 動能衰減
            min_hold = self.params.get("min_bars_hold", 3)
            if bars_held >= min_hold:
                if current_position == "long" and curr_hist < prev_hist and curr_hist < 0:
                    return Signal(direction=None, strength=0.8, reason="MACD 動能衰減")
                elif current_position == "short" and curr_hist > prev_hist and curr_hist > 0:
                    return Signal(direction=None, strength=0.8, reason="MACD 動能衰減")

            return Signal(direction=current_position, strength=0.5, reason="持倉中")

        # === 開倉信號 ===
        strength = 0.0
        reasons = []

        # 條件 1: EMA 交叉方向
        ema_bullish = curr_ema_fast > curr_ema_slow
        ema_bearish = curr_ema_fast < curr_ema_slow

        # 條件 2: MACD 動能
        macd_bullish = curr_hist > 0 and curr_hist > prev_hist
        macd_bearish = curr_hist < 0 and curr_hist < prev_hist

        # 條件 3: 成交量確認
        vol_confirm = True
        if self.params.get("volume_confirm", True):
            vol_confirm = curr_vol > avg_vol * 1.1

        # 條件 4: 價格在 EMA 正確側
        price_above_ema = curr_price > curr_ema_fast
        price_below_ema = curr_price < curr_ema_fast

        # === 做多信號 ===
        if ema_bullish and macd_bullish and price_above_ema:
            strength += 0.4
            reasons.append("EMA多頭")
            if vol_confirm:
                strength += 0.2
                reasons.append("量能確認")
            if curr_hist > prev_hist:
                strength += 0.2
                reasons.append("MACD加速")
            if closes[-2] < ema_slow[-2] and curr_price > curr_ema_slow:
                strength += 0.2
                reasons.append("突破慢線")

            if strength >= 0.5:
                sl, tp = self.calc_sl_tp("long", curr_price, curr_atr)
                return Signal(
                    direction="long", strength=min(strength, 1.0),
                    reason=" + ".join(reasons),
                    sl_price=sl, tp_price=tp,
                )

        # === 做空信號 ===
        if ema_bearish and macd_bearish and price_below_ema:
            strength += 0.4
            reasons.append("EMA空頭")
            if vol_confirm:
                strength += 0.2
                reasons.append("量能確認")
            if curr_hist < prev_hist:
                strength += 0.2
                reasons.append("MACD加速")
            if closes[-2] > ema_slow[-2] and curr_price < curr_ema_slow:
                strength += 0.2
                reasons.append("跌破慢線")

            if strength >= 0.5:
                sl, tp = self.calc_sl_tp("short", curr_price, curr_atr)
                return Signal(
                    direction="short", strength=min(strength, 1.0),
                    reason=" + ".join(reasons),
                    sl_price=sl, tp_price=tp,
                )

        return Signal(direction=None, strength=0, reason="無信號")
