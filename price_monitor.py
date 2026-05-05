"""
高頻價格監控模組 — 每 5 秒檢查止損/止盈
獨立於 K 線回調，確保在劇烈波動時及時平倉
v2.0 — 新增 SmartExit 智能出場（EMA動態止損 + RSI動量止盈 + 增強追蹤止損）
"""

import asyncio
import time
import requests
from typing import Dict, Optional, Callable, Awaitable

HL_INFO_URL = "https://api.hyperliquid.xyz/info"


class PriceMonitor:
    """每 5 秒從 API 獲取價格 ，檢查止損/止盈/緊急止損/智能出場"""

    def __init__(self, positions, close_callback, check_interval=5):
        self.positions = positions
        self.close_callback = close_callback
        self.check_interval = check_interval
        self.running = False
        self._task = None
        self.last_prices = {}
        self.check_count = 0
        self.trigger_count = 0

        # SmartExit 智能出場引擎
        from smart_exit import SmartExit
        self.smart_exit = SmartExit()

        # K線緩存（每60秒更新一次）
        self._candle_cache: Dict[str, dict] = {}
        self._candle_cache_ttl = 60

    def start(self):
        if self.running:
            return
        self.running = True
        self._task = asyncio.ensure_future(self._monitor_loop())
        print(f"  [PriceMonitor] 啟動 — 每 {self.check_interval}s 檢查止損/止盈（SmartExit=ON）")

    def stop(self):
        self.running = False
        if self._task and not self._task.done():
            self._task.cancel()

    def _fetch_prices(self):
        try:
            resp = requests.post(HL_INFO_URL, json={"type": "allMids"}, timeout=10)
            resp.raise_for_status()
            return {k: float(v) for k, v in resp.json().items()}
        except Exception as e:
            print(f"  [PriceMonitor] 價格獲取失敗：{e}")
            return {}

    def _check_sl_tp(self, market_id, current_price):
        pos = self.positions.get(market_id)
        if not pos or pos.get("direction") is None:
            return None

        direction = pos["direction"]
        entry_price = pos.get("entry_price", 0.0)
        sl_price = pos.get("sl_price", 0.0)
        tp_price = pos.get("tp_price", 0.0)
        trailing_stop = pos.get("trailing_stop_price", 0.0)

        # 1. 追蹤止損
        if trailing_stop > 0:
            if direction == "long" and current_price <= trailing_stop:
                return f"[即時] 追蹤止損 @{trailing_stop:.2f} (現價={current_price:.2f})"
            if direction == "short" and current_price >= trailing_stop:
                return f"[即時] 追蹤止損 @{trailing_stop:.2f} (現價={current_price:.2f})"

        # 2. 固定止損
        if sl_price > 0:
            if direction == "long" and current_price <= sl_price:
                loss_pct = (current_price - entry_price) / entry_price * 100
                return f"[即時] 止損 @{sl_price:.2f} (現價={current_price:.2f}, {loss_pct:.1f}%)"
            if direction == "short" and current_price >= sl_price:
                loss_pct = (entry_price - current_price) / entry_price * 100
                return f"[即時] 止損 @{sl_price:.2f} (現價={current_price:.2f}, {loss_pct:.1f}%)"

        # 3. 止盈
        if tp_price > 0:
            if direction == "long" and current_price >= tp_price:
                gain_pct = (current_price - entry_price) / entry_price * 100
                return f"[即時] 止盈 @{tp_price:.2f} (現價={current_price:.2f}, +{gain_pct:.1f}%)"
            if direction == "short" and current_price <= tp_price:
                gain_pct = (entry_price - current_price) / entry_price * 100
                return f"[即時] 止盈 @{tp_price:.2f} (現價={current_price:.2f}, +{gain_pct:.1f}%)"

        # 4. 緊急止損：價格虧損超過 5%
        if entry_price > 0:
            if direction == "long":
                pnl_pct = (current_price - entry_price) / entry_price * 100
            else:
                pnl_pct = (entry_price - current_price) / entry_price * 100
            if pnl_pct <= -5.0:
                return f"[緊急] 虧損超限 {pnl_pct:.1f}% (現價={current_price:.2f})"

        return None

    def _check_smart_exit(self, market_id, current_price):
        """SmartExit 智能出場檢查"""
        pos = self.positions.get(market_id)
        if not pos or pos.get("direction") is None:
            return None

        candle_data = self._get_cached_candles(market_id)
        if not candle_data or len(candle_data.get("closes", [])) < 25:
            return None

        signal = self.smart_exit.check_exit(
            market_id=market_id,
            position={
                "direction": pos["direction"],
                "entry_price": pos.get("entry_price", 0),
                "sl_price": pos.get("sl_price", 0),
                "tp_price": pos.get("tp_price", 0),
            },
            candle_closes=candle_data["closes"],
            candle_highs=candle_data["highs"],
            candle_lows=candle_data["lows"],
            current_price=current_price,
        )

        if signal.should_exit:
            return f"[SmartExit] {signal.reason}"
        return None

    def _get_cached_candles(self, market_id: str) -> Optional[dict]:
        """獲取K線數據（帶60秒緩存）"""
        now = time.time()
        cache = self._candle_cache.get(market_id)
        if cache and (now - cache["timestamp"]) < self._candle_cache_ttl:
            return cache["data"]
        try:
            data = self._fetch_candles(market_id)
            if data:
                self._candle_cache[market_id] = {"timestamp": now, "data": data}
                return data
        except Exception as e:
            print(f"  [PriceMonitor] {market_id} K線獲取失敗: {e}")
        return cache["data"] if cache else None

    def _fetch_candles(self, market_id: str) -> Optional[dict]:
        """從 Hyperliquid API 獲取最近50根1h K線"""
        coin_map = {"BTC": "BTC", "ETH": "ETH", "SOL": "SOL",
                    "DOGE": "DOGE", "ZEC": "ZEC", "PAXG": "PAXG"}
        if ":" in market_id:
            coin = market_id
        else:
            coin = coin_map.get(market_id, market_id)

        end_time = int(time.time() * 1000)
        start_time = end_time - (50 * 3600 * 1000)

        try:
            resp = requests.post(
                HL_INFO_URL,
                json={"type": "candleSnapshot", "req": {
                    "coin": coin, "interval": "1h",
                    "startTime": start_time, "endTime": end_time,
                }},
                timeout=10,
            )
            if resp.status_code != 200:
                return None
            candles = resp.json()
            if not candles or not isinstance(candles, list):
                return None
            closes, highs, lows = [], [], []
            for c in candles:
                closes.append(float(c["c"]))
                highs.append(float(c["h"]))
                lows.append(float(c["l"]))
            return {"closes": closes, "highs": highs, "lows": lows}
        except requests.exceptions.Timeout:
            return None
        except Exception as e:
            print(f"  [PriceMonitor] K線API錯誤 {market_id}: {e}")
            return None

    async def _monitor_loop(self):
        print(f"  [PriceMonitor] 監控循環開始")
        while self.running:
            try:
                active = {m: p for m, p in self.positions.items() if p.get("direction") is not None}
                if active:
                    prices = self._fetch_prices()
                    if prices:
                        self.last_prices = prices
                        self.check_count += 1
                        for market_id, pos in active.items():
                            coin = market_id.split(":")[0] if ":" in market_id else market_id
                            cp = prices.get(coin)
                            if cp is None:
                                continue

                            # 先檢查固定止損/止盈/緊急止損
                            reason = self._check_sl_tp(market_id, cp)

                            # 如果固定條件未觸發，再檢查 SmartExit
                            if not reason:
                                reason = self._check_smart_exit(market_id, cp)

                            if reason:
                                self.trigger_count += 1
                                print(f"  [PriceMonitor] {market_id} 觸發：{reason}")
                                try:
                                    await self.close_callback(market_id, reason)
                                    self.smart_exit.reset_market(market_id)
                                except Exception as e:
                                    print(f"  [PriceMonitor] {market_id} 平倉失敗：{e}")

                    # 每60次（約5分鐘）打印狀態
                    if self.check_count % 60 == 0:
                        parts = []
                        for mid, pos in active.items():
                            coin = mid.split(":")[0] if ":" in mid else mid
                            cp = prices.get(coin, 0)
                            ep = pos.get("entry_price", 0)
                            d = pos.get("direction", "?")
                            sl = pos.get("sl_price", 0)
                            if ep > 0:
                                pnl = ((cp-ep)/ep*100) if d=="long" else ((ep-cp)/ep*100)
                                parts.append(f"{coin}({d[0].upper()}):{cp:.4g} PnL={pnl:+.1f}% SL={sl:.4g}")
                        if parts:
                            print(f"  [PriceMonitor] #{self.check_count} | {' | '.join(parts)}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"  [PriceMonitor] 異常：{e}")
            await asyncio.sleep(self.check_interval)
