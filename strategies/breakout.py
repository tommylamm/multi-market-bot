"""
動量突破策略 (Momentum Breakout)
適用市場：SOL, SP500
邏輯：突破近期高低點 + 成交量爆發 + 美盤時段過濾
"""

import numpy as np
from typing import Optional
from datetime import datetime, timezone
from strategies.base import BaseStrategy, Signal, Indicators


class BreakoutStrategy(BaseStrategy):
    """
    動量突破策略
    - 價格突破近 N 根 K 線的最高/最低點
    - 成交量需要 > 平均的 1.5 倍（量能爆發）
    - 可選：僅在美盤時段（UTC 13:00-21:00）交易
    - 高盈虧比：止損窄（1 ATR），止盈寬（3 ATR）
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

        lookback = self.params.get("lookback_period", 48)
        min_bars = lookback + 5
        if len(closes) < min_bars:
            return Signal(direction=None, strength=0, reason="數據不足")

        # === 時段過濾 ===
        if self.params.get("session_filter", True):
            now_utc = datetime.now(timezone.utc)
            hour = now_utc.hour
            session_start = self.params.get("session_start_utc", 13)
            session_end = self.params.get("session_end_utc", 21)

            if session_start < session_end:
                in_session = session_start <= hour < session_end
            else:
                # 跨日（如 21:00 - 05:00）
                in_session = hour >= session_start or hour < session_end

            if not in_session and current_position is None:
                return Signal(direction=None, strength=0, reason="非交易時段")

        # === 計算指標 ===
        atr = Indicators.atr(highs, lows, closes, self.params.get("atr_period", 14))
        vol_sma = Indicators.volume_sma(volumes, 20)

        curr_price = closes[-1]
        curr_high = highs[-1]
        curr_low = lows[-1]
        curr_atr = atr[-1]
        curr_vol = volumes[-1]
        avg_vol = vol_sma[-1] if not np.isnan(vol_sma[-1]) else volumes[-1]

        # 近期高低點（不包含當前 K 線）
        recent_high = np.max(highs[-lookback - 1:-1])
        recent_low = np.min(lows[-lookback - 1:-1])

        # === 如果有持倉，檢查是否需要平倉 ===
        if current_position is not None:
            close_reason = self._check_exit(
                current_position, entry_price, curr_price,
                curr_atr, bars_held,
            )
            if close_reason:
                return Signal(
                    direction=None, strength=0.8,
                    reason=close_reason,
                )
            return Signal(direction=current_position, strength=0.5, reason="持倉中")

        # === 開倉信號 ===
        breakout_mult = self.params.get("breakout_atr_mult", 1.0)
        vol_spike_mult = self.params.get("volume_spike_mult", 1.5)

        # 成交量爆發確認
        vol_spike = curr_vol > avg_vol * vol_spike_mult

        # === 向上突破 ===
        breakout_level_up = recent_high + breakout_mult * curr_atr
        if curr_price > breakout_level_up:
            strength = 0.0
            reasons = []

            # 突破幅度
            breakout_pct = (curr_price - recent_high) / recent_high * 100
            strength += min(0.4, breakout_pct / 2)
            reasons.append(f"突破前高{breakout_pct:.1f}%")

            # 成交量確認
            if vol_spike:
                strength += 0.3
                reasons.append(f"量能爆發({curr_vol/avg_vol:.1f}x)")
            else:
                strength += 0.1
                reasons.append("量能一般")

            # K 線實體強度（收盤接近最高點）
            body_ratio = (curr_price - lows[-1]) / (highs[-1] - lows[-1] + 1e-10)
            if body_ratio > 0.7:
                strength += 0.2
                reasons.append("強勢收盤")

            if strength >= 0.5:
                sl_mult = self.params.get("atr_sl_mult", 1.0)
                tp_mult = self.params.get("atr_tp_mult", 3.0)
                sl = curr_price - sl_mult * curr_atr
                tp = curr_price + tp_mult * curr_atr

                return Signal(
                    direction="long", strength=min(strength, 1.0),
                    reason=" + ".join(reasons),
                    sl_price=sl, tp_price=tp,
                )

        # === 向下突破 ===
        breakout_level_down = recent_low - breakout_mult * curr_atr
        if curr_price < breakout_level_down:
            strength = 0.0
            reasons = []

            breakout_pct = (recent_low - curr_price) / recent_low * 100
            strength += min(0.4, breakout_pct / 2)
            reasons.append(f"跌破前低{breakout_pct:.1f}%")

            if vol_spike:
                strength += 0.3
                reasons.append(f"量能爆發({curr_vol/avg_vol:.1f}x)")
            else:
                strength += 0.1
                reasons.append("量能一般")

            body_ratio = (highs[-1] - curr_price) / (highs[-1] - lows[-1] + 1e-10)
            if body_ratio > 0.7:
                strength += 0.2
                reasons.append("弱勢收盤")

            if strength >= 0.5:
                sl_mult = self.params.get("atr_sl_mult", 1.0)
                tp_mult = self.params.get("atr_tp_mult", 3.0)
                sl = curr_price + sl_mult * curr_atr
                tp = curr_price - tp_mult * curr_atr

                return Signal(
                    direction="short", strength=min(strength, 1.0),
                    reason=" + ".join(reasons),
                    sl_price=sl, tp_price=tp,
                )

        return Signal(direction=None, strength=0, reason="無突破")

    def _check_exit(
        self,
        position: str,
        entry_price: float,
        current_price: float,
        atr: float,
        bars_held: int,
    ) -> Optional[str]:
        """檢查是否應該平倉"""

        sl_mult = self.params.get("atr_sl_mult", 1.0)
        tp_mult = self.params.get("atr_tp_mult", 3.0)

        # 止損
        if position == "long":
            sl = entry_price - sl_mult * atr
            if current_price <= sl:
                return f"止損 @{sl:.2f}"
        elif position == "short":
            sl = entry_price + sl_mult * atr
            if current_price >= sl:
                return f"止損 @{sl:.2f}"

        # 止盈
        if position == "long":
            tp = entry_price + tp_mult * atr
            if current_price >= tp:
                return f"止盈 @{tp:.2f}"
        elif position == "short":
            tp = entry_price - tp_mult * atr
            if current_price <= tp:
                return f"止盈 @{tp:.2f}"

        # 最大持倉時間
        max_hold = self.params.get("max_bars_hold", 40)
        if bars_held >= max_hold:
            return f"超時平倉 ({bars_held} bars)"

        # 突破失敗：價格回到突破點以下
        min_hold = self.params.get("min_bars_hold", 2)
        if bars_held >= min_hold:
            pnl_pct = 0
            if position == "long":
                pnl_pct = (current_price - entry_price) / entry_price
            else:
                pnl_pct = (entry_price - current_price) / entry_price

            # 如果持倉超過 min_hold 但仍然虧損，可能是假突破
            if pnl_pct < -0.002:  # 虧損超過 0.2%
                return "假突破，止損出場"

        return None
