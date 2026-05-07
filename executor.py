"""
多幣種 Hyperliquid 交易執行器 v1.1
支援同時在多個市場開倉/平倉，使用隔離保證金
修復：API 錢包 + 主帳戶地址的正確配置
"""

import json
import math
import os
import time
from datetime import datetime, timezone
from typing import Optional, Dict

from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants
from eth_account import Account

from config import HL_SECRET, HL_ACCOUNT, MARKETS, TRADE_LOG, LOG_DIR
from telegram_notifier import notify_trade_open, notify_trade_close


class MarketExecutor:
    """單一市場的交易執行器"""

    def __init__(
        self,
        market_id: str,
        exchange: Exchange,
        info: Info,
        account_address: str,
        coin: str,
        leverage: int,
        capital_pct: float,
        sz_decimals: int = 5,
    ):
        self.market_id = market_id
        self.exchange = exchange
        self.info = info
        self.account_address = account_address
        self.coin = coin
        self.leverage = leverage
        self.capital_pct = capital_pct
        self.sz_decimals = sz_decimals

        # 持倉狀態
        self.current_position: Optional[str] = None  # "long" / "short" / None
        self.entry_price: float = 0.0
        self.position_size: float = 0.0
        self.entry_time: float = 0.0

        # 統計
        self.total_pnl: float = 0.0
        self.trade_count: int = 0
        self.win_count: int = 0
        self.consecutive_losses: int = 0

        # 設置槓桿
        self._set_leverage()
        # 同步持倉
        self._sync_position()

    def _set_leverage(self):
        """設置槓桿倍數（隔離保證金）"""
        try:
            result = self.exchange.update_leverage(
                self.leverage, self.coin, is_cross=False
            )
            print(f"  [{self.market_id}] 槓桿已設置: {self.leverage}x (隔離)")
        except Exception as e:
            # 某些合約可能不支持隔離，改用全倉
            try:
                result = self.exchange.update_leverage(
                    self.leverage, self.coin, is_cross=True
                )
                print(f"  [{self.market_id}] 槓桿已設置: {self.leverage}x (全倉)")
            except Exception as e2:
                print(f"  [{self.market_id}] 設置槓桿失敗: {e2}")

    def _sync_position(self):
        """同步當前持倉狀態"""
        try:
            # HIP-3 unlisted perp 需要指定 dex 名稱查詢持倉
            dex = self.coin.split(":")[0] if ":" in self.coin else ""
            state = self.info.user_state(self.account_address, dex=dex)
            positions = state.get("assetPositions", [])
            for pos in positions:
                p = pos.get("position", {})
                if p.get("coin") == self.coin:
                    szi = float(p.get("szi", "0"))
                    if abs(szi) > 1e-10:
                        self.current_position = "long" if szi > 0 else "short"
                        self.entry_price = float(p.get("entryPx", "0"))
                        self.position_size = abs(szi)
                        return
            self.current_position = None
            self.entry_price = 0.0
            self.position_size = 0.0
        except Exception as e:
            print(f"  [{self.market_id}] 同步持倉失敗: {e}")

    def get_mid_price(self) -> float:
        """取得當前中間價"""
        try:
            # HIP-3 unlisted perp 需要指定 dex 名稱
            dex = self.coin.split(":")[0] if ":" in self.coin else ""
            mids = self.info.all_mids(dex)
            return float(mids.get(self.coin, "0"))
        except Exception:
            return 0.0

    def _calc_size(self, price: float, position_usd: Optional[float] = None) -> float:
        """計算下單數量"""
        if price <= 0:
            return 0.0
        from config import RISK_FREE_MARGIN_PCT
        # 動態獲取帳戶價值
        try:
            state = self.info.user_state(self.account_address)
            account_value = float(state.get('marginSummary', {}).get('accountValue', '0'))
        except: account_value = 400.0
        usd = position_usd or (account_value * self.capital_pct * (1 - RISK_FREE_MARGIN_PCT))
        notional = usd * self.leverage
        raw_size = notional / price
        size = round(raw_size, self.sz_decimals)
        # 確保最小名義價值 >= $10
        if size * price < 10:
            size = round(10.0 / price + 10 ** (-self.sz_decimals), self.sz_decimals)
        return size

    @staticmethod
    def _round_price(price: float, sz_decimals: int = 5, is_buy: bool = True) -> float:
        """將價格調整為 Hyperliquid 接受的格式（動態精度）"""
        if price <= 0:
            return 0
        # 根據價格大小動態決定有效位數（Hyperliquid 統一用 5 位有效數字）
        if price >= 100000:
            tick = 1.0
        elif price >= 10000:
            tick = 0.1
        elif price >= 1000:
            tick = 0.1
        elif price >= 100:
            tick = 0.01
        elif price >= 10:
            tick = 0.001
        elif price >= 1:
            tick = 0.0001
        else:
            tick = 0.00001
        if is_buy:
            rounded = math.ceil(price / tick) * tick
        else:
            rounded = math.floor(price / tick) * tick
        # 避免浮點數精度問題
        decimals = max(0, -int(math.floor(math.log10(tick))))
        rounded = round(rounded, decimals)
        return rounded

    def open_position(self, direction: str, reason: str = "",
                      position_usd: Optional[float] = None,
                      use_maker: bool = False) -> dict:
        """開倉"""
        is_buy = direction == "long"

        self._sync_position()

        if self.current_position == direction:
            return {"status": "skip", "msg": f"已有 {direction} 持倉"}

        # 如果有反向持倉，先平倉
        if self.current_position is not None:
            close_result = self.close_position(f"反向開倉: {direction}")
            if close_result["status"] == "error":
                return {"status": "error", "msg": f"反向平倉失敗: {close_result.get('msg', '')}"}

        price = self.get_mid_price()
        if price <= 0:
            return {"status": "error", "msg": "無法取得價格"}

        size = self._calc_size(price, position_usd)
        if size <= 0:
            return {"status": "error", "msg": "計算數量失敗"}

        try:
            slippage = 0.003 if use_maker else 0.005
            if is_buy:
                limit_price = self._round_price(
                    price * (1 + slippage), self.sz_decimals, is_buy=True
                )
            else:
                limit_price = self._round_price(
                    price * (1 - slippage), self.sz_decimals, is_buy=False
                )

            # IOC 限價單模擬市價單
            order_type = {"limit": {"tif": "Ioc"}}
            if use_maker:
                # Maker 用 GTC 限價單（可能不立即成交）
                order_type = {"limit": {"tif": "Gtc"}}
                # Maker 用更緊的價格
                if is_buy:
                    limit_price = self._round_price(
                        price * 0.9999, self.sz_decimals, is_buy=True
                    )
                else:
                    limit_price = self._round_price(
                        price * 1.0001, self.sz_decimals, is_buy=False
                    )

            result = self.exchange.order(
                self.coin, is_buy, size, limit_price, order_type
            )

            status = result.get("status", "")
            response = result.get("response", {})

            if status == "ok":
                statuses = response.get("data", {}).get("statuses", [])
                if statuses and "filled" in statuses[0]:
                    filled = statuses[0]["filled"]
                    fill_price = float(filled.get("avgPx", price))
                    fill_size = float(filled.get("totalSz", size))

                    self.current_position = direction
                    self.entry_price = fill_price
                    self.position_size = fill_size
                    self.entry_time = time.time()
                    self.trade_count += 1

                    self._log_trade("open", direction, fill_price, fill_size, reason)

                    print(
                        f"  [{self.market_id}] ✅ 開{direction} "
                        f"@{fill_price:.2f} × {fill_size} | {reason}"
                    )

                    return {
                        "status": "ok",
                        "direction": direction,
                        "price": fill_price,
                        "size": fill_size,
                    }
                elif statuses and "resting" in statuses[0]:
                    # Maker 訂單已掛出
                    resting = statuses[0]["resting"]
                    oid = resting.get("oid", "")
                    print(
                        f"  [{self.market_id}] 📋 Maker 訂單已掛出 "
                        f"@{limit_price:.2f} | oid={oid}"
                    )
                    return {"status": "pending", "oid": oid, "price": limit_price}
                elif statuses and "error" in statuses[0]:
                    err = statuses[0]["error"]
                    print(f"  [{self.market_id}] ❌ 開倉錯誤: {err}")
                    return {"status": "error", "msg": err}
                else:
                    return {"status": "error", "msg": f"未成交: {statuses}"}
            else:
                return {"status": "error", "msg": f"下單失敗: {result}"}

        except Exception as e:
            return {"status": "error", "msg": f"下單異常: {e}"}

    def close_position(self, reason: str = "") -> dict:
        """平倉"""
        self._sync_position()

        if self.current_position is None:
            return {"status": "skip", "msg": "無持倉"}

        is_buy = self.current_position == "short"
        price = self.get_mid_price()
        if price <= 0:
            return {"status": "error", "msg": "無法取得價格"}

        size = self.position_size
        if size <= 0:
            self.current_position = None
            return {"status": "skip", "msg": "持倉數量為 0"}

        try:
            slippage = 0.005
            if is_buy:
                limit_price = self._round_price(
                    price * (1 + slippage), self.sz_decimals, is_buy=True
                )
            else:
                limit_price = self._round_price(
                    price * (1 - slippage), self.sz_decimals, is_buy=False
                )

            result = self.exchange.order(
                self.coin, is_buy, size, limit_price,
                {"limit": {"tif": "Ioc"}},
                reduce_only=True,
            )

            status = result.get("status", "")
            response = result.get("response", {})

            if status == "ok":
                statuses = response.get("data", {}).get("statuses", [])
                if statuses and "filled" in statuses[0]:
                    filled = statuses[0]["filled"]
                    fill_price = float(filled.get("avgPx", price))

                    # 計算 PnL
                    if self.current_position == "long":
                        pnl = (fill_price - self.entry_price) * self.position_size
                    else:
                        pnl = (self.entry_price - fill_price) * self.position_size

                    self.total_pnl += pnl
                    if pnl > 0:
                        self.win_count += 1
                        self.consecutive_losses = 0
                    else:
                        self.consecutive_losses += 1

                    direction = self.current_position
                    self._log_trade("close", direction, fill_price, size, reason, pnl)

                    emoji = "🟢" if pnl > 0 else "🔴"
                    print(
                        f"  [{self.market_id}] {emoji} 平{direction} "
                        f"@{fill_price:.2f} | PnL=${pnl:+.2f} | {reason}"
                    )

                    self.current_position = None
                    self.entry_price = 0.0
                    self.position_size = 0.0

                    return {
                        "status": "ok",
                        "direction": direction,
                        "price": fill_price,
                        "pnl": pnl,
                    }
                elif statuses and "error" in statuses[0]:
                    err = statuses[0]["error"]
                    if "Reduce only" in err or "asset=0" in str(err):
                        self.current_position = None
                        self.entry_price = 0.0
                        self.position_size = 0.0
                        return {"status": "skip", "msg": "HL 上已無倉位"}
                    return {"status": "error", "msg": err}
                else:
                    return {"status": "error", "msg": f"未成交: {statuses}"}
            else:
                return {"status": "error", "msg": f"平倉失敗: {result}"}

        except Exception as e:
            return {"status": "error", "msg": f"平倉異常: {e}"}

    def _log_trade(self, action: str, direction: str, price: float,
                   size: float, reason: str = "", pnl: float = None):
        """記錄交易日誌"""
        record = {
            "time": datetime.now(timezone.utc).isoformat(),
            "market": self.market_id,
            "coin": self.coin,
            "action": action,
            "direction": direction,
            "price": price,
            "size": size,
            "pnl": pnl,
            "total_pnl": self.total_pnl,
            "trade_count": self.trade_count,
            "reason": reason,
        }
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            with open(TRADE_LOG, "a") as f:
                f.write(json.dumps(record) + "\n")
        except Exception:
            pass
        try:
            self._notify_trade(record)
        except Exception:
            pass

    def _notify_trade(self, record: dict):
        action = record.get("action", "")
        market = record.get("market", "")
        direction = record.get("direction", "")
        price = record.get("price", 0)
        size = record.get("size", 0)
        pnl = record.get("pnl")
        reason = record.get("reason", "")

        if action == "open":
            notify_trade_open(market, direction, price, size, reason=reason)
        elif action == "close" and pnl is not None:
            notify_trade_close(market, direction, price, pnl, reason=reason)


    def get_unrealized_pnl(self) -> float:
        """計算未實現盈虧"""
        if self.current_position is None:
            return 0.0
        price = self.get_mid_price()
        if price <= 0:
            return 0.0
        if self.current_position == "long":
            return (price - self.entry_price) * self.position_size
        else:
            return (self.entry_price - price) * self.position_size

    def status_str(self) -> str:
        """狀態摘要"""
        pos = (
            f"{self.current_position} @{self.entry_price:.2f}"
            if self.current_position
            else "空倉"
        )
        wr = (
            f"{self.win_count}/{self.trade_count}"
            if self.trade_count > 0
            else "0/0"
        )
        return (
            f"[{self.market_id}] {pos} | "
            f"PnL=${self.total_pnl:+.2f} | W/L={wr} | "
            f"連虧={self.consecutive_losses}"
        )


