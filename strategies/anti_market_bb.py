"""
反市場布林帶策略 v1.1
Bug #8 修復：補充做空開倉信號（上軌 + RSI 超買 做空）
"""
from strategies.base import BaseStrategy, Indicators, Signal
from strategies.indicators_extended import ExtendedIndicators


class AntiMarketBBStrategy(BaseStrategy):
    def generate_signal(self, closes, highs, lows, volumes,
                        current_position=None, entry_price=0.0, bars_held=0):
        bb_p = self.params.get("bb_period", 20)
        if len(closes) < bb_p + 10:
            return Signal(None, 0, "數據不足")

        u, l, m = Indicators.bollinger_bands(closes, bb_p, 2.0)
        rsi = Indicators.rsi(closes, 14)
        atr = Indicators.atr(highs, lows, closes, 14)[-1]
        cp, crsi = closes[-1], rsi[-1]

        # Bug #3：有持倉只做策略特有退出判斷
        if current_position is not None:
            if current_position == "long" and (cp >= u[-1] or crsi > 75):
                return Signal(None, 0.8, "布林上軌/RSI超買止盈")
            elif current_position == "short" and (cp <= l[-1] or crsi < 25):
                return Signal(None, 0.8, "布林下軌/RSI超賣止盈")
            return Signal(current_position, 0.5, "持倉")

        fb_sig, _ = ExtendedIndicators.false_breakout_detect(highs, lows, closes)

        # 做多：假突破下跌 or 下軌 + 超賣
        if fb_sig == "false_breakout_down" or (cp <= l[-1] and crsi < 25):
            return Signal(
                "long", 0.7, "反市場做多",
                sl_price=cp - 1.5 * atr,
                tp_price=u[-1],
            )

        # Bug #8：補充做空：假突破上漲 or 上軌 + 超買
        if fb_sig == "false_breakout_up" or (cp >= u[-1] and crsi > 75):
            return Signal(
                "short", 0.7, "反市場做空",
                sl_price=cp + 1.5 * atr,
                tp_price=l[-1],
            )

        return Signal(None, 0, "無信號")
