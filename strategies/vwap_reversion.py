"""
VWAP 均值回歸策略 (VWAP Mean Reversion)
核心：價格偏離 VWAP 後回歸
"""

import numpy as np
from typing import Optional
from strategies.base import BaseStrategy, Signal, Indicators


class VWAPReversionStrategy(BaseStrategy):
    """
    VWAP 均值回歸策略
    - 計算近 N 根 K 線的成交量加權均價（模擬 VWAP）
    - 當價格偏離 VWAP 時，等待反轉信號入場
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
        vwap_period = self.params.get("vwap_period", 30)
        min_bars = vwap_period + 5

        if len(closes) < min_bars:
            return Signal(direction=None, strength=0, reason="數據不足")

        # === 計算指標 ===
        atr = Indicators.atr(highs, lows, closes, self.params.get("atr_period", 14))
        rsi = Indicators.rsi(closes, 14)

        curr_price = closes[-1]
        prev_price = closes[-2]
        curr_atr = atr[-1]
        curr_rsi = rsi[-1]

        if curr_atr <= 0:
            return Signal(direction=None, strength=0, reason="ATR=0")

        # 計算模擬 VWAP
        typical_prices = (highs[-vwap_period:] + lows[-vwap_period:] + closes[-vwap_period:]) / 3
        vols = volumes[-vwap_period:]
        total_vol = np.sum(vols)
        vwap = np.sum(typical_prices * vols) / total_vol if total_vol > 0 else np.mean(typical_prices)

        # 計算偏離度
        deviation = (curr_price - vwap) / curr_atr

        # === 如果有持倉，檢查是否需要平倉 ===
        if current_position is not None:
            sl, tp = self.calc_sl_tp(current_position, entry_price, curr_atr)
            
            # 1. 檢查基類的通用止盈止損 (包含追蹤止損)
            close_reason = self.should_close(
                current_position, entry_price, curr_price,
                sl, tp, bars_held, curr_atr
            )
            
            # 2. 策略特有退出：回歸 VWAP 或偏離加劇
            if not close_reason:
                if current_position == "long" and curr_price >= vwap:
                    close_reason = "回歸VWAP止盈"
                elif current_position == "short" and curr_price <= vwap:
                    close_reason = "回歸VWAP止盈"
                elif current_position == "long" and deviation < -3.5:
                    close_reason = "偏離加劇止損"
                elif current_position == "short" and deviation > 3.5:
                    close_reason = "偏離加劇止損"

            if close_reason:
                return Signal(direction=None, strength=0.8, reason=close_reason)
                
            return Signal(direction=current_position, strength=0.5, reason="持倉中")

        # === 開倉條件 ===
        dev_threshold = self.params.get("deviation_threshold", 1.5)

        # 做多：價格大幅低於 VWAP
        if deviation < -dev_threshold:
            if curr_price > prev_price or (curr_rsi > 35 and rsi[-2] < 35):
                strength = 0.5 if deviation < -2.5 else 0.4
                sl, tp = self.calc_sl_tp("long", curr_price, curr_atr)
                return Signal(direction="long", strength=strength, reason=f"偏離VWAP({deviation:.1f}σ)", sl_price=sl, tp_price=vwap)

        # 做空：價格大幅高於 VWAP
        if deviation > dev_threshold:
            if curr_price < prev_price or (curr_rsi < 65 and rsi[-2] > 65):
                strength = 0.5 if deviation > 2.5 else 0.4
                sl, tp = self.calc_sl_tp("short", curr_price, curr_atr)
                return Signal(direction="short", strength=strength, reason=f"偏離VWAP({deviation:.1f}σ)", sl_price=sl, tp_price=vwap)

        return Signal(direction=None, strength=0, reason="無偏離信號")
