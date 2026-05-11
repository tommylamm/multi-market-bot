"""
Pattern / reversal strategies and their local indicator helpers.

These strategies are intentionally kept together because they are small,
price-action oriented, and share ExtendedIndicators.
"""

import numpy as np

from strategies.base import BaseStrategy, Indicators, Signal


class ExtendedIndicators:
    """Price-action helpers used by pattern/reversal strategies."""

    @staticmethod
    def find_swings_realtime(highs, lows, lookback=5):
        """尋找擺動高低點（實時模式，右側確認最多lookback根）"""
        n = len(highs)
        sh, sl = [], []
        for i in range(lookback, n):
            is_h = all(highs[i] >= highs[i - j] for j in range(1, lookback + 1))
            is_l = all(lows[i] <= lows[i - j] for j in range(1, lookback + 1))
            rb = min(lookback, n - 1 - i)
            if rb > 0:
                is_h = is_h and all(highs[i] >= highs[i + j] for j in range(1, rb + 1))
                is_l = is_l and all(lows[i] <= lows[i + j] for j in range(1, rb + 1))
            if is_h:
                sh.append((i, float(highs[i])))
            if is_l:
                sl.append((i, float(lows[i])))
        return sh, sl

    @staticmethod
    def price_action_features(opens, highs, lows, closes):
        if len(closes) < 2:
            return {"is_pin_bar": False, "close_position": 0.5}
        o, h, l, c = opens[-1], highs[-1], lows[-1], closes[-1]
        br = max(h - l, 1e-10)
        body = abs(c - o)
        cp = (c - l) / br
        lsr = (min(o, c) - l) / br
        usr = (h - max(o, c)) / br
        return {
            "is_pin_bar_bull": lsr > (body / br) * 2 and cp > 0.6,
            "is_pin_bar_bear": usr > (body / br) * 2 and cp < 0.4,
            "is_strong_bull": cp > 0.75 and body / br > 0.5,
            "is_strong_bear": cp < 0.25 and body / br > 0.5,
        }

    @staticmethod
    def false_breakout_detect(highs, lows, closes, lookback=20, confirm_bars=3):
        """假突破偵測"""
        n = len(closes)
        if n < lookback + confirm_bars + 1:
            return None, 0.0
        re = n - confirm_bars - 1
        rs = max(0, re - lookback)
        sup = np.min(lows[rs:re])
        res = np.max(highs[rs:re])
        # 假突破下跌：確認根曾破支撐，但收盤回到支撐上方
        if any(lows[i] < sup for i in range(n - confirm_bars, n)) and closes[-1] > sup:
            return "false_breakout_down", sup
        # 假突破上漲：確認根曾破阻力，但收盤回到阻力下方
        if any(highs[i] > res for i in range(n - confirm_bars, n)) and closes[-1] < res:
            return "false_breakout_up", res
        return None, 0.0

    @staticmethod
    def sperandeo_123(highs, lows, closes, lookback=5):
        """
        Sperandeo 1-2-3 反轉形態（Bug #9 修復）
        多頭123：P1=擺動低點 → P2=後續反彈高點 → P3=回調（>P1） → 突破P2做多
        空頭123：P1=擺動高點 → P2=後續回落低點 → P3=反彈（<P1） → 跌破P2做空
        """
        sh, sl = ExtendedIndicators.find_swings_realtime(highs, lows, lookback)
        if len(sh) < 2 or len(sl) < 2:
            return None, {}

        cp = closes[-1]

        # --- 多頭 123 ---
        if len(sl) >= 2:
            p1_idx, p1 = sl[-2]  # 較早的擺動低點（第1點）
            # 第2點：p1 之後的擺動高點
            sh_after = [(i, h) for i, h in sh if i > p1_idx]
            if sh_after:
                p2_idx, p2 = sh_after[-1]
                # 第3點：p2 之後的擺動低點，且必須高於 p1（不破前低）
                sl_after = [(i, l) for i, l in sl if i > p2_idx]
                if sl_after:
                    p3_idx, p3 = sl_after[-1]
                    if p3 > p1 and cp > p2:  # 突破 P2 入場
                        return "long", {"p1": p1, "p2": p2, "p3": p3, "sl": p3}

        # --- 空頭 123 ---
        if len(sh) >= 2:
            p1_idx, p1 = sh[-2]  # 較早的擺動高點（第1點）
            # 第2點：p1 之後的擺動低點
            sl_after = [(i, l) for i, l in sl if i > p1_idx]
            if sl_after:
                p2_idx, p2 = sl_after[-1]
                # 第3點：p2 之後的擺動高點，且必須低於 p1（不破前高）
                sh_after = [(i, h) for i, h in sh if i > p2_idx]
                if sh_after:
                    p3_idx, p3 = sh_after[-1]
                    if p3 < p1 and cp < p2:  # 跌破 P2 入場
                        return "short", {"p1": p1, "p2": p2, "p3": p3, "sl": p3}

        return None, {}


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


class BrooksTrendStrategy(BaseStrategy):
    def generate_signal(self, closes, highs, lows, volumes,
                        current_position=None, entry_price=0.0, bars_held=0):
        if len(closes) < 50:
            return Signal(None, 0, "數據不足")

        e9 = Indicators.ema(closes, 9)[-1]
        e21 = Indicators.ema(closes, 21)[-1]
        e50 = Indicators.ema(closes, 50)[-1]
        atr = Indicators.atr(highs, lows, closes, 14)[-1]
        cp = closes[-1]

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


class SperandeoReversalStrategy(BaseStrategy):
    def generate_signal(self, closes, highs, lows, volumes,
                        current_position=None, entry_price=0.0, bars_held=0):
        if len(closes) < 40:
            return Signal(None, 0, "數據不足")

        sig, det = ExtendedIndicators.sperandeo_123(highs, lows, closes)
        atr = Indicators.atr(highs, lows, closes, 14)[-1]

        if current_position:
            return Signal(current_position, 0.5, "持倉")
        if sig:
            return Signal(
                sig, 0.7, "123反轉",
                sl_price=det["sl"],
                tp_price=closes[-1] + 2 * atr if sig == "long" else closes[-1] - 2 * atr,
            )
        return Signal(None, 0, "無信號")
