path = "/root/multi-market-bot/executor.py"
with open(path, "r") as f: lines = f.readlines()
new_lines = []
for line in lines:
    if "capital: float," in line:
        new_lines.append(line.replace("capital: float,", "capital_pct: float,"))
    elif "self.capital = capital" in line:
        new_lines.append(line.replace("self.capital = capital", "self.capital_pct = capital_pct"))
    elif "usd = position_usd or self.capital" in line:
        new_lines.append("        from config import RISK_FREE_MARGIN_PCT\n")
        new_lines.append("        # 動態獲取帳戶價值\n")
        new_lines.append("        try:\n")
        new_lines.append("            state = self.info.user_state(self.account_address)\n")
        new_lines.append("            account_value = float(state.get('marginSummary', {}).get('accountValue', '0'))\n")
        new_lines.append("        except: account_value = 400.0\n")
        new_lines.append("        usd = position_usd or (account_value * self.capital_pct * (1 - RISK_FREE_MARGIN_PCT))\n")
    elif "capital=cfg[\"capital\"]," in line:
        new_lines.append(line.replace("capital=cfg[\"capital\"],", "capital_pct=cfg[\"capital_pct\"],"))
    else:
        new_lines.append(line)
with open(path, "w") as f: f.writelines(new_lines)
