"""
持倉同步模組 — 啟動時從 Hyperliquid 恢復持倉狀態
v1.0
"""
import requests
from config import HL_ACCOUNT, MARKETS

HL_INFO_URL = "https://api.hyperliquid.xyz/info"


class PositionSync:
    """從交易所恢復持倉 ，防止重啟後止損失效"""

    def __init__(self, account_address=None):
        self.account = account_address or HL_ACCOUNT

    def fetch_exchange_positions(self):
        """從 Hyperliquid 獲取所有持倉"""
        try:
            resp = requests.post(
                HL_INFO_URL,
                json={"type": "clearinghouseState", "user": self.account},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            positions = {}
            for asset_pos in data.get("assetPositions", []):
                p = asset_pos.get("position", {})
                szi = float(p.get("szi", 0))
                if szi == 0:
                    continue
                coin = p.get("coin", "")
                entry_px = float(p.get("entryPx", 0))
                unrealized_pnl = float(p.get("unrealizedPnl", 0))
                lev_info = p.get("leverage", {})
                lev_val = int(lev_info.get("value", 1)) if isinstance(lev_info, dict) else 1
                positions[coin] = {
                    "direction": "long" if szi > 0 else "short",
                    "size": abs(szi),
                    "entry_price": entry_px,
                    "unrealized_pnl": unrealized_pnl,
                    "leverage": lev_val,
                }
            return positions
        except Exception as e:
            print(f"  [PositionSync] 獲取交易所持倉失敗: {e}")
            return {}

    def sync_positions(self, local_positions, strategy_params=None):
        """
        將交易所持倉同步到本地 positions dict
        返回同步的持倉數量
        """
        exchange_positions = self.fetch_exchange_positions()
        synced = 0

        if not exchange_positions:
            print("  [PositionSync] 交易所無持倉，跳過同步")
            return 0

        # 獲取當前價格
        try:
            resp = requests.post(HL_INFO_URL, json={"type": "allMids"}, timeout=10)
            resp.raise_for_status()
            current_prices = {k: float(v) for k, v in resp.json().items()}
        except Exception:
            current_prices = {}

        for market_id, local_pos in local_positions.items():
            coin = market_id.split(":")[0] if ":" in market_id else market_id

            if coin in exchange_positions:
                ex_pos = exchange_positions[coin]

                # 本地已有持倉且方向一致，跳過
                if local_pos.get("direction") == ex_pos["direction"]:
                    continue

                entry_price = ex_pos["entry_price"]
                direction = ex_pos["direction"]
                current_price = current_prices.get(coin, entry_price)

                # 估算止損/止盈（保守的 2% 止損、3% 止盈）
                sl_pct = 0.02
                tp_pct = 0.03

                # 嘗試從策略參數獲取更精確的值
                market_cfg = MARKETS.get(market_id, {})
                strat_name = market_cfg.get("strategy", "trend")
                if strategy_params and strat_name in strategy_params:
                    params = strategy_params[strat_name]
                    sl_mult = params.get("atr_sl_mult", 1.5)
                    tp_mult = params.get("atr_tp_mult", 2.0)
                    est_atr_pct = 0.015  # 1h 級別典型 ATR
                    sl_pct = est_atr_pct * sl_mult
                    tp_pct = est_atr_pct * tp_mult

                if direction == "long":
                    sl_price = entry_price * (1 - sl_pct)
                    tp_price = entry_price * (1 + tp_pct)
                else:
                    sl_price = entry_price * (1 + sl_pct)
                    tp_price = entry_price * (1 - tp_pct)

                local_pos["direction"] = direction
                local_pos["entry_price"] = entry_price
                local_pos["sl_price"] = sl_price
                local_pos["tp_price"] = tp_price
                local_pos["bars_held"] = 1
                local_pos["entry_bar"] = 0
                local_pos["trailing_stop_price"] = 0.0

                synced += 1
                if entry_price > 0:
                    if direction == "long":
                        pnl = (current_price - entry_price) / entry_price * 100
                    else:
                        pnl = (entry_price - current_price) / entry_price * 100
                else:
                    pnl = 0
                print(
                    f"  [PositionSync] 恢復 {market_id}: "
                    f"{direction} @{entry_price:.4g} | "
                    f"SL={sl_price:.4g} TP={tp_price:.4g} | "
                    f"PnL={pnl:+.1f}%"
                )

        # 檢查未管理的持倉
        local_coins = set()
        for mid in local_positions:
            coin = mid.split(":")[0] if ":" in mid else mid
            local_coins.add(coin)

        for coin, ex_pos in exchange_positions.items():
            if coin not in local_coins:
                print(
                    f"  [PositionSync] 警告: 發現未管理的持倉 {coin} "
                    f"{ex_pos['direction']} {ex_pos['size']} @{ex_pos['entry_price']:.4g}"
                )

        print(f"  [PositionSync] 同步完成: 恢復 {synced} 個持倉")
        return synced
