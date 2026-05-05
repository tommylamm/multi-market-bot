"""
EMA 動量策略 (EMA Momentum)
核心：EMA 交叉 + 價格動量 (Momentum) + RSI 過濾
"""

import numpy as np
from typing import Optional
from strategies.base import BaseStrategy, Indicators, Signal


class EMAMomentumStrategy(BaseStrategy):
    """
    EMA 動量策略
    - 使用短週期 EMA 交叉
    - 加上 K 線動量確認
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
        ema_fast_period = self.params.get("ema_fast", 9)
        ema_slow_period = self.params.get("ema_slow", 21)
        min_bars = ema_slow_period + 10

        if len(closes) < min_bars:
            return Signal(direction=None, strength=0, reason="數據不足")

        # === 計算指標 ===
        ema_fast = Indicators.ema(closes, ema_fast_period)
        ema_slow = Indicators.ema(closes, ema_slow_period)
        atr = Indicators.atr(highs, lows, closes, self.params.get("atr_period", 14))

        curr_price = closes[-1]
        curr_ema_fast = ema_fast[-1]
        curr_ema_slow = ema_slow[-1]
        prev_ema_fast = ema_fast[-2]
        prev_ema_slow = ema_slow[-2]
        curr_atr = atr[-1]

        # === 如果有持倉，檢查是否需要平倉 ===
        if current_position is not None:
            sl, tp = self.calc_sl_tp(current_position, entry_price, curr_atr)
            
            # 1. 檢查基類的通用止盈止損 (包含追蹤止損)
            close_reason = self.should_close(
                current_position, entry_price, curr_price,
                sl, tp, bars_held, curr_atr
            )
            
            # 2. 額外檢查：EMA 反轉
            if not close_reason:
                min_hold = self.params.get("min_bars_hold", 3)
                if bars_held >= min_hold:
                    if current_position == "long" and curr_ema_fast < curr_ema_slow:
                        close_reason = "EMA反轉平倉"
                    elif current_position == "short" and curr_ema_fast > curr_ema_slow:
                        close_reason = "EMA反轉平倉"

            if close_reason:
                return Signal(direction=None, strength=0.8, reason=close_reason)
                
            return Signal(direction=current_position, strength=0.5, reason="持倉中")

        # === 開倉信號 ===
        momentum_3 = (closes[-1] - closes[-4]) / closes[-4] * 100 if len(closes) >= 4 else 0

        # 做多信號
        golden_cross = prev_ema_fast <= prev_ema_slow and curr_ema_fast > curr_ema_slow
        trend_accel = (curr_ema_fast > curr_ema_slow and
                      (curr_ema_fast - curr_ema_slow) > (prev_ema_fast - prev_ema_slow) and
                      curr_price > curr_ema_fast)

        if golden_cross or (trend_accel and momentum_3 > 0.3):
            strength = 0.0
            reasons = []
            if golden_cross: strength += 0.4; reasons.append("EMA金叉")
            elif trend_accel: strength += 0.3; reasons.append("趨勢加速")
            
            if momentum_3 > 0.5: strength += 0.3; reasons.append("強動量")
            elif momentum_3 > 0.2: strength += 0.2; reasons.append("正動量")
            
            if strength >= 0.5:
                sl, tp = self.calc_sl_tp("long", curr_price, curr_atr)
                return Signal(direction="long", strength=min(strength, 1.0), reason=" + ".join(reasons), sl_price=sl, tp_price=tp)

        # 做空信號
        death_cross = prev_ema_fast >= prev_ema_slow and curr_ema_fast < curr_ema_slow
        trend_decel = (curr_ema_fast < curr_ema_slow and
                      (curr_ema_slow - curr_ema_fast) > (prev_ema_slow - prev_ema_fast) and
                      curr_price < curr_ema_fast)

        if death_cross or (trend_decel and momentum_3 < -0.3):
            strength = 0.0
            reasons = []
            if death_cross: strength += 0.4; reasons.append("EMA死叉")
            elif trend_decel: strength += 0.3; reasons.append("下跌加速")
            
            if momentum_3 < -0.5: strength += 0.3; reasons.append("強負動量")
            elif momentum_3 < -0.2: strength += 0.2; reasons.append("負動量")
            
            if strength >= 0.5:
                sl, tp = self.calc_sl_tp("short", curr_price, curr_atr)
                return Signal(direction="short", strength=min(strength, 1.0), reason=" + ".join(reasons), sl_price=sl, tp_price=tp)

        return Signal(direction=None, strength=0, reason="無動量信號")
