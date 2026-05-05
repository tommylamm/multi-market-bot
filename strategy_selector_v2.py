import time, json, os
import numpy as np
from dataclasses import dataclass, field
from typing import Optional, List, Dict
from strategies import STRATEGY_MAP, Indicators
from strategies.indicators_extended import ExtendedIndicators

@dataclass
class TradeRecord:
    strategy_name: str
    direction: str
    entry_price: float
    exit_price: float
    pnl: float
    timestamp: float = 0.0
    @property
    def is_win(self) -> bool: return self.pnl > 0

@dataclass
class StrategyPerformance:
    name: str
    trades: list = field(default_factory=list)
    consecutive_losses: int = 0
    total_trades: int = 0
    @property
    def win_rate(self) -> float:
        if not self.trades: return 0.5
        wins = sum(1 for t in self.trades[-20:] if t.is_win)
        return wins / len(self.trades[-20:])

class AdaptiveStrategySelector:
    def __init__(self, market_configs: dict):
        self.market_configs = market_configs
        self.performances = {}
        self.active_strategies = {}
        self.strategy_instances = {} # 改為按市場存儲實例: {market_id: {strategy_name: instance}}
        self._initialize()
        self._load_performance()

    def _initialize(self):
        from config import STRATEGY_PARAMS
        for mid, cfg in self.market_configs.items():
            self.strategy_instances[mid] = {}
            cands = cfg.get("strategies", ["trend"])
            for sname in cands:
                if sname not in self.performances:
                    self.performances[sname] = StrategyPerformance(name=sname)
                
                if sname in STRATEGY_MAP:
                    # 傳入必要的 market_id 和 params
                    params = STRATEGY_PARAMS.get(sname, {})
                    self.strategy_instances[mid][sname] = STRATEGY_MAP[sname](market_id=mid, params=params)
            
            self.active_strategies[mid] = cands[0]

    def scan_and_update(self, market_id, closes, highs, lows, volumes):
        if len(closes) < 50: return
        
        adx = Indicators.adx(highs, lows, closes, 14)[-1]
        rsi = Indicators.rsi(closes, 14)[-1]
        bb_upper, bb_mid, bb_lower = Indicators.bollinger_bands(closes, 20, 2)
        bb_width = (bb_upper[-1] - bb_lower[-1]) / bb_mid[-1]
        
        candidates = self.market_configs.get(market_id, {}).get("strategies", ["trend"])
        best_score = -1.0
        current_active = self.active_strategies.get(market_id, candidates[0])
        best_strategy = current_active
        
        for sname in candidates:
            perf = self.performances.get(sname)
            if not perf: continue
            
            score = perf.win_rate
            if sname == "brooks_trend" and adx > 25: score += 0.2
            if sname == "anti_market_bb" and (rsi > 70 or rsi < 30): score += 0.2
            if sname == "sperandeo_reversal" and bb_width > 0.05: score += 0.1
            
            if score > best_score:
                best_score = score
                best_strategy = sname
        
        if best_strategy != current_active:
            print(f"  [Scanner] {market_id} 策略切換: {current_active} -> {best_strategy} (Score: {best_score:.2f})")
            self.active_strategies[market_id] = best_strategy


    def get_active_strategy_name(self, market_id):
        return self.active_strategies.get(market_id, "trend")

    def get_active_strategy(self, market_id):

        sname = self.active_strategies.get(market_id, "trend")
        return self.strategy_instances.get(market_id, {}).get(sname)

    def record_trade(self, strategy_name: str, direction: str, entry_px: float, exit_px: float, pnl: float):
        if strategy_name not in self.performances:
            self.performances[strategy_name] = StrategyPerformance(name=strategy_name)
        
        perf = self.performances[strategy_name]
        record = TradeRecord(strategy_name, direction, entry_px, exit_px, pnl, time.time())
        perf.trades.append(record)
        perf.total_trades += 1
        
        if pnl < 0: perf.consecutive_losses += 1
        else: perf.consecutive_losses = 0
        
        self._save_performance()

    def print_status(self):
        print("\n" + "="*50)
        print("📊 策略實戰勝率統計 (Strategy Performance)")
        print("-" * 50)
        print(f"{'策略名稱':<20} | {'勝率':<8} | {'交易次數':<8} | {'連損'}")
        print("-" * 50)
        for name, perf in self.performances.items():
            wr = f"{perf.win_rate*100:>6.1f}%"
            print(f"{name:<20} | {wr:<8} | {perf.total_trades:<8} | {perf.consecutive_losses}")
        print("="*50 + "\n")

    def _save_performance(self):
        data = {name: {"total_trades": p.total_trades, "consecutive_losses": p.consecutive_losses} 
                for name, p in self.performances.items()}
        try:
            with open("/root/multi-market-bot/strategy_performance_v2.json", "w") as f:
                json.dump(data, f, indent=2)
        except: pass

    def _load_performance(self):
        path = "/root/multi-market-bot/strategy_performance_v2.json"
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                    for name, d in data.items():
                        if name in self.performances:
                            self.performances[name].total_trades = d.get("total_trades", 0)
                            self.performances[name].consecutive_losses = d.get("consecutive_losses", 0)
            except: pass
