"""
多市場數據層 v1.1
使用 Hyperliquid WebSocket 訂閱多個市場的 K 線數據
修復：WebSocket 斷線重連、graceful shutdown
"""

import asyncio
import json
import time
import requests
import numpy as np
from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Callable, Optional

import websockets

from config import HL_API_URL, CANDLE_BUFFER_SIZE, MARKETS

HL_WS_URL = "wss://api.hyperliquid.xyz/ws"
HL_REST_URL = f"{HL_API_URL}/info"


class CandleBuffer:
    """單一市場的 K 線緩衝區"""

    def __init__(self, market_id: str, max_size: int = CANDLE_BUFFER_SIZE):
        self.market_id = market_id
        self.candles: deque = deque(maxlen=max_size)
        self.current_candle: Optional[dict] = None

    def append(self, candle: dict):
        self.candles.append(candle)

    def get_closes(self) -> np.ndarray:
        if not self.candles:
            return np.array([])
        return np.array([c["close"] for c in self.candles])

    def get_highs(self) -> np.ndarray:
        if not self.candles:
            return np.array([])
        return np.array([c["high"] for c in self.candles])

    def get_lows(self) -> np.ndarray:
        if not self.candles:
            return np.array([])
        return np.array([c["low"] for c in self.candles])

    def get_volumes(self) -> np.ndarray:
        if not self.candles:
            return np.array([])
        return np.array([c["volume"] for c in self.candles])

    def __len__(self):
        return len(self.candles)


class MultiMarketFeed:
    """多市場實時數據源 — 透過 Hyperliquid WebSocket 訂閱多個市場"""

    def __init__(self):
        self.buffers: Dict[str, CandleBuffer] = {}
        self.callbacks: List[Callable] = []
        self._running = False
        self._tasks: List[asyncio.Task] = []

        # 為每個市場建立緩衝區
        for market_id, cfg in MARKETS.items():
            self.buffers[market_id] = CandleBuffer(market_id)

    def on_candle_close(self, callback: Callable):
        """註冊 K 線收盤回調"""
        self.callbacks.append(callback)

    async def start(self):
        """啟動所有市場的數據訂閱"""
        self._running = True

        # 為每個市場啟動一個 WebSocket 連接
        for market_id, cfg in MARKETS.items():
            coin = cfg["coin"]
            tf = cfg["timeframe"]
            task = asyncio.create_task(
                self._subscribe_candles(market_id, coin, tf)
            )
            self._tasks.append(task)

        # 啟動定期 OBI 採集
        obi_task = asyncio.create_task(self._periodic_obi_fetch())
        self._tasks.append(obi_task)

        # 等待所有任務（它們會無限循環直到 _running=False）
        try:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        except asyncio.CancelledError:
            pass

    async def stop(self):
        """停止所有連接"""
        self._running = False
        # 取消所有任務
        for task in self._tasks:
            if not task.done():
                task.cancel()
        # 等待任務結束
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def _subscribe_candles(self, market_id: str, coin: str, timeframe: str):
        """訂閱單個市場的 K 線 WebSocket"""
        retry_count = 0
        max_retry_delay = 60

        while self._running:
            try:
                async with websockets.connect(
                    HL_WS_URL,
                    ping_interval=20,
                    ping_timeout=30,
                    close_timeout=5,
                ) as ws:
                    # 發送訂閱請求
                    sub_msg = {
                        "method": "subscribe",
                        "subscription": {
                            "type": "candle",
                            "coin": coin,
                            "interval": timeframe,
                        },
                    }
                    await ws.send(json.dumps(sub_msg))
                    print(f"  [WS] {market_id} ({coin}/{timeframe}) 已訂閱")
                    retry_count = 0  # 連接成功，重置計數

                    async for message in ws:
                        if not self._running:
                            break
                        try:
                            data = json.loads(message)
                            await self._handle_candle_msg(market_id, data)
                        except json.JSONDecodeError:
                            pass
                        except Exception as e:
                            print(f"  [WS] {market_id} 處理消息錯誤: {e}")

            except asyncio.CancelledError:
                print(f"  [WS] {market_id} 任務已取消")
                return
            except websockets.exceptions.ConnectionClosed as e:
                retry_count += 1
                delay = min(5 * retry_count, max_retry_delay)
                print(f"  [WS] {market_id} 斷線 (code={e.code})，{delay}s 後重連...")
                await asyncio.sleep(delay)
            except Exception as e:
                retry_count += 1
                delay = min(10 * retry_count, max_retry_delay)
                print(f"  [WS] {market_id} 錯誤: {e}，{delay}s 後重連...")
                await asyncio.sleep(delay)

    async def _handle_candle_msg(self, market_id: str, data: dict):
        """處理 K 線 WebSocket 消息"""
        channel = data.get("channel", "")
        if channel != "candle":
            return

        candle_data = data.get("data", {})
        if not candle_data:
            return

        # Hyperliquid candle 格式
        candle = {
            "timestamp": candle_data.get("t", 0),
            "open": float(candle_data.get("o", 0)),
            "high": float(candle_data.get("h", 0)),
            "low": float(candle_data.get("l", 0)),
            "close": float(candle_data.get("c", 0)),
            "volume": float(candle_data.get("v", 0)),
        }

        buf = self.buffers[market_id]

        # 判斷是否為新 K 線（時間戳不同）
        is_new = (buf.current_candle is None or
                  candle["timestamp"] != buf.current_candle.get("timestamp", 0))

        if is_new and buf.current_candle is not None:
            # 前一根 K 線收盤
            closed_candle = buf.current_candle.copy()
            buf.append(closed_candle)

            dt = datetime.fromtimestamp(
                closed_candle["timestamp"] / 1000, tz=timezone.utc
            )
            print(
                f"  [{market_id}] K線收盤 {dt.strftime('%H:%M')} | "
                f"C={closed_candle['close']:.2f} | "
                f"V={closed_candle['volume']:.1f} | "
                f"buf={len(buf)}"
            )

            # 觸發回調
            for cb in self.callbacks:
                try:
                    await cb(market_id, closed_candle, buf)
                except Exception as e:
                    print(f"  [{market_id}] 回調錯誤: {e}")

        buf.current_candle = candle

    async def _periodic_obi_fetch(self):
        """定期獲取所有市場的訂單簿不平衡度（OBI）"""
        while self._running:
            try:
                await asyncio.sleep(10)  # 每 10 秒更新一次
            except asyncio.CancelledError:
                return

            if not self._running:
                return

            for market_id, cfg in MARKETS.items():
                if not self._running:
                    return
                try:
                    obi_data = await asyncio.to_thread(
                        fetch_orderbook, cfg["coin"]
                    )
                    buf = self.buffers[market_id]
                    if buf.current_candle is not None:
                        buf.current_candle["obi"] = obi_data["obi"]
                        buf.current_candle["spread"] = obi_data["spread"]
                except Exception:
                    pass  # OBI 失敗不影響主流程

    def prefill_history(self, market_id: str, coin: str, timeframe: str, bars: int = 200):
        """用 REST API 預填歷史 K 線"""
        try:
            now_ms = int(time.time() * 1000)
            # 計算需要多少毫秒的歷史數據
            tf_map = {"1m": 60000, "5m": 300000, "15m": 900000, "1h": 3600000}
            interval_ms = tf_map.get(timeframe, 300000)
            start_ms = now_ms - bars * interval_ms

            payload = {
                "type": "candleSnapshot",
                "req": {
                    "coin": coin,
                    "interval": timeframe,
                    "startTime": start_ms,
                    "endTime": now_ms,
                },
            }
            resp = requests.post(HL_REST_URL, json=payload, timeout=15)
            data = resp.json()

            if isinstance(data, list):
                buf = self.buffers[market_id]
                for c in data:
                    candle = {
                        "timestamp": c["t"],
                        "open": float(c["o"]),
                        "high": float(c["h"]),
                        "low": float(c["l"]),
                        "close": float(c["c"]),
                        "volume": float(c["v"]),
                    }
                    buf.append(candle)
                print(f"  [{market_id}] 歷史數據預填: {len(buf)} 根 K 線")
            else:
                print(f"  [{market_id}] 歷史數據格式異常: {str(data)[:100]}")
        except Exception as e:
            print(f"  [{market_id}] 歷史數據預填失敗: {e}")


