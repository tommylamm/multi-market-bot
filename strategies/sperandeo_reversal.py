from strategies.base import BaseStrategy, Indicators, Signal
from strategies.indicators_extended import ExtendedIndicators
class SperandeoReversalStrategy(BaseStrategy):
    def generate_signal(self, closes, highs, lows, volumes, current_position=None, entry_price=0.0, bars_held=0):
        if len(closes) < 40: return Signal(None, 0, "數據不足")
        sig, det = ExtendedIndicators.sperandeo_123(highs, lows, closes)
        atr = Indicators.atr(highs, lows, closes, 14)[-1]
        if current_position: return Signal(current_position, 0.5, "持倉")
        if sig: return Signal(sig, 0.7, "123反轉", sl_price=det['sl'], tp_price=closes[-1]+2*atr if sig=="long" else closes[-1]-2*atr)
        return Signal(None, 0, "無信號")
