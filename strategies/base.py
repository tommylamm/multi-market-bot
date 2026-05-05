"""
策略基類與技術指標計算工具
所有策略都繼承 BaseStrategy，並實現 generate_signal() 方法
"""

import numpy as np
from dataclasses import dataclass
from typing import Optional
from datetime import datetime, timezone


@dataclass
class Signal:
    """交易信號"""
    direction: Optional[str]  # "long" / "short" / None
    strength: float           # 信號強度 0~1
    reason: str               # 信號原因
    sl_price: float = 0.0     # 建議止損價
    tp_price: float = 0.0     # 建議止盈價


class Indicators:
    """技術指標計算工具（純 NumPy 實現，無外部依賴）"""

    @staticmethod
    def ema(data: np.ndarray, period: int) -> np.ndarray:
        """指數移動平均線"""
        if len(data) < period:
            return np.full_like(data, np.nan)
        alpha = 2.0 / (period + 1)
        result = np.empty_like(data)
        result[:period - 1] = np.nan
        result[period - 1] = np.mean(data[:period])
        for i in range(period, len(data)):
            result[i] = alpha * data[i] + (1 - alpha) * result[i - 1]
        return result

    @staticmethod
    def sma(data: np.ndarray, period: int) -> np.ndarray:
        """簡單移動平均線"""
        if len(data) < period:
            return np.full_like(data, np.nan)
        result = np.full_like(data, np.nan)
        cumsum = np.cumsum(data)
        result[period - 1:] = (cumsum[period - 1:] - np.concatenate([[0], cumsum[:-period]])) / period
        return result

    @staticmethod
    def rsi(data: np.ndarray, period: int = 14) -> np.ndarray:
        """相對強弱指標"""
        if len(data) < period + 1:
            return np.full_like(data, 50.0)
        delta = np.diff(data)
        gain = np.where(delta > 0, delta, 0.0)
        loss = np.where(delta < 0, -delta, 0.0)

        result = np.full(len(data), 50.0)

        avg_gain = np.mean(gain[:period])
        avg_loss = np.mean(loss[:period])

        for i in range(period, len(delta)):
            avg_gain = (avg_gain * (period - 1) + gain[i]) / period
            avg_loss = (avg_loss * (period - 1) + loss[i]) / period
            if avg_loss == 0:
                result[i + 1] = 100.0
            else:
                rs = avg_gain / avg_loss
                result[i + 1] = 100.0 - 100.0 / (1.0 + rs)

        return result

    @staticmethod
    def bollinger_bands(data: np.ndarray, period: int = 20, std_mult: float = 2.0):
        """布林通道 → (upper, middle, lower)"""
        middle = Indicators.sma(data, period)
        if len(data) < period:
            nan_arr = np.full_like(data, np.nan)
            return nan_arr, nan_arr, nan_arr

        std = np.full_like(data, np.nan)
        for i in range(period - 1, len(data)):
            std[i] = np.std(data[i - period + 1:i + 1])

        upper = middle + std_mult * std
        lower = middle - std_mult * std
        return upper, lower, middle

    @staticmethod
    def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray,
            period: int = 14) -> np.ndarray:
        """平均真實波幅"""
        if len(high) < 2:
            return np.full_like(high, 0.0)

        tr = np.zeros(len(high))
        tr[0] = high[0] - low[0]
        for i in range(1, len(high)):
            tr[i] = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1]),
            )

        result = np.full_like(high, 0.0)
        if len(tr) >= period:
            result[period - 1] = np.mean(tr[:period])
            for i in range(period, len(tr)):
                result[i] = (result[i - 1] * (period - 1) + tr[i]) / period
        return result

    @staticmethod
    def macd(data: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9):
        """MACD → (macd_line, signal_line, histogram)"""
        ema_fast = Indicators.ema(data, fast)
        ema_slow = Indicators.ema(data, slow)
        macd_line = ema_fast - ema_slow
        signal_line = Indicators.ema(
            np.nan_to_num(macd_line, nan=0.0), signal
        )
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    @staticmethod
    def volume_sma(volumes: np.ndarray, period: int = 20) -> np.ndarray:
        """成交量移動平均"""
        return Indicators.sma(volumes, period)


class BaseStrategy:
    """策略基類"""

    def __init__(self, market_id: str, params: dict):
        self.market_id = market_id
        self.params = params
        self.bar_count = 0
        self.last_signal: Optional[Signal] = None
        self.trailing_stop_price = 0.0  # 當前追蹤止損價格

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
        """
        生成交易信號（子類必須實現）
        返回 Signal 對象
        """
        raise NotImplementedError

    def should_close(
        self,
        current_position: str,
        entry_price: float,
        current_price: float,
        sl_price: float,
        tp_price: float,
        bars_held: int,
        atr_value: float,
    ) -> Optional[str]:
        """
        判斷是否應該平倉
        返回平倉原因字串，或 None 表示不平倉
        """
        # 1. 檢查追蹤止損
        if self.trailing_stop_price > 0:
            if current_position == "long" and current_price <= self.trailing_stop_price:
                return f"追蹤止損 @{self.trailing_stop_price:.2f}"
            if current_position == "short" and current_price >= self.trailing_stop_price:
                return f"追蹤止損 @{self.trailing_stop_price:.2f}"

        # 2. 止損
        if current_position == "long" and current_price <= sl_price:
            return f"止損 @{sl_price:.2f}"
        if current_position == "short" and current_price >= sl_price:
            return f"止損 @{sl_price:.2f}"

        # 3. 止盈
        if current_position == "long" and current_price >= tp_price:
            return f"止盈 @{tp_price:.2f}"
        if current_position == "short" and current_price <= tp_price:
            return f"止盈 @{tp_price:.2f}"

        # 4. 最大持倉時間
        max_hold = self.params.get("max_bars_hold", 60)
        if bars_held >= max_hold:
            return f"超時平倉 ({bars_held} bars)"

        # 5. 更新追蹤止損
        self._update_trailing_stop(current_position, entry_price, current_price, atr_value)

        return None

    def _update_trailing_stop(self, position: str, entry_price: float, current_price: float, atr: float):
        """
        通用追蹤止損邏輯 v2.4
        當利潤達到 activation_atr * ATR 後，啟用追蹤止損，追蹤距離為 trail_atr * ATR
        """
        activation_atr = self.params.get("tsl_activation_atr", 1.5)
        trail_atr = self.params.get("tsl_distance_atr", 1.5)

        if position == "long":
            profit_atr = (current_price - entry_price) / atr if atr > 0 else 0
            if profit_atr >= activation_atr:
                new_stop = current_price - trail_atr * atr
                if new_stop > self.trailing_stop_price:
                    self.trailing_stop_price = new_stop
        elif position == "short":
            profit_atr = (entry_price - current_price) / atr if atr > 0 else 0
            if profit_atr >= activation_atr:
                new_stop = current_price + trail_atr * atr
                if self.trailing_stop_price <= 0 or new_stop < self.trailing_stop_price:
                    self.trailing_stop_price = new_stop

    def calc_sl_tp(
        self,
        direction: str,
        entry_price: float,
        atr_value: float,
    ) -> tuple:
        """計算止損和止盈價格"""
        sl_mult = self.params.get("atr_sl_mult", 1.5)
        tp_mult = self.params.get("atr_tp_mult", 3.0)

        if direction == "long":
            sl = entry_price - sl_mult * atr_value
            tp = entry_price + tp_mult * atr_value
        else:
            sl = entry_price + sl_mult * atr_value
            tp = entry_price - tp_mult * atr_value

        return sl, tp
