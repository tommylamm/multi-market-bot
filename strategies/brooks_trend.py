"""
Brooks 趨勢策略 v1.1
Bug #7 修復：補充做空信號（三線空頭排列回調做空）
"""
from strategies.base import BaseStrategy, Indicators, Signal


class BrooksTrendStrategy(BaseStrategy):
    def generate_signal(self, closes, highs, lows, volumes,
                        current_position=None, entry_price=0.0, bars_held=0):
        if len(closes) < 50:
            return Signal(None, 0, "數據不足")

        e9  = Indicators.ema(closes, 9)[-1]
        e21 = Indicators.ema(closes, 21)[-1]
        e50 = Indicators.ema(closes, 50)[-1]
        atr = Indicators.atr(highs, lows, closes, 14)[-1]
        cp  = closes[-1]

        # Bug #3：有持倉只做策略特有退出判斷
        if current_position is not None:
            min_hold = self.params.get("min_bars_hold", 2)
            if bars_held >= min_hold:
                if current_position == "long" and e9 < e21:
                    return Signal(None, 0.8, "Brooks多頭結構破壞")
                elif current_position == "short" and e9 > e21:
                    return Signal(None, 0.8, "Brooks空頭結構破壞")
            return Signal(current_position, 0.5, "持倉中")

        # 做多：三線多頭排列（e9 > e21 > e50），回調至 e21 附近入場
        # 放寬區間：從 0.5 ATR 擴大到 1.5 ATR，提高觸發頻率
        if e9 > e21 > e50 and cp > e21 and cp < e21 + 1.5 * atr:
            return Signal(
                "long", 0.6, "Brooks多頭回調入場",
                sl_price=cp - 1.2 * atr,
                tp_price=cp + 2.5 * atr,
            )

        # 三線空頭排列（e9 < e21 < e50），反彈至 e21 附近做空
        # 放寬區間：從 0.5 ATR 擴大到 1.5 ATR
        if e9 < e21 < e50 and cp < e21 and cp > e21 - 1.5 * atr:
            return Signal(
                "short", 0.6, "Brooks空頭反彈做空",
                sl_price=cp + 1.2 * atr,
                tp_price=cp - 2.5 * atr,
            )

        return Signal(None, 0, "無信號")
