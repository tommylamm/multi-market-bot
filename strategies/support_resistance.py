"""
支撐阻力策略 (Support & Resistance)
核心：識別關鍵價位平台 + 觸碰反彈/回落信號
"""

import numpy as np
from typing import Optional
from strategies.base import BaseStrategy, Indicators, Signal


class SupportResistanceStrategy(BaseStrategy):
    """
    支撐阻力策略
    - 識別近 N 根 K 線的顯著高點和低點
    - 當價格接近支撐位時做多，接近阻力位時做空
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
        lookback = self.params.get("lookback_period", 50)
        if len(closes) < lookback + 5:
            return Signal(direction=None, strength=0, reason="數據不足")

        curr_price = closes[-1]
        prev_price = closes[-2]
        atr = Indicators.atr(highs, lows, closes, self.params.get("atr_period", 14))
        curr_atr = atr[-1]
        rsi = Indicators.rsi(closes, 14)
        curr_rsi = rsi[-1]

        # 識別支撐和阻力位
        recent_highs = highs[-lookback:-1]
        recent_lows = lows[-lookback:-1]
        support_levels = self._find_support_levels(recent_lows, curr_atr)
        resistance_levels = self._find_resistance_levels(recent_highs, curr_atr)

        # === 如果有持倉，檢查是否需要平倉 ===
        if current_position is not None:
            sl, tp = self.calc_sl_tp(current_position, entry_price, curr_atr)
            
            # 1. 檢查基類的通用止盈止損 (包含追蹤止損)
            close_reason = self.should_close(
                current_position, entry_price, curr_price,
                sl, tp, bars_held, curr_atr
            )
            
            # 2. 策略特有退出：碰到反向關鍵位
            if not close_reason:
                if current_position == "long":
                    for r in resistance_levels:
                        if curr_price >= r and curr_price > entry_price:
                            close_reason = f"觸及阻力止盈 @{r:.2f}"
                            break
                elif current_position == "short":
                    for s in support_levels:
                        if curr_price <= s and curr_price < entry_price:
                            close_reason = f"觸及支撐止盈 @{s:.2f}"
                            break

            if close_reason:
                return Signal(direction=None, strength=0.8, reason=close_reason)
                
            return Signal(direction=current_position, strength=0.5, reason="持倉中")

        # === 開倉邏輯 ===
        proximity_atr = self.params.get("proximity_atr", 0.5)
        strength = 0.0
        reasons = []

        # 做多：接近支撐位
        for support in support_levels:
            distance = (curr_price - support) / curr_atr
            if 0 < distance < proximity_atr:
                if curr_price > prev_price and curr_rsi > 35:
                    strength = 0.4 if distance < 0.2 else 0.3
                    reasons.append(f"接近支撐({support:.2f})")
                    if curr_price > prev_price: strength += 0.2; reasons.append("反彈中")
                    
                    if strength >= 0.5:
                        sl, tp = self.calc_sl_tp("long", curr_price, curr_atr)
                        return Signal(direction="long", strength=min(strength, 1.0), reason=" + ".join(reasons), sl_price=sl, tp_price=tp)

        # 做空：接近阻力位
        for resistance in resistance_levels:
            distance = (resistance - curr_price) / curr_atr
            if 0 < distance < proximity_atr:
                if curr_price < prev_price and curr_rsi < 65:
                    strength = 0.4 if distance < 0.2 else 0.3
                    reasons.append(f"接近阻力({resistance:.2f})")
                    if curr_price < prev_price: strength += 0.2; reasons.append("回落中")
                    
                    if strength >= 0.5:
                        sl, tp = self.calc_sl_tp("short", curr_price, curr_atr)
                        return Signal(direction="short", strength=min(strength, 1.0), reason=" + ".join(reasons), sl_price=sl, tp_price=tp)

        return Signal(direction=None, strength=0, reason="無信號")

    def _find_support_levels(self, lows: np.ndarray, atr: float) -> list:
        levels = []
        for i in range(2, len(lows) - 2):
            if lows[i] <= lows[i-1] and lows[i] <= lows[i-2] and lows[i] <= lows[i+1] and lows[i] <= lows[i+2]:
                levels.append(lows[i])
        return self._merge_levels(levels, atr * 0.5)

    def _find_resistance_levels(self, highs: np.ndarray, atr: float) -> list:
        levels = []
        for i in range(2, len(highs) - 2):
            if highs[i] >= highs[i-1] and highs[i] >= highs[i-2] and highs[i] >= highs[i+1] and highs[i] >= highs[i+2]:
                levels.append(highs[i])
        return self._merge_levels(levels, atr * 0.5)

    def _merge_levels(self, levels: list, threshold: float) -> list:
        if not levels: return []
        levels = sorted(levels)
        merged = [levels[0]]
        for level in levels[1:]:
            if level - merged[-1] < threshold:
                merged[-1] = (merged[-1] + level) / 2
            else:
                merged.append(level)
        return merged
