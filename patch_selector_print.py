path = "/root/multi-market-bot/strategy_selector_v2.py"
with open(path, "r") as f: content = f.read()

# 在 AdaptiveStrategySelector 類中增加 print_status 方法
print_method = """
    def print_status(self):
        print("\n" + "="*50)
        print("📊 策略實戰勝率統計 (Strategy Performance)")
        print("-" * 50)
        print(f"{'策略名稱':<20} | {'勝率':<8} | {'交易次數':<8} | {'連損'}")
        print("-" * 50)
        for name, perf in self.performances.items():
            wr = f"{perf.win_rate*100:>6.1f}%"
            print(f"{name:<20} | {wr:<8} | {perf.total_trades:<8} | {perf.consecutive_losses}")
        print("="*50 + "\\n")
"""

# 插入到類定義的末尾（在 _load_performance 之前）
if "def print_status" not in content:
    content = content.replace("    def _load_performance(self):", print_method + "\n    def _load_performance(self):")

with open(path, "w") as f: f.write(content)