def fetch_orderbook(coin: str) -> dict:
    """獲取訂單簿數據（同步）"""
    try:
        payload = {"type": "l2Book", "coin": coin}
        resp = requests.post(HL_REST_URL, json=payload, timeout=3)
        data = resp.json()
        levels = data.get("levels", [[], []])
        bids = levels[0][:10] if len(levels) > 0 else []
        asks = levels[1][:10] if len(levels) > 1 else []
        bid_vol = sum(float(b["sz"]) for b in bids)
        ask_vol = sum(float(a["sz"]) for a in asks)
        spread = float(asks[0]["px"]) - float(bids[0]["px"]) if bids and asks else 0
        obi = (bid_vol - ask_vol) / (bid_vol + ask_vol + 1e-10)
        mid = (float(bids[0]["px"]) + float(asks[0]["px"])) / 2 if bids and asks else 0
        return {
            "obi": obi, "spread": spread,
            "bid_vol": bid_vol, "ask_vol": ask_vol,
            "mid": mid,
        }
    except Exception:
        return {"obi": 0.0, "spread": 0.0, "bid_vol": 0.0, "ask_vol": 0.0, "mid": 0.0}


def fetch_funding_rate(coin: str) -> float:
    """獲取當前資金費率"""
    try:
        payload = {"type": "meta"}
        resp = requests.post(HL_REST_URL, json=payload, timeout=5)
        meta = resp.json()
        for asset in meta.get("universe", []):
            if asset.get("name") == coin:
                return float(asset.get("funding", 0))
        return 0.0
    except Exception:
        return 0.0
