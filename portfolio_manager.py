"""
中央調度器 (Portfolio Manager) v2.0
新增功能：自適應策略切換
負責：
  1. 協調多市場多策略的信號與執行
  2. 全局風險管理（每日虧損熔斷、單策略暫停）
  3. 持倉狀態追蹤與統計報告
  4. 自適應策略切換（根據績效自動選擇最佳策略）
"""

import time
from price_monitor import PriceMonitor
from position_sync import PositionSync
import json
import os
from datetime import datetime, timezone
from typing import Dict, Optional

import numpy as np

from config import (
    MARKETS, STRATEGY_PARAMS, TOTAL_CAPITAL,
    DAILY_LOSS_LIMIT, MAX_CONSECUTIVE_LOSSES,
    CIRCUIT_BREAKER_COOLDOWN, LOG_DIR,
)
from data_feed import MultiMarketFeed, CandleBuffer
from executor import MultiMarketExecutor
from strategies.base import Indicators
from strategy_selector_v2 import AdaptiveStrategySelector
from telegram_notifier import (
    notify_circuit_breaker, notify_market_paused,
    notify_system_start,
)


class MTFFilter:
    """多時間框架趨勢過濾器"""

    def __init__(self, ema_fast: int = 20, ema_slow: int = 50):
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow

    def synthesize_4h_from_1h(self, closes_1h, highs_1h, lows_1h, volumes_1h):
        """從 1h K線合成 4h K線"""
        n = len(closes_1h)
        remainder = n % 4
        if remainder > 0:
            closes_1h = closes_1h[remainder:]
            highs_1h = highs_1h[remainder:]
            lows_1h = lows_1h[remainder:]
            volumes_1h = volumes_1h[remainder:]
        n = len(closes_1h)
        n_4h = n // 4
        if n_4h < 2:
            return np.array([]), np.array([]), np.array([]), np.array([])
        closes_4h = np.zeros(n_4h)
        highs_4h = np.zeros(n_4h)
        lows_4h = np.zeros(n_4h)
        volumes_4h = np.zeros(n_4h)
        for i in range(n_4h):
            start = i * 4
            end = start + 4
            closes_4h[i] = closes_1h[end - 1]
            highs_4h[i] = np.max(highs_1h[start:end])
            lows_4h[i] = np.min(lows_1h[start:end])
            volumes_4h[i] = np.sum(volumes_1h[start:end])
        return closes_4h, highs_4h, lows_4h, volumes_4h

    def get_higher_tf_trend(self, closes_1h, highs_1h, lows_1h, volumes_1h):
        """獲取 4h 趨勢方向"""
        closes_4h, highs_4h, lows_4h, volumes_4h = self.synthesize_4h_from_1h(
            closes_1h, highs_1h, lows_1h, volumes_1h
        )
        min_required = max(self.ema_fast, self.ema_slow) + 5
        if len(closes_4h) < min_required:
            return None, 0.0, "4h數據不足"
        ema_fast = Indicators.ema(closes_4h, self.ema_fast)
        ema_slow = Indicators.ema(closes_4h, self.ema_slow)
        macd_line, signal_line, histogram = Indicators.macd(closes_4h)
        current_ema_fast = ema_fast[-1]
        current_ema_slow = ema_slow[-1]
        current_histogram = histogram[-1]
        current_close = closes_4h[-1]
        if any(np.isnan(x) for x in [current_ema_fast, current_ema_slow, current_histogram]):
            return None, 0.0, "指標計算中"
        ema_bullish = current_ema_fast > current_ema_slow
        macd_bullish = current_histogram > 0
        price_above_slow = current_close > current_ema_slow
        ema_diff_pct = abs(current_ema_fast - current_ema_slow) / current_ema_slow if current_ema_slow > 0 else 0
        bull_score = sum([ema_bullish, macd_bullish, price_above_slow])
        bear_score = sum([not ema_bullish, not macd_bullish, not price_above_slow])
        if bull_score >= 2:
            strength = min(1.0, ema_diff_pct * 100 + 0.3 * bull_score)
            return "long", strength, "4h多頭"
        elif bear_score >= 2:
            strength = min(1.0, ema_diff_pct * 100 + 0.3 * bear_score)
            return "short", strength, "4h空頭"
        else:
            return None, 0.0, "4h震盪"

    def should_allow_signal(self, signal_direction, closes_1h, highs_1h, lows_1h,
                            volumes_1h, strategy_type="trend"):
        """判斷信號是否與 4h 趨勢一致"""
        if signal_direction is None:
            return True, "無信號"
        if strategy_type in ("bollinger_reversion", "mean_reversion", "vwap_reversion"):
            return True, "MTF跳過(均值回歸)"
        trend_dir, trend_strength, trend_reason = self.get_higher_tf_trend(
            closes_1h, highs_1h, lows_1h, volumes_1h
        )
        if trend_dir is None:
            return True, f"MTF通過(4h無趨勢)"
        if signal_direction == trend_dir:
            return True, f"MTF通過({signal_direction}與{trend_reason}一致)"
        return False, f"MTF阻止({signal_direction}與{trend_reason}衝突)"


