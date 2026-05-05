"""
Bollinger Band 均值回歸策略
適用場景：震盪/盤整行情 | 預期勝率：55-65%
"""
import numpy as np
from typing import Optional
from strategies.base import BaseStrategy, Signal, Indicators


class BollingerReversionStrategy(BaseStrategy):
    """布林通道均值回歸策略"""

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
        bb_period = self.params.get("bb_period", 20)
        bb_std = self.params.get("bb_std", 2.0)
        rsi_period = self.params.get("rsi_period", 14)
        rsi_oversold = self.params.get("rsi_oversold", 30)
        rsi_overbought = self.params.get("rsi_overbought", 70)
        atr_period = self.params.get("atr_period", 14)
        squeeze_threshold = self.params.get("squeeze_threshold", 0.02)
        max_bb_width = self.params.get("max_bb_width", 0.08)
        volume_confirm = self.params.get("volume_confirm", True)

        min_len = max(bb_period, rsi_period, atr_period) + 10
        if len(closes) < min_len:
            return Signal(direction=None, strength=0, reason="數據不足")

        upper, lower, middle = Indicators.bollinger_bands(closes, bb_period, bb_std)
        rsi = Indicators.rsi(closes, rsi_period)
        atr = Indicators.atr(highs, lows, closes, atr_period)

        current_close = closes[-1]
        current_rsi = rsi[-1]
        current_upper = upper[-1]
        current_lower = lower[-1]
        current_middle = middle[-1]
        current_atr = atr[-1]

        if np.isnan(current_upper) or np.isnan(current_rsi) or np.isnan(current_atr):
            return Signal(direction=None, strength=0, reason="指標計算中")

        bb_width = (current_upper - current_lower) / current_middle if current_middle > 0 else 0
        if bb_width < squeeze_threshold:
            return Signal(direction=None, strength=0, reason=f"Squeeze中({bb_width:.4f})")
        if bb_width > max_bb_width:
            return Signal(direction=None, strength=0, reason=f"趨勢太強({bb_width:.4f})")

        if volume_confirm and len(volumes) >= 20:
            vol_sma = Indicators.volume_sma(volumes, 20)
            if not np.isnan(vol_sma[-1]) and volumes[-1] < vol_sma[-1] * 0.7:
                return Signal(direction=None, strength=0, reason="成交量不足")

        bb_range = current_upper - current_lower
        bb_position = (current_close - current_lower) / bb_range if bb_range > 0 else 0.5

        if current_close <= current_lower and current_rsi <= rsi_oversold:
            prev_bb_range = upper[-2] - lower[-2]
            prev_bb_pos = (closes[-2] - lower[-2]) / prev_bb_range if prev_bb_range > 0 else 0.5
            if prev_bb_pos < 0.3:
                strength = min(1.0, (rsi_oversold - current_rsi) / 20 + (1 - bb_position))
                sl, tp = self._calc_mr_sl_tp("long", current_close, current_middle, current_atr)
                return Signal(
                    direction="long", strength=strength,
                    reason=f"BB下軌回歸(RSI={current_rsi:.0f},BB={bb_position:.2f})",
                    sl_price=sl, tp_price=tp,
                )

        if current_close >= current_upper and current_rsi >= rsi_overbought:
            prev_bb_range = upper[-2] - lower[-2]
            prev_bb_pos = (closes[-2] - lower[-2]) / prev_bb_range if prev_bb_range > 0 else 0.5
            if prev_bb_pos > 0.7:
                strength = min(1.0, (current_rsi - rsi_overbought) / 20 + bb_position)
                sl, tp = self._calc_mr_sl_tp("short", current_close, current_middle, current_atr)
                return Signal(
                    direction="short", strength=strength,
                    reason=f"BB上軌回歸(RSI={current_rsi:.0f},BB={bb_position:.2f})",
                    sl_price=sl, tp_price=tp,
                )

        return Signal(direction=None, strength=0, reason=f"等待極端(BB={bb_position:.2f},RSI={current_rsi:.0f})")

    def _calc_mr_sl_tp(self, direction: str, entry: float, middle: float, atr: float) -> tuple:
        """均值回歸止損止盈：止盈目標為中軌"""
        sl_mult = self.params.get("atr_sl_mult", 1.2)
        tp_mult = self.params.get("atr_tp_mult", 1.5)
        if direction == "long":
            sl = entry - sl_mult * atr
            tp_atr = entry + tp_mult * atr
            tp = min(tp_atr, middle) if middle > entry else tp_atr
        else:
            sl = entry + sl_mult * atr
            tp_atr = entry - tp_mult * atr
            tp = max(tp_atr, middle) if middle < entry else tp_atr
        return sl, tp
