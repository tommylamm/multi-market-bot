from strategies.base import BaseStrategy, Indicators, Signal
class BrooksTrendStrategy(BaseStrategy):
    def generate_signal(self, closes, highs, lows, volumes, current_position=None, entry_price=0.0, bars_held=0):
        if len(closes) < 50: return Signal(None, 0, "數據不足")
        e9, e21, e50 = Indicators.ema(closes, 9)[-1], Indicators.ema(closes, 21)[-1], Indicators.ema(closes, 50)[-1]
        atr = Indicators.atr(highs, lows, closes, 14)[-1]
        if current_position: return Signal(current_position, 0.5, "持倉")
        if e9 > e21 > e50 and closes[-1] > e21 and closes[-1] < e21 + 0.5*atr:
            return Signal("long", 0.6, "Brooks回調入場", sl_price=closes[-1]-1.2*atr, tp_price=closes[-1]+2.5*atr)
        return Signal(None, 0, "無信號")
