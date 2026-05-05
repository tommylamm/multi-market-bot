"""
均值回歸策略 (Mean Reversion)
適用市場：ETH, GOLD（黃金）
邏輯：RSI 超買超賣 + 布林通道偏離 + 回歸中軌止盈
"""

import numpy as np
from typing import Optional
from strategies.base import BaseStrategy, Signal, Indicators


class MeanReversionStrategy(BaseStrategy):
    """
    均值回歸策略
    - RSI 低於 25 且價格觸及布林下軌 → 做多
    - RSI 高於 75 且價格觸及布林上軌 → 做空
    - 止盈目標：回歸布林中軌
    - 使用 Maker 限價單降低手續費
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
        bb_period = self.params.get("bb_period", 20)
        rsi_period = self.params.get("rsi_period", 14)
        min_bars = max(bb_period, rsi_period) + 5
        if len(closes) < min_bars:
            return Signal(direction=None, strength=0, reason="數據不足")

        # === 計算指標 ===
        rsi = Indicators.rsi(closes, rsi_period)
        bb_upper, bb_lower, bb_middle = Indicators.bollinger_bands(
            closes, bb_period, self.params.get("bb_std", 2.0)
        )
        atr = Indicators.atr(highs, lows, closes, self.params.get("atr_period", 14))

        curr_price = closes[-1]
        curr_rsi = rsi[-1]
        curr_upper = bb_upper[-1]
        curr_lower = bb_lower[-1]
        curr_middle = bb_middle[-1]
        curr_atr = atr[-1]

        # === 如果有持倉，檢查是否需要平倉 ===
        if current_position is not None:
            close_reason = self._check_exit(
                current_position, entry_price, curr_price,
                curr_atr, bars_held, curr_rsi, curr_middle,
            )
            if close_reason:
                return Signal(
                    direction=None, strength=0.8,
                    reason=close_reason,
                )
            return Signal(direction=current_position, strength=0.5, reason="持倉中")

        # === 開倉信號 ===
        rsi_oversold = self.params.get("rsi_oversold", 25)
        rsi_overbought = self.params.get("rsi_overbought", 75)

        # 計算布林帶寬度（用於過濾窄幅震盪）
        bb_width = (curr_upper - curr_lower) / curr_middle if curr_middle > 0 else 0
        if bb_width < 0.005:
            return Signal(direction=None, strength=0, reason="布林帶過窄，跳過")

        # === 做多信號：超賣反彈 ===
        if curr_rsi < rsi_oversold and curr_price <= curr_lower:
            strength = 0.0
            reasons = []

            # RSI 越低，信號越強
            if curr_rsi < 20:
                strength += 0.5
                reasons.append(f"RSI極度超賣({curr_rsi:.0f})")
            else:
                strength += 0.3
                reasons.append(f"RSI超賣({curr_rsi:.0f})")

            # 價格偏離布林下軌的程度
            deviation = (curr_lower - curr_price) / curr_atr if curr_atr > 0 else 0
            if deviation > 0.5:
                strength += 0.3
                reasons.append("深度偏離下軌")
            else:
                strength += 0.15
                reasons.append("觸及下軌")

            # 前一根 K 線也是下跌（確認超賣延續）
            if len(closes) > 2 and closes[-2] < closes[-3]:
                strength += 0.1
                reasons.append("連續下跌")

            if strength >= 0.4:
                # 止盈目標：回歸中軌
                tp = curr_middle
                sl_mult = self.params.get("atr_sl_mult", 1.2)
                sl = curr_price - sl_mult * curr_atr

                return Signal(
                    direction="long", strength=min(strength, 1.0),
                    reason=" + ".join(reasons),
                    sl_price=sl, tp_price=tp,
                )

        # === 做空信號：超買回落 ===
        if curr_rsi > rsi_overbought and curr_price >= curr_upper:
            strength = 0.0
            reasons = []

            if curr_rsi > 80:
                strength += 0.5
                reasons.append(f"RSI極度超買({curr_rsi:.0f})")
            else:
                strength += 0.3
                reasons.append(f"RSI超買({curr_rsi:.0f})")

            deviation = (curr_price - curr_upper) / curr_atr if curr_atr > 0 else 0
            if deviation > 0.5:
                strength += 0.3
                reasons.append("深度偏離上軌")
            else:
                strength += 0.15
                reasons.append("觸及上軌")

            if len(closes) > 2 and closes[-2] > closes[-3]:
                strength += 0.1
                reasons.append("連續上漲")

            if strength >= 0.4:
                tp = curr_middle
                sl_mult = self.params.get("atr_sl_mult", 1.2)
                sl = curr_price + sl_mult * curr_atr

                return Signal(
                    direction="short", strength=min(strength, 1.0),
                    reason=" + ".join(reasons),
                    sl_price=sl, tp_price=tp,
                )

        return Signal(direction=None, strength=0, reason="無信號")

    def _check_exit(
        self,
        position: str,
        entry_price: float,
        current_price: float,
        atr: float,
        bars_held: int,
        rsi: float,
        bb_middle: float,
    ) -> Optional[str]:
        """檢查是否應該平倉"""

        sl_mult = self.params.get("atr_sl_mult", 1.2)
        min_hold = self.params.get("min_bars_hold", 1)

        # 止損
        if position == "long":
            sl = entry_price - sl_mult * atr
            if current_price <= sl:
                return f"止損 @{sl:.2f}"
        elif position == "short":
            sl = entry_price + sl_mult * atr
            if current_price >= sl:
                return f"止損 @{sl:.2f}"

        # 均值回歸止盈：回到布林中軌
        if bars_held >= min_hold:
            if position == "long" and current_price >= bb_middle:
                return f"回歸中軌止盈 @{bb_middle:.2f}"
            if position == "short" and current_price <= bb_middle:
                return f"回歸中軌止盈 @{bb_middle:.2f}"

        # RSI 反轉信號
        if position == "long" and rsi > 65:
            return f"RSI回升止盈 ({rsi:.0f})"
        if position == "short" and rsi < 35:
            return f"RSI回落止盈 ({rsi:.0f})"

        # 最大持倉時間
        max_hold = self.params.get("max_bars_hold", 20)
        if bars_held >= max_hold:
            return f"超時平倉 ({bars_held} bars)"

        return None
