path = "/root/multi-market-bot/strategy_selector_v2.py"
with open(path, "r") as f: content = f.read()

# 增加 get_active_strategy_name 方法
new_method = """
    def get_active_strategy_name(self, market_id):
        return self.active_strategies.get(market_id, "trend")

    def get_active_strategy(self, market_id):
"""

if "def get_active_strategy_name" not in content:
    content = content.replace("    def get_active_strategy(self, market_id):", new_method)

with open(path, "w") as f: f.write(content)
