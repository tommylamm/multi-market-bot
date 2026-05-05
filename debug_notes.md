# 為什麼其他市場不開倉的分析

## 代碼邏輯分析

代碼邏輯本身是正確的 — 每個市場都有獨立的 WebSocket 訂閱、策略實例和執行器。
問題不在代碼架構，而在**策略信號條件太嚴格**。

## 各市場策略分析

### BTC (trend, 15m)
- 條件：EMA(20) > EMA(50) + MACD 柱狀圖 > 0 且加速 + 價格 > EMA fast + 成交量 > 110% 平均
- BTC 波動大、成交量穩定，容易滿足條件 ✅

### ETH (mean_reversion, 5m)
- 條件：RSI < 25 **且** 價格 <= 布林下軌 **同時**
- RSI < 25 已經很極端，加上布林下軌的條件，非常難同時滿足
- **問題：條件太嚴格**

### SOL (breakout, 5m)
- 條件：價格突破近 48 根 K 線高點 + 1 ATR **且** 成交量 > 1.5x 平均 **且** 美盤時段(UTC 13-21)
- 48 根 5m K 線 = 4 小時的高低點
- 需要突破 4 小時高點 + 1 ATR，這在 5m 時間框架上很難
- **問題：lookback_period=48 對 5m 太長，且 session_filter 限制了交易時間**

### OIL (trend, 15m)
- 和 BTC 一樣的策略
- 但 OIL 成交量可能很低（V=527.5），如果 volume_confirm=True 且成交量不穩定
- **問題：volume_confirm 在低流動性市場可能阻止信號**

### PAXG (mean_reversion, 5m)
- 和 ETH 一樣的策略
- PAXG（黃金）波動更小，RSI 更難到 25 以下
- **問題：RSI 閾值太極端**

## 解決方案

1. ETH/PAXG (mean_reversion): 放寬 RSI 閾值（25→30, 75→70）
2. SOL (breakout): 縮短 lookback_period（48→20），降低 volume_spike_mult（1.5→1.2）
3. OIL (trend): 關閉 volume_confirm 或降低閾值
4. 或者：為 ETH/SOL/PAXG 換用 trend 策略（已證明在 BTC 上能開倉）