class RiskManager:
    """全局風險管理器"""

    def __init__(self):
        self.daily_pnl: float = 0.0
        self.daily_start_time: float = time.time()
        self.circuit_breaker_active: bool = False
        self.circuit_breaker_until: float = 0.0
        self.paused_markets: Dict[str, float] = {}

    def reset_daily(self):
        self.daily_pnl = 0.0
        self.daily_start_time = time.time()
        print("  [RISK] 每日計數器已重置")

    def record_pnl(self, pnl: float, market_id: str):
        self.daily_pnl += pnl

    def check_daily_limit(self) -> bool:
        if self.daily_pnl <= -DAILY_LOSS_LIMIT:
            if not self.circuit_breaker_active:
                self.circuit_breaker_active = True
                self.circuit_breaker_until = time.time() + CIRCUIT_BREAKER_COOLDOWN
                print(
                    f"  [RISK] ⚠️ 每日虧損熔斷！"
                    f"日虧=${self.daily_pnl:.2f} >= 上限=${DAILY_LOSS_LIMIT:.2f}"
                )
                notify_circuit_breaker("triggered", self.daily_pnl, DAILY_LOSS_LIMIT)
            return True
        return False

    def check_market_pause(self, market_id: str, consecutive_losses: int) -> bool:
        now = time.time()
        if market_id in self.paused_markets:
            if now < self.paused_markets[market_id]:
                return True
            else:
                del self.paused_markets[market_id]
                print(f"  [RISK] {market_id} 暫停期結束，恢復交易")
                return False

        if consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
            pause_until = now + CIRCUIT_BREAKER_COOLDOWN
            self.paused_markets[market_id] = pause_until
            print(
                f"  [RISK] ⚠️ {market_id} 連續虧損 {consecutive_losses} 次，"
                f"暫停 {CIRCUIT_BREAKER_COOLDOWN//60} 分鐘"
            )
            notify_market_paused(market_id, consecutive_losses, CIRCUIT_BREAKER_COOLDOWN // 60)
            return True
        return False

    def is_trading_allowed(self, market_id: str = None) -> bool:
        now = time.time()
        if self.circuit_breaker_active:
            if now >= self.circuit_breaker_until:
                self.circuit_breaker_active = False
                print("  [RISK] 全局熔斷解除")
                notify_circuit_breaker("released", 0, 0)
            else:
                return False

        now_utc = datetime.now(timezone.utc)
        day_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        if self.daily_start_time < day_start.timestamp():
            self.reset_daily()

        if market_id and market_id in self.paused_markets:
            if now < self.paused_markets[market_id]:
                return False
        return True


class PortfolioManager:
    """中央調度器 — 協調多市場多策略（含自適應切換）"""

    def __init__(self):
        self.feed = MultiMarketFeed()
        self.executor = MultiMarketExecutor()
        self.risk = RiskManager()
        self.positions: Dict[str, dict] = {}

        # === 自適應策略選擇器 ===
        selector_configs = {}
        for market_id, cfg in MARKETS.items():
            strategies_list = cfg.get("strategies", [cfg["strategy"]])
            default_strategy = cfg.get("default_strategy", strategies_list[0])

            strat_params = {}
            for strat_name in strategies_list:
                strat_params[strat_name] = STRATEGY_PARAMS.get(strat_name, {})

            selector_configs[market_id] = {
                "strategies": strategies_list,
                "default": default_strategy,
                "strategy_params": strat_params,
            }

        self.selector = AdaptiveStrategySelector(selector_configs)

        # 初始化持倉狀態
        for market_id in MARKETS:
            self.positions[market_id] = {
                "direction": None,
                "entry_price": 0.0,
                "sl_price": 0.0,
                "tp_price": 0.0,
                "bars_held": 0,
                "entry_bar": 0,
            }

        # 註冊 K 線回調
        self.feed.on_candle_close(self.on_candle_close)

        # 統計
        self.total_signals = 0
        self.total_trades = 0
        self.start_time = time.time()
        # MTF 多時間框架過濾器
        self.mtf_filter = MTFFilter(ema_fast=20, ema_slow=50)
        self.mtf_enabled = True

        # === 持倉同步：從交易所恢復持倉 ===
        try:
            sync = PositionSync()
            sync.sync_positions(self.positions, STRATEGY_PARAMS)
        except Exception as e:
            print(f"  [PositionSync] 同步異常: {e}")

        # === 高頻價格監控：每30秒檢查止損/止盈 ===
        self.price_monitor = PriceMonitor(
            positions=self.positions,
            close_callback=self._emergency_close,
            check_interval=5,
        )



    def start_price_monitor(self):
        """啟動高頻價格監控"""
        self.price_monitor.start()

    async def _emergency_close(self, market_id: str, reason: str):
        """PriceMonitor 觸發的緊急平倉回調"""
        print(f"  [EmergencyClose] {market_id}: {reason}")
        await self._close_position(market_id, reason)

    async def on_candle_close(
        self, market_id: str, candle: dict, buf: CandleBuffer
    ):
        """K 線收盤回調 — 核心交易邏輯"""
        if not self.risk.is_trading_allowed(market_id):
            return

        # 獲取當前活躍策略
        strategy = self.selector.get_active_strategy(market_id)
        if not strategy:
            return

        closes = buf.get_closes()
        highs = buf.get_highs()
        lows = buf.get_lows()
        volumes = buf.get_volumes()

        if len(closes) < 30:
            return

        pos = self.positions[market_id]
        current_position = pos["direction"]
        entry_price = pos["entry_price"]
        bars_held = pos["bars_held"]

        # Bug #4 修復：先記錄當前持倉 bars，再遞增
        if current_position is not None:
            pos["bars_held"] += 1
            bars_held = pos["bars_held"]  # 使用遞增後的值

        if current_position is None:
            self.selector.scan_and_update(market_id, closes, highs, lows, volumes)
            strategy = self.selector.get_active_strategy(market_id)
        # === 生成信號 ===
        signal = strategy.generate_signal(
            closes, highs, lows, volumes,
            current_position, entry_price, bars_held,
        )
        self.total_signals += 1

        # === 檢查是否應該平倉（追蹤止損/止損/止盈/超時）===
        # Bug #3 修復：此處是唯一呼叫 should_close() 的地方
        if current_position is not None:
            atr_arr = Indicators.atr(highs, lows, closes)
            curr_atr = atr_arr[-1] if len(atr_arr) > 0 and not __import__("numpy").isnan(atr_arr[-1]) else 0.0
            close_reason = strategy.should_close(
                current_position=current_position,
                entry_price=entry_price,
                current_price=closes[-1],
                sl_price=pos.get("sl_price", 0.0),
                tp_price=pos.get("tp_price", 0.0),
                bars_held=bars_held,
                atr_value=curr_atr,
            )
            if close_reason:
                await self._close_position(market_id, close_reason)
                return

        # === MTF 多時間框架過濾 ===
        if self.mtf_enabled and signal.direction is not None and current_position is None:
            # Bug #18 修復：使用當前活躍策略名，而非配置中的靜態策略名
            active_strat_name = self.selector.get_active_strategy_name(market_id)
            mtf_allowed, mtf_reason = self.mtf_filter.should_allow_signal(
                signal.direction, closes, highs, lows, volumes, active_strat_name
            )
            if not mtf_allowed:
                print(f"    [{market_id}] {mtf_reason}")
                from strategies.base import Signal
                signal = Signal(direction=None, strength=0, reason=mtf_reason)

        # === 處理信號 ===
        if current_position is not None:
            if signal.direction is None and signal.strength > 0.5:
                await self._close_position(market_id, signal.reason)
            elif signal.direction is not None and signal.direction != current_position:
                await self._close_position(market_id, f"反向: {signal.reason}")
                if signal.strength >= 0.5:
                    await self._open_position(
                        market_id, signal.direction, signal.reason,
                        signal.sl_price, signal.tp_price,
                    )
        else:
            if signal.direction is not None and signal.strength >= 0.5:
                exec_inst = self.executor.get_executor(market_id)
                if exec_inst:
                    consec = exec_inst.consecutive_losses
                    if self.risk.check_market_pause(market_id, consec):
                        return
                await self._open_position(
                    market_id, signal.direction, signal.reason,
                    signal.sl_price, signal.tp_price,
                )

    async def _open_position(
        self, market_id: str, direction: str, reason: str,
        sl_price: float = 0.0, tp_price: float = 0.0,
    ):
        """開倉"""
        market_executor = self.executor.get_executor(market_id)
        strat_name = self.selector.get_active_strategy_name(market_id)

        if not market_executor:
            print(f"  [{market_id}] 模擬開{direction} ({strat_name}): {reason}")
            self.positions[market_id] = {
                "direction": direction,
                "entry_price": 0.0,
                "sl_price": sl_price,
                "tp_price": tp_price,
                "bars_held": 0,
                "entry_bar": self.total_signals,
            }
            return

        cfg = MARKETS.get(market_id, {})
        use_maker = STRATEGY_PARAMS.get(strat_name, {}).get("use_maker", False)

        result = market_executor.open_position(
            direction, f"[{strat_name}] {reason}", use_maker=use_maker,
        )

        if result["status"] == "ok":
            self.positions[market_id] = {
                "direction": direction,
                "entry_price": result["price"],
                "sl_price": sl_price,
                "tp_price": tp_price,
                "bars_held": 0,
                "entry_bar": self.total_signals,
            }
            self.total_trades += 1

    async def _close_position(self, market_id: str, reason: str):
        """平倉"""
        market_executor = self.executor.get_executor(market_id)
        pos = self.positions[market_id]

        if not market_executor:
            print(f"  [{market_id}] 模擬平倉: {reason}")
            # Bug #2 修復：重置策略實例的追蹤止損狀態
            active_strategy = self.selector.get_active_strategy(market_id)
            if active_strategy:
                active_strategy.reset_trailing_stop()
            self.positions[market_id] = {
                "direction": None,
                "entry_price": 0.0,
                "sl_price": 0.0,
                "tp_price": 0.0,
                "bars_held": 0,
                "entry_bar": 0,
            }
            return

        entry_price = pos["entry_price"]
        direction = pos["direction"]

        result = market_executor.close_position(reason)
        if result["status"] == "ok":
            pnl = result.get("pnl", 0)
            exit_price = result.get("price", 0)
            self.risk.record_pnl(pnl, market_id)
            self.risk.check_daily_limit()
            self.total_trades += 1

            # === 記錄交易到策略選擇器（觸發自適應切換） ===
            if direction and entry_price > 0:
                # Bug #1 修復：傳入正確的 strategy_name，而非 market_id
                strat_name_for_record = self.selector.get_active_strategy_name(market_id)
                self.selector.record_trade(
                    strat_name_for_record, direction, entry_price, exit_price, pnl
                )

            # Bug #2 修復：平倉成功後重置策略的追蹤止損狀態
            active_strategy = self.selector.get_active_strategy(market_id)
            if active_strategy:
                active_strategy.reset_trailing_stop()

            self.positions[market_id] = {
                "direction": None,
                "entry_price": 0.0,
                "sl_price": 0.0,
                "tp_price": 0.0,
                "bars_held": 0,
                "entry_bar": 0,
            }

    def print_status(self):
        """打印系統狀態"""
        uptime = time.time() - self.start_time
        hours = uptime / 3600

        print("\n" + "=" * 70)
        print(f"  多市場交易系統 v2.0 | 運行 {hours:.1f} 小時")
        print("=" * 70)

        for market_id in MARKETS:
            pos = self.positions[market_id]
            exec_inst = self.executor.get_executor(market_id)
            strat_name = self.selector.get_active_strategy_name(market_id)

            pos_str = (
                f"{pos['direction']} @{pos['entry_price']:.2f} "
                f"(SL={pos['sl_price']:.2f}, TP={pos['tp_price']:.2f}, "
                f"bars={pos['bars_held']})"
                if pos["direction"]
                else "空倉"
            )

            pnl_str = ""
            if exec_inst:
                pnl_str = f" | PnL=${exec_inst.total_pnl:+.2f}"

            paused = "⏸️" if market_id in self.risk.paused_markets else "▶️"
            cfg = MARKETS[market_id]
            print(
                f"  {paused} [{market_id}] {strat_name:<18s} "
                f"${cfg['capital_pct']} {cfg['leverage']}x | {pos_str}{pnl_str}"
            )

        total_pnl = self.executor.get_total_pnl()
        daily_pnl = self.risk.daily_pnl
        balance = self.executor.get_account_balance()
        print("-" * 70)
        print(
            f"  總PnL: ${total_pnl:+.2f} | "
            f"今日: ${daily_pnl:+.2f} | "
            f"帳戶: ${balance:.2f} | "
            f"交易: {self.total_trades}筆"
        )
        if self.risk.circuit_breaker_active:
            remaining = max(0, self.risk.circuit_breaker_until - time.time())
            print(f"  ⚠️ 全局熔斷中！剩餘 {remaining/60:.0f} 分鐘")
        print("=" * 70)

        # 打印策略切換狀態
        self.selector.print_status()

    async def run(self):
        """啟動系統"""
        print("\n" + "=" * 70)
        print("  多市場多策略交易系統 v2.0 啟動")
        print(f"  總資金: ${TOTAL_CAPITAL}")
        print(f"  市場數: {len(MARKETS)}")
        print(f"  每日虧損上限: ${DAILY_LOSS_LIMIT:.2f}")
        print("=" * 70)

        # 打印策略配置
        print("\n  === 策略配置（自適應切換） ===")
        for market_id in MARKETS:
            strat_name = self.selector.get_active_strategy_name(market_id)
            cfg = MARKETS[market_id]
            candidates = cfg.get("strategies", [cfg["strategy"]])
            print(f"  {market_id}: 🎯 {strat_name} | 候補: {candidates}")

        # 初始化執行器
        live = self.executor.initialize()
        if live:
            print("\n  ✅ 實盤模式")
        else:
            print("\n  ⚠️ 模擬模式（未配置 HL 密鑰）")

        markets_str = ", ".join(MARKETS.keys())
        notify_system_start(markets_str, TOTAL_CAPITAL, live)

        # 預填歷史數據
        print("\n  正在預填歷史數據...")
        for market_id, cfg in MARKETS.items():
            self.feed.prefill_history(
                market_id, cfg["coin"], cfg["timeframe"], bars=200
            )

        if live:
            self.executor.print_status()

        import asyncio
        asyncio.create_task(self._periodic_status())

        print("\n  正在連接 WebSocket...")
        await self.feed.start()

    async def _periodic_status(self):
        """定期打印狀態"""
        import asyncio
        while True:
            await asyncio.sleep(300)
            self.print_status()
