import numpy as np


class ExtendedIndicators:

    @staticmethod
    def find_swings_realtime(highs, lows, lookback=5):
        """尋找擺動高低點（實時模式，右側確認最多lookback根）"""
        n = len(highs)
        sh, sl = [], []
        for i in range(lookback, n):
            is_h = all(highs[i] >= highs[i - j] for j in range(1, lookback + 1))
            is_l = all(lows[i]  <= lows[i - j]  for j in range(1, lookback + 1))
            rb = min(lookback, n - 1 - i)
            if rb > 0:
                is_h = is_h and all(highs[i] >= highs[i + j] for j in range(1, rb + 1))
                is_l = is_l and all(lows[i]  <= lows[i + j]  for j in range(1, rb + 1))
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
        br  = max(h - l, 1e-10)
        body = abs(c - o)
        cp  = (c - l) / br
        lsr = (min(o, c) - l) / br
        usr = (h - max(o, c)) / br
        return {
            "is_pin_bar_bull": lsr > (body / br) * 2 and cp > 0.6,
            "is_pin_bar_bear": usr > (body / br) * 2 and cp < 0.4,
            "is_strong_bull":  cp > 0.75 and body / br > 0.5,
            "is_strong_bear":  cp < 0.25 and body / br > 0.5,
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
