"""
EMA 動量策略 (EMA Momentum) v2.1
核心：三條 EMA 8/21/55 交叉 + 價格動量 + RSI 過濾
Bug 修復：
  - #3  移除重複的 should_close() 調用
  - #5  正確使用 ema_fast/ema_mid/ema_slow 三條線
  - #21 實現 RSI 過濾器（rsi_filter_low / rsi_filter_high）
"""

import numpy as np
from typing import Optional
from strategies.base import BaseStrategy, Indicators, Signal


class EMAMomentumStrategy(BaseStrategy):
    """
    EMA 動量策略
    - 三條 EMA (8/21/55) 排列判斷趨勢
    - 動量確認（3 根 K 線漲跌幅）
    - RSI 過濾（避免在超買/超賣區域順勢追高/追低）
    - ATR 動態止損止盈 + 通用追蹤止損（由 portfolio_manager 統一管理）
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

        # Bug #5：正確讀取三條 EMA 的周期
        ema_fast_period = self.params.get("ema_fast", 8)
        ema_mid_period  = self.params.get("ema_mid",  21)
        ema_slow_period = self.params.get("ema_slow", 55)
        min_bars = ema_slow_period + 10

        if len(closes) < min_bars:
            return Signal(direction=None, strength=0, reason="數據不足")

        # === 計算指標 ===
        ema_fast = Indicators.ema(closes, ema_fast_period)
        ema_mid  = Indicators.ema(closes, ema_mid_period)
        ema_slow = Indicators.ema(closes, ema_slow_period)
        atr      = Indicators.atr(highs, lows, closes, self.params.get("atr_period", 14))

        # Bug #21：實現 RSI 過濾
        rsi_period = self.params.get("rsi_period", 14)
        rsi = Indicators.rsi(closes, rsi_period)

        curr_price    = closes[-1]
        curr_ef       = ema_fast[-1]
        curr_em       = ema_mid[-1]
        curr_es       = ema_slow[-1]
        prev_ef       = ema_fast[-2]
        prev_em       = ema_mid[-2]
        curr_atr      = atr[-1]
        curr_rsi      = rsi[-1]

        rsi_filter_low  = self.params.get("rsi_filter_low",  35)
        rsi_filter_high = self.params.get("rsi_filter_high", 65)

        # === Bug #3：有持倉時只做策略特有退出判斷，sl/tp/trailing 由 PM 統一處理 ===
        if current_position is not None:
            min_hold = self.params.get("min_bars_hold", 2)
            if bars_held >= min_hold:
                # 三線排列反轉
                if current_position == "long" and curr_ef < curr_em:
                    return Signal(direction=None, strength=0.8, reason="EMA快線跌破中線反轉")
                elif current_position == "short" and curr_ef > curr_em:
                    return Signal(direction=None, strength=0.8, reason="EMA快線突破中線反轉")
            return Signal(direction=current_position, strength=0.5, reason="持倉中")

        # === 開倉信號 ===
        momentum_3 = (closes[-1] - closes[-4]) / closes[-4] * 100 if len(closes) >= 4 else 0.0

        # --- 做多信號 ---
        # 三條 EMA 多頭排列：ef > em > es
        full_bull = curr_ef > curr_em > curr_es
        # 金叉：ef 剛穿越 em
        golden_cross = prev_ef <= prev_em and curr_ef > curr_em
        # 趨勢加速：ef-em 差距擴大，且價格在 ef 之上
        trend_accel = (full_bull and
                       (curr_ef - curr_em) > (prev_ef - prev_em) and
                       curr_price > curr_ef)

        if golden_cross or (trend_accel and momentum_3 > 0.3):
            # RSI 過濾：多頭時 RSI 不應已超買
            if curr_rsi > rsi_filter_high:
                return Signal(direction=None, strength=0, reason=f"RSI={curr_rsi:.0f}超買，多頭過濾")
            strength = 0.0
            reasons = []
            if golden_cross:
                strength += 0.4; reasons.append("EMA金叉")
            elif trend_accel:
                strength += 0.3; reasons.append("三線多頭加速")
            if full_bull:
                strength += 0.1; reasons.append("三線多頭排列")
            if momentum_3 > 0.5:
                strength += 0.3; reasons.append("強動量")
            elif momentum_3 > 0.2:
                strength += 0.2; reasons.append("正動量")
            if strength >= 0.5:
                sl, tp = self.calc_sl_tp("long", curr_price, curr_atr)
                return Signal(
                    direction="long", strength=min(strength, 1.0),
                    reason=" + ".join(reasons), sl_price=sl, tp_price=tp,
                )

        # --- 做空信號 ---
        # 三條 EMA 空頭排列：ef < em < es
        full_bear = curr_ef < curr_em < curr_es
        # 死叉：ef 剛跌破 em
        death_cross = prev_ef >= prev_em and curr_ef < curr_em
        # 下跌加速
        trend_decel = (full_bear and
                       (curr_em - curr_ef) > (prev_em - prev_ef) and
                       curr_price < curr_ef)

        if death_cross or (trend_decel and momentum_3 < -0.3):
            # RSI 過濾：空頭時 RSI 不應已超賣
            if curr_rsi < rsi_filter_low:
                return Signal(direction=None, strength=0, reason=f"RSI={curr_rsi:.0f}超賣，空頭過濾")
            strength = 0.0
            reasons = []
            if death_cross:
                strength += 0.4; reasons.append("EMA死叉")
            elif trend_decel:
                strength += 0.3; reasons.append("三線空頭加速")
            if full_bear:
                strength += 0.1; reasons.append("三線空頭排列")
            if momentum_3 < -0.5:
                strength += 0.3; reasons.append("強負動量")
            elif momentum_3 < -0.2:
                strength += 0.2; reasons.append("負動量")
            if strength >= 0.5:
                sl, tp = self.calc_sl_tp("short", curr_price, curr_atr)
                return Signal(
                    direction="short", strength=min(strength, 1.0),
                    reason=" + ".join(reasons), sl_price=sl, tp_price=tp,
                )

        return Signal(direction=None, strength=0, reason="無動量信號")
