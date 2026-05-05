import numpy as np
from typing import List, Tuple, Optional
class ExtendedIndicators:
    @staticmethod
    def find_swings_realtime(highs, lows, lookback=5):
        n = len(highs)
        sh, sl = [], []
        for i in range(lookback, n):
            is_h = all(highs[i] >= highs[i-j] for j in range(1, lookback+1))
            is_l = all(lows[i] <= lows[i-j] for j in range(1, lookback+1))
            rb = min(lookback, n-1-i)
            if rb > 0:
                is_h = is_h and all(highs[i] >= highs[i+j] for j in range(1, rb+1))
                is_l = is_l and all(lows[i] <= lows[i+j] for j in range(1, rb+1))
            if is_h: sh.append((i, float(highs[i])))
            if is_l: sl.append((i, float(lows[i])))
        return sh, sl
    @staticmethod
    def price_action_features(opens, highs, lows, closes):
        if len(closes) < 2: return {"is_pin_bar": False, "close_position": 0.5}
        o, h, l, c = opens[-1], highs[-1], lows[-1], closes[-1]
        br = max(h - l, 1e-10)
        body = abs(c - o)
        cp = (c - l) / br
        lsr = (min(o, c) - l) / br
        usr = (h - max(o, c)) / br
        return {"is_pin_bar_bull": lsr > (body/br)*2 and cp > 0.6, "is_pin_bar_bear": usr > (body/br)*2 and cp < 0.4, "is_strong_bull": cp > 0.75 and body/br > 0.5, "is_strong_bear": cp < 0.25 and body/br > 0.5}
    @staticmethod
    def false_breakout_detect(highs, lows, closes, lookback=20, confirm_bars=3):
        n = len(closes)
        if n < lookback + confirm_bars + 1: return None, 0.0
        re = n - confirm_bars - 1
        rs = max(0, re - lookback)
        sup, res = np.min(lows[rs:re]), np.max(highs[rs:re])
        if any(lows[i] < sup for i in range(n-confirm_bars, n)) and closes[-1] > sup: return "false_breakout_down", sup
        if any(highs[i] > res for i in range(n-confirm_bars, n)) and closes[-1] < res: return "false_breakout_up", res
        return None, 0.0
    @staticmethod
    def sperandeo_123(highs, lows, closes, lookback=5):
        sh, sl = ExtendedIndicators.find_swings_realtime(highs, lows, lookback)
        if len(sh) < 2 or len(sl) < 2: return None, {}
        cp = closes[-1]
        if len(sl) >= 3 and sl[-2][1] < sl[-3][1]:
            p1, p2 = sl[-2][1], max(h[1] for h in sh if h[0] > sl[-2][0]) if any(h[0] > sl[-2][0] for h in sh) else 0
            p3 = min(l[1] for l in sl if l[0] > 0) # simplified
            if p2 > 0 and cp > p2: return "long", {"p1":p1, "p2":p2, "sl":p1}
        return None, {}
