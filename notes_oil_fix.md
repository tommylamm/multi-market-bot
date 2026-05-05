# OIL (HIP-3) 修復筆記

## 發現的問題
1. `Info` 和 `Exchange` 初始化時沒有傳入 `perp_dexs=["", "flx"]`，導致 SDK 不認識 `flx:OIL`
2. `get_mid_price()` 調用 `all_mids()` 時需要指定 `dex="flx"` 才能取得 OIL 價格
3. `_sync_position()` 調用 `user_state()` 時需要指定 `dex="flx"` 才能看到 OIL 持倉

## OIL 合約配置（從 API 獲取）
- szDecimals: 3（不是 config.py 中的 1！需要修正）
- maxLeverage: 15
- onlyIsolated: True（只支持隔離保證金）
- marginMode: strictIsolated

## 需要修正的地方
1. ✅ executor.py: Info/Exchange 初始化加入 perp_dexs
2. ✅ executor.py: get_mid_price 加入 dex 參數
3. ✅ executor.py: _sync_position 加入 dex 參數
4. ⚠️ config.py: OIL 的 sz_decimals 應該是 3（不是 1）
5. ✅ executor.py: _set_leverage 中全倉 fallback 不適用 OIL（onlyIsolated=True）
