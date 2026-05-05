"""
自適應策略切換管理器 (Adaptive Strategy Selector)
根據每個策略的近期績效自動切換到表現最好的策略

切換邏輯：
1. 每個市場有 2-3 個候選策略
2. 系統追蹤每個策略最近 N 筆交易的勝率和盈虧比
3. 當前策略連虧 3 次 → 自動切換到績效最好的候選策略
4. 每 10 筆交易重新評估一次策略表現
5. 新策略有 5 筆交易的「觀察期」，觀察期內不切換
"""
import time
import json
import os
from dataclasses import dataclass, field
from typing import Optional
from strategies import STRATEGY_MAP


@dataclass
class TradeRecord:
    """單筆交易記錄"""
    strategy_name: str
    direction: str
    entry_price: float
    exit_price: float
    pnl: float  # 盈虧金額
    timestamp: float = 0.0

    @property
    def is_win(self) -> bool:
        return self.pnl > 0


@dataclass
class StrategyPerformance:
    """策略績效追蹤"""
    name: str
    trades: list = field(default_factory=list)
    consecutive_losses: int = 0
    total_trades: int = 0
    is_active: bool = False
    activated_at: float = 0.0
    trades_since_activation: int = 0

    @property
    def recent_win_rate(self) -> float:
        """最近 10 筆交易的勝率"""
        recent = self.trades[-10:] if self.trades else []
        if not recent:
            return 0.5  # 沒有記錄時假設 50%
        wins = sum(1 for t in recent if t.is_win)
        return wins / len(recent)

    @property
    def recent_profit_factor(self) -> float:
        """最近 10 筆交易的盈虧比"""
        recent = self.trades[-10:] if self.trades else []
        if not recent:
            return 1.0
        total_profit = sum(t.pnl for t in recent if t.pnl > 0)
        total_loss = abs(sum(t.pnl for t in recent if t.pnl < 0))
        if total_loss == 0:
            return 3.0  # 沒有虧損，給最高分
        return min(total_profit / total_loss, 3.0)

    @property
    def score(self) -> float:
        """
        綜合評分 (0~100)
        = 勝率 * 50 + 盈虧比 * 30 + 活躍度加成
        """
        wr_score = self.recent_win_rate * 50
        pf_score = min(self.recent_profit_factor, 2.0) / 2.0 * 30
        # 有更多交易記錄的策略稍微加分（數據更可靠）
        data_bonus = min(len(self.trades) / 10, 1.0) * 10
        # 連虧懲罰
        loss_penalty = self.consecutive_losses * 5
        return max(wr_score + pf_score + data_bonus - loss_penalty, 0)


