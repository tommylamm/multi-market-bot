"""
智能出場模組 — 基於走勢分析的動態止盈/止損
v1.0
"""

import numpy as np
from typing import Optional, Dict, List


class ExitSignal:
    """出場信號"""
    def __init__(self, should_exit: bool, reason: str = "", urgency: str = "normal"):
        self.should_exit = should_exit
        self.reason = reason
        self.urgency = urgency


class SmartExit:
    """智能出場引擎"""

    def __init__(self, config: dict = None):
        cfg = config or {}
        self.ema_fast = cfg.get("ema_fast", 8)
        self.ema_slow = cfg.get("ema_slow", 21)
        self.rsi_period = cfg.get("rsi_period", 14)
        self.rsi_overbought = cfg.get("rsi_overbought", 70)
        self.rsi_oversold = cfg.get("rsi_oversold", 30)
        self.rsi_reversal_threshold = cfg.get("rsi_reversal_threshold", 5)
        self.trailing_activate_pct = cfg.get("trailing_activate_pct", 0.8)
        self.trailing_callback_pct = cfg.get("trailing_callback_pct", 0.6)
        self.ema_exit_min_profit_pct = cfg.get("ema_exit_min_profit_pct", 0.3)
        self.max_loss_pct = cfg.get("max_loss_pct", 5.0)
        self.peak_prices: Dict[str, float] = {}

    def _calc_ema(self, prices: List[float], period: int) -> float:
        if len(prices) < period:
            return prices[-1] if prices else 0
        multiplier = 2 / (period + 1)
        ema = prices[0]
        for price in prices[1:]:
            ema = (price - ema) * multiplier + ema
        return ema

    def _calc_rsi(self, prices: List[float], period: int = 14) -> List[float]:
        if len(prices) < period + 1:
            return [50.0]
        gains = []
        losses = []
        for i in range(1, len(prices)):
            change = prices[i] - prices[i-1]
            gains.append(max(change, 0))
            losses.append(max(-change, 0))
        if len(gains) < period:
            return [50.0]
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        rsi_values = []
        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            if avg_loss == 0:
                rsi_values.append(100.0)
            else:
                rs = avg_gain / avg_loss
                rsi_values.append(100 - (100 / (1 + rs)))
        return rsi_values if rsi_values else [50.0]

    def _find_support_resistance(self, highs: List[float], lows: List[float],
                                  closes: List[float]) -> Dict[str, float]:
        if len(closes) < 20:
            return {"support": 0, "resistance": float('inf')}
        recent_highs = highs[-20:]
        recent_lows = lows[-20:]
        current_price = closes[-1]
        resistance_candidates = [h for h in recent_highs if h > current_price * 1.001]
        resistance = min(resistance_candidates) if resistance_candidates else current_price * 1.05
        support_candidates = [l for l in recent_lows if l < current_price * 0.999]
        support = max(support_candidates) if support_candidates else current_price * 0.95
        return {"support": support, "resistance": resistance}

    def check_exit(self, market_id: str, position: dict,
                   candle_closes: List[float],
                   candle_highs: List[float] = None,
                   candle_lows: List[float] = None,
                   current_price: float = None) -> ExitSignal:
        if not candle_closes or len(candle_closes) < 5:
            return ExitSignal(False, "數據不足")
        direction = position.get("direction", "")
        entry_price = position.get("entry_price", 0)
        if not direction or entry_price <= 0:
            return ExitSignal(False, "持倉信息不完整")
        price = current_price or candle_closes[-1]
        if direction == "long":
            pnl_pct = (price - entry_price) / entry_price * 100
        else:
            pnl_pct = (entry_price - price) / entry_price * 100

        # 1. 安全網止損
        if pnl_pct <= -self.max_loss_pct:
            return ExitSignal(True, f"安全網止損: 虧損{pnl_pct:.1f}%", "emergency")

        # 2. 增強追蹤止損
        trailing_signal = self._check_trailing_stop(market_id, direction, price, entry_price, pnl_pct)
        if trailing_signal.should_exit:
            return trailing_signal

        # 3. EMA 動態止損（盈利時才啟用）
        if pnl_pct >= self.ema_exit_min_profit_pct:
            ema_signal = self._check_ema_exit(direction, candle_closes, price)
            if ema_signal.should_exit:
                return ema_signal

        # 4. RSI 動量止盈
        rsi_signal = self._check_rsi_exit(direction, candle_closes, pnl_pct)
        if rsi_signal.should_exit:
            return rsi_signal

        # 5. 支撐/阻力位止盈
        if False:  # 禁用支撐/阻力位止盈（太敏感）
            sr_signal = self._check_sr_exit(direction, price, entry_price,
                                            candle_highs, candle_lows, candle_closes)
            if sr_signal.should_exit:
                return sr_signal

        return ExitSignal(False, f"持倉中 PnL={pnl_pct:+.2f}%")

    def _check_trailing_stop(self, market_id, direction, price, entry_price, pnl_pct):
        if market_id not in self.peak_prices:
            self.peak_prices[market_id] = price
        if direction == "long":
            self.peak_prices[market_id] = max(self.peak_prices[market_id], price)
            peak = self.peak_prices[market_id]
            peak_pnl = (peak - entry_price) / entry_price * 100
        else:
            self.peak_prices[market_id] = min(self.peak_prices[market_id], price)
            peak = self.peak_prices[market_id]
            peak_pnl = (entry_price - peak) / entry_price * 100
        if peak_pnl < self.trailing_activate_pct:
            return ExitSignal(False)
        if direction == "long":
            drawdown = (peak - price) / peak * 100
        else:
            drawdown = (price - peak) / peak * 100
        if drawdown >= self.trailing_callback_pct:
            self.peak_prices.pop(market_id, None)
            return ExitSignal(True, f"追蹤止損: 峰值盈利{peak_pnl:.1f}%, 回撤{drawdown:.1f}%", "normal")
        return ExitSignal(False)

    def _check_ema_exit(self, direction, closes, current_price):
        if len(closes) < self.ema_slow + 5:
            return ExitSignal(False)
        ema21 = self._calc_ema(closes, self.ema_slow)
        ema8 = self._calc_ema(closes, self.ema_fast)
        if direction == "long":
            if current_price < ema21 and ema8 < ema21:
                return ExitSignal(True, f"EMA止損: 價格{current_price:.1f} < EMA21={ema21:.1f}", "normal")
        else:
            if current_price > ema21 and ema8 > ema21:
                return ExitSignal(True, f"EMA止損: 價格{current_price:.1f} > EMA21={ema21:.1f}", "normal")
        return ExitSignal(False)

    def _check_rsi_exit(self, direction, closes, pnl_pct):
        if len(closes) < self.rsi_period + 5:
            return ExitSignal(False)
        if pnl_pct < 0.5:
            return ExitSignal(False)
        rsi_values = self._calc_rsi(closes, self.rsi_period)
        if len(rsi_values) < 3:
            return ExitSignal(False)
        current_rsi = rsi_values[-1]
        prev_rsi = rsi_values[-2]
        prev2_rsi = rsi_values[-3]
        if direction == "long":
            peak_rsi = max(rsi_values[-5:]) if len(rsi_values) >= 5 else max(rsi_values)
            if (peak_rsi >= self.rsi_overbought and
                current_rsi < prev_rsi and prev_rsi < prev2_rsi and
                peak_rsi - current_rsi >= self.rsi_reversal_threshold):
                return ExitSignal(True, f"RSI止盈: 峰值{peak_rsi:.0f}→{current_rsi:.0f}", "normal")
        else:
            trough_rsi = min(rsi_values[-5:]) if len(rsi_values) >= 5 else min(rsi_values)
            if (trough_rsi <= self.rsi_oversold and
                current_rsi > prev_rsi and prev_rsi > prev2_rsi and
                current_rsi - trough_rsi >= self.rsi_reversal_threshold):
                return ExitSignal(True, f"RSI止盈: 谷值{trough_rsi:.0f}→{current_rsi:.0f}", "normal")
        return ExitSignal(False)

    def _check_sr_exit(self, direction, price, entry_price, highs, lows, closes):
        sr = self._find_support_resistance(highs, lows, closes)
        if direction == "long":
            resistance = sr["resistance"]
            if resistance > 0 and price > entry_price:
                dist = (resistance - price) / price * 100
                if 0 > dist > -0.1 or 0 < dist < 0.3:
                    return ExitSignal(True, f"阻力位止盈: 價格{price:.1f}≈阻力{resistance:.1f}", "normal")
        else:
            support = sr["support"]
            if support > 0 and price < entry_price:
                dist = (price - support) / price * 100
                if 0 > dist > -0.1 or 0 < dist < 0.3:
                    return ExitSignal(True, f"支撐位止盈: 價格{price:.1f}≈支撐{support:.1f}", "normal")
        return ExitSignal(False)

    def reset_market(self, market_id: str):
        self.peak_prices.pop(market_id, None)