class MultiMarketExecutor:
    """多市場交易執行器管理器"""

    def __init__(self):
        self.executors: Dict[str, MarketExecutor] = {}
        self.info: Optional[Info] = None
        self.exchange: Optional[Exchange] = None
        self._initialized = False

    def initialize(self) -> bool:
        """初始化 Hyperliquid 連接"""
        if not HL_SECRET or not HL_ACCOUNT:
            print("  [EXEC] ⚠️ 缺少 HL_SECRET 或 HL_ACCOUNT，以模擬模式運行")
            return False

        try:
            wallet = Account.from_key(HL_SECRET)

            # 需要包含 HIP-3 perp dex (flx) 才能交易 OIL 等 unlisted perp
            perp_dexs = ["", "flx"]

            self.info = Info(constants.MAINNET_API_URL, skip_ws=True, perp_dexs=perp_dexs)

            # API 錢包的地址（從私鑰派生）
            api_wallet_address = wallet.address

            # Exchange 初始化：
            # - wallet = API 錢包（用於簽名）
            # - account_address = 主帳戶地址（用於查詢和下單）
            # - perp_dexs = 包含 flx 以支持 HIP-3 unlisted perp
            self.exchange = Exchange(
                wallet,
                constants.MAINNET_API_URL,
                account_address=HL_ACCOUNT,
                perp_dexs=perp_dexs,
            )

            print(f"  [EXEC] API 錢包: {api_wallet_address}")
            print(f"  [EXEC] 主帳戶: {HL_ACCOUNT}")

            # 為每個市場建立執行器
            for market_id, cfg in MARKETS.items():
                try:
                    self.executors[market_id] = MarketExecutor(
                        market_id=market_id,
                        exchange=self.exchange,
                        info=self.info,
                        account_address=HL_ACCOUNT,
                        coin=cfg["coin"],
                        leverage=cfg["leverage"],
                        capital_pct=cfg["capital_pct"],
                        sz_decimals=cfg["sz_decimals"],
                    )
                except Exception as e:
                    print(f"  [EXEC] ⚠️ {market_id} 初始化失敗: {e}")

            self._initialized = True
            print(f"  [EXEC] ✅ 已初始化 {len(self.executors)} 個市場執行器")
            return True

        except Exception as e:
            print(f"  [EXEC] ❌ 初始化失敗: {e}")
            import traceback
            traceback.print_exc()
            return False

    def get_executor(self, market_id: str) -> Optional[MarketExecutor]:
        return self.executors.get(market_id)

    def get_total_pnl(self) -> float:
        return sum(e.total_pnl for e in self.executors.values())

    def get_total_unrealized_pnl(self) -> float:
        return sum(e.get_unrealized_pnl() for e in self.executors.values())

    def get_account_balance(self) -> float:
        """查詢帳戶總餘額"""
        if not self.info:
            return 0.0
        try:
            state = self.info.user_state(HL_ACCOUNT)
            return float(state.get("marginSummary", {}).get("accountValue", "0"))
        except Exception:
            return 0.0

    def close_all(self, reason: str = "緊急平倉"):
        """關閉所有持倉"""
        for market_id, executor in self.executors.items():
            if executor.current_position is not None:
                executor.close_position(reason)

    def print_status(self):
        """打印所有市場狀態"""
        print("\n" + "=" * 70)
        print("  多市場持倉狀態")
        print("=" * 70)
        for market_id, executor in self.executors.items():
            print(f"  {executor.status_str()}")
        total_pnl = self.get_total_pnl()
        total_upnl = self.get_total_unrealized_pnl()
        balance = self.get_account_balance()
        print("-" * 70)
        print(
            f"  總計: 已實現=${total_pnl:+.2f} | "
            f"未實現=${total_upnl:+.2f} | "
            f"帳戶=${balance:.2f}"
        )
        print("=" * 70)
