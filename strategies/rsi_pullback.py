"""
RSI 回調策略 (RSI Pullback)
高勝率策略：在趨勢中等待回調入場
邏輯：大趨勢方向由 EMA200 確定，RSI 回調到 40-50（多頭）或 50-60（空頭）時入場
勝率預期：55-65%（順勢回調，成功率高）
"""
import numpy as np
from typing import Optional
from strategies.base import BaseStrategy, Signal, Indicators


class RSIPullbackStrategy(BaseStrategy):
    """
    RSI 回調策略
    - 用 EMA200 判斷大趨勢方向
    - 在趨勢方向上等待 RSI 回調到中性區域
    - 回調結束（RSI 反轉）時入場
    - 止損窄（1.2 ATR），止盈適中（2.0 ATR）
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
        min_bars = max(self.params.get("ema_trend_period", 100) + 5, 50)
        if len(closes) < min_bars:
            return Signal(direction=None, strength=0, reason="數據不足")

        # === 計算指標 ===
        ema_trend = Indicators.ema(closes, self.params.get("ema_trend_period", 100))
        rsi = Indicators.rsi(closes, self.params.get("rsi_period", 14))
        atr = Indicators.atr(highs, lows, closes, self.params.get("atr_period", 14))

        curr_price = closes[-1]
        prev_price = closes[-2]
        curr_rsi = rsi[-1]
        prev_rsi = rsi[-2]
        curr_ema_trend = ema_trend[-1]
        curr_atr = atr[-1]

        if np.isnan(curr_ema_trend) or curr_atr <= 0:
            return Signal(direction=None, strength=0, reason="指標未就緒")

        # === 如果有持倉，檢查是否需要平倉 ===
        if current_position is not None:
            close_reason = self._check_exit(
                current_position, entry_price, curr_price,
                curr_atr, bars_held, curr_rsi,
            )
            if close_reason:
                return Signal(direction=None, strength=0.8, reason=close_reason)
            return Signal(direction=current_position, strength=0.5, reason="持倉中")

        # === 判斷大趨勢 ===
        is_uptrend = curr_price > curr_ema_trend
        is_downtrend = curr_price < curr_ema_trend

        # RSI 回調區間
        pullback_low = self.params.get("rsi_pullback_low", 38)
        pullback_high = self.params.get("rsi_pullback_high", 62)

        # === 做多信號：上升趨勢 + RSI 從回調區反彈 ===
        if is_uptrend:
            # RSI 曾經回調到 38-50，現在開始反彈（prev < curr 且 curr > pullback_low）
            if prev_rsi < 50 and curr_rsi > prev_rsi and pullback_low <= curr_rsi <= 55:
                strength = 0.0
                reasons = []

                # 趨勢強度：價格離 EMA 的距離
                trend_strength = (curr_price - curr_ema_trend) / curr_atr
                if trend_strength > 1.0:
                    strength += 0.3
                    reasons.append("強勢趨勢")
                else:
                    strength += 0.2
                    reasons.append("溫和趨勢")

                # RSI 反彈確認
                if curr_rsi > prev_rsi + 2:
                    strength += 0.3
                    reasons.append(f"RSI反彈({curr_rsi:.0f})")
                else:
                    strength += 0.2
                    reasons.append(f"RSI回升({curr_rsi:.0f})")

                # 價格確認：收盤 > 前一根收盤
                if curr_price > prev_price:
                    strength += 0.2
                    reasons.append("價格確認")

                if strength >= 0.5:
                    sl_mult = self.params.get("atr_sl_mult", 1.2)
                    tp_mult = self.params.get("atr_tp_mult", 2.0)
                    sl = curr_price - sl_mult * curr_atr
                    tp = curr_price + tp_mult * curr_atr
                    return Signal(
                        direction="long", strength=min(strength, 1.0),
                        reason=" + ".join(reasons),
                        sl_price=sl, tp_price=tp,
                    )

        # === 做空信號：下降趨勢 + RSI 從超買區回落 ===
        if is_downtrend:
            if prev_rsi > 50 and curr_rsi < prev_rsi and 45 <= curr_rsi <= pullback_high:
                strength = 0.0
                reasons = []

                trend_strength = (curr_ema_trend - curr_price) / curr_atr
                if trend_strength > 1.0:
                    strength += 0.3
                    reasons.append("強勢下跌趨勢")
                else:
                    strength += 0.2
                    reasons.append("溫和下跌趨勢")

                if prev_rsi - curr_rsi > 2:
                    strength += 0.3
                    reasons.append(f"RSI回落({curr_rsi:.0f})")
                else:
                    strength += 0.2
                    reasons.append(f"RSI下降({curr_rsi:.0f})")

                if curr_price < prev_price:
                    strength += 0.2
                    reasons.append("價格確認")

                if strength >= 0.5:
                    sl_mult = self.params.get("atr_sl_mult", 1.2)
                    tp_mult = self.params.get("atr_tp_mult", 2.0)
                    sl = curr_price + sl_mult * curr_atr
                    tp = curr_price - tp_mult * curr_atr
                    return Signal(
                        direction="short", strength=min(strength, 1.0),
                        reason=" + ".join(reasons),
                        sl_price=sl, tp_price=tp,
                    )

        return Signal(direction=None, strength=0, reason="無回調信號")

    def _check_exit(
        self,
        position: str,
        entry_price: float,
        current_price: float,
        atr: float,
        bars_held: int,
        rsi: float,
    ) -> Optional[str]:
        """檢查是否應該平倉"""
        sl_mult = self.params.get("atr_sl_mult", 1.2)
        tp_mult = self.params.get("atr_tp_mult", 2.0)

        # 止損
        if position == "long":
            sl = entry_price - sl_mult * atr
            if current_price <= sl:
                return f"止損 @{sl:.2f}"
        elif position == "short":
            sl = entry_price + sl_mult * atr
            if current_price >= sl:
                return f"止損 @{sl:.2f}"

        # 止盈
        if position == "long":
            tp = entry_price + tp_mult * atr
            if current_price >= tp:
                return f"止盈 @{tp:.2f}"
        elif position == "short":
            tp = entry_price - tp_mult * atr
            if current_price <= tp:
                return f"止盈 @{tp:.2f}"

        # RSI 極端值平倉
        if position == "long" and rsi > 75:
            return f"RSI超買平倉 ({rsi:.0f})"
        if position == "short" and rsi < 25:
            return f"RSI超賣平倉 ({rsi:.0f})"

        # 最大持倉時間
        max_hold = self.params.get("max_bars_hold", 30)
        if bars_held >= max_hold:
            return f"超時平倉 ({bars_held} bars)"

        return None