class AdaptiveStrategySelector:
    """
    自適應策略選擇器
    為每個市場管理多個候選策略，根據績效自動切換
    """

    def __init__(self, market_configs: dict):
        """
        market_configs: {
            "BTC": {
                "strategies": ["trend", "rsi_pullback", "ema_momentum"],
                "default": "trend",
                ...
            }
        }
        """
        self.market_configs = market_configs
        self.performances: dict[str, dict[str, StrategyPerformance]] = {}
        self.active_strategies: dict[str, str] = {}
        self.strategy_instances: dict[str, dict] = {}

        # 切換參數
        self.max_consecutive_losses = 3  # 連虧 N 次觸發切換
        self.min_trades_before_switch = 5  # 觀察期（新策略至少跑 N 筆）
        self.review_interval = 10  # 每 N 筆交易重新評估

        self._initialize()

    def _initialize(self):
        """初始化所有市場的策略追蹤"""
        for market_id, cfg in self.market_configs.items():
            strategies = cfg.get("strategies", [cfg.get("strategy", "trend")])
            default = cfg.get("default", strategies[0])

            self.performances[market_id] = {}
            for strat_name in strategies:
                perf = StrategyPerformance(name=strat_name)
                if strat_name == default:
                    perf.is_active = True
                    perf.activated_at = time.time()
                self.performances[market_id][strat_name] = perf

            self.active_strategies[market_id] = default

            # 創建策略實例
            self.strategy_instances[market_id] = {}
            for strat_name in strategies:
                strat_class = STRATEGY_MAP.get(strat_name)
                if strat_class:
                    params = cfg.get("strategy_params", {}).get(strat_name, {})
                    self.strategy_instances[market_id][strat_name] = strat_class(
                        market_id, params
                    )

        # 嘗試載入歷史績效
        self._load_performance()

    def get_active_strategy(self, market_id: str):
        """獲取市場當前活躍的策略實例"""
        strat_name = self.active_strategies.get(market_id)
        if strat_name and market_id in self.strategy_instances:
            return self.strategy_instances[market_id].get(strat_name)
        return None

    def get_active_strategy_name(self, market_id: str) -> str:
        """獲取市場當前活躍的策略名稱"""
        return self.active_strategies.get(market_id, "unknown")

    def record_trade(self, market_id: str, direction: str,
                     entry_price: float, exit_price: float, pnl: float):
        """
        記錄一筆交易結果，並檢查是否需要切換策略
        """
        strat_name = self.active_strategies.get(market_id)
        if not strat_name or market_id not in self.performances:
            return

        perf = self.performances[market_id].get(strat_name)
        if not perf:
            return

        # 記錄交易
        record = TradeRecord(
            strategy_name=strat_name,
            direction=direction,
            entry_price=entry_price,
            exit_price=exit_price,
            pnl=pnl,
            timestamp=time.time(),
        )
        perf.trades.append(record)
        perf.total_trades += 1
        perf.trades_since_activation += 1

        # 更新連虧計數
        if pnl > 0:
            perf.consecutive_losses = 0
        else:
            perf.consecutive_losses += 1

        # 檢查是否需要切換策略
        should_switch = False
        reason = ""

        # 條件 1：連虧超過閾值
        if perf.consecutive_losses >= self.max_consecutive_losses:
            should_switch = True
            reason = f"連虧{perf.consecutive_losses}次"

        # 條件 2：每 N 筆交易重新評估
        if perf.trades_since_activation >= self.review_interval:
            if perf.recent_win_rate < 0.35:
                should_switch = True
                reason = f"勝率過低({perf.recent_win_rate:.0%})"

        if should_switch and perf.trades_since_activation >= self.min_trades_before_switch:
            self._switch_strategy(market_id, reason)

        # 保存績效數據
        self._save_performance()

    def _switch_strategy(self, market_id: str, reason: str):
        """切換到表現最好的候選策略"""
        current = self.active_strategies[market_id]
        candidates = self.performances[market_id]

        # 找到評分最高的非當前策略
        best_name = None
        best_score = -1

        for name, perf in candidates.items():
            if name == current:
                continue
            score = perf.score
            if score > best_score:
                best_score = score
                best_name = name

        if best_name:
            # 停用當前策略
            candidates[current].is_active = False

            # 啟用新策略
            self.active_strategies[market_id] = best_name
            new_perf = candidates[best_name]
            new_perf.is_active = True
            new_perf.activated_at = time.time()
            new_perf.trades_since_activation = 0
            new_perf.consecutive_losses = 0

            print(f"  [策略切換] {market_id}: {current} → {best_name}")
            print(f"    原因: {reason}")
            print(f"    {current} 評分: {candidates[current].score:.1f}")
            print(f"    {best_name} 評分: {best_score:.1f}")

    def get_status(self) -> dict:
        """獲取所有市場的策略狀態"""
        status = {}
        for market_id in self.market_configs:
            active = self.active_strategies[market_id]
            perf = self.performances[market_id][active]
            candidates = list(self.performances[market_id].keys())
            status[market_id] = {
                "active": active,
                "candidates": candidates,
                "win_rate": f"{perf.recent_win_rate:.0%}",
                "profit_factor": f"{perf.recent_profit_factor:.2f}",
                "consecutive_losses": perf.consecutive_losses,
                "total_trades": perf.total_trades,
                "score": f"{perf.score:.1f}",
            }
        return status

    def print_status(self):
        """打印策略狀態報告"""
        print("\n  ╔═══ 策略狀態 ═══╗")
        for market_id, info in self.get_status().items():
            active = info["active"]
            others = [c for c in info["candidates"] if c != active]
            print(f"  ║ {market_id:5s} │ 🎯 {active:15s} │ "
                  f"WR={info['win_rate']:>4s} │ "
                  f"PF={info['profit_factor']:>5s} │ "
                  f"連虧={info['consecutive_losses']}")
            if others:
                print(f"  ║       │ 候補: {', '.join(others)}")
        print("  ╚═══════════════╝\n")

    def _save_performance(self):
        """保存績效數據到文件"""
        data = {}
        for market_id, strategies in self.performances.items():
            data[market_id] = {
                "active": self.active_strategies[market_id],
                "strategies": {},
            }
            for name, perf in strategies.items():
                data[market_id]["strategies"][name] = {
                    "total_trades": perf.total_trades,
                    "consecutive_losses": perf.consecutive_losses,
                    "trades_since_activation": perf.trades_since_activation,
                    "trades": [
                        {
                            "direction": t.direction,
                            "entry_price": t.entry_price,
                            "exit_price": t.exit_price,
                            "pnl": t.pnl,
                            "timestamp": t.timestamp,
                        }
                        for t in perf.trades[-20:]  # 只保留最近 20 筆
                    ],
                }

        try:
            filepath = os.path.join(os.path.dirname(__file__), "strategy_performance.json")
            with open(filepath, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"  [策略選擇器] 保存績效失敗: {e}")

    def _load_performance(self):
        """從文件載入歷史績效"""
        filepath = os.path.join(os.path.dirname(__file__), "strategy_performance.json")
        if not os.path.exists(filepath):
            return

        try:
            with open(filepath, "r") as f:
                data = json.load(f)

            for market_id, market_data in data.items():
                if market_id not in self.performances:
                    continue

                # 恢復活躍策略
                saved_active = market_data.get("active")
                if saved_active and saved_active in self.performances[market_id]:
                    self.active_strategies[market_id] = saved_active
                    # 更新 is_active 標記
                    for name, perf in self.performances[market_id].items():
                        perf.is_active = (name == saved_active)

                # 恢復交易記錄
                for name, strat_data in market_data.get("strategies", {}).items():
                    if name not in self.performances[market_id]:
                        continue
                    perf = self.performances[market_id][name]
                    perf.total_trades = strat_data.get("total_trades", 0)
                    perf.consecutive_losses = strat_data.get("consecutive_losses", 0)
                    perf.trades_since_activation = strat_data.get("trades_since_activation", 0)

                    for t in strat_data.get("trades", []):
                        record = TradeRecord(
                            strategy_name=name,
                            direction=t["direction"],
                            entry_price=t["entry_price"],
                            exit_price=t["exit_price"],
                            pnl=t["pnl"],
                            timestamp=t.get("timestamp", 0),
                        )
                        perf.trades.append(record)

            print("  [策略選擇器] 已載入歷史績效數據")
        except Exception as e:
            print(f"  [策略選擇器] 載入績效失敗: {e}")
