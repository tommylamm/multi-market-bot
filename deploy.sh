#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# 多市場交易系統 v1.0 — 一鍵部署腳本
# 用法: bash deploy.sh
# ═══════════════════════════════════════════════════════════════

set -e

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Multi-Market Trading System v1.0 — 部署腳本               ║"
echo "╚══════════════════════════════════════════════════════════════╝"

# 1. 停止舊的 BTC bot（如果存在）
echo ""
echo ">>> 步驟 1: 停止舊的交易機器人..."
systemctl stop btcbot 2>/dev/null && echo "  已停止 btcbot" || echo "  btcbot 未運行"
systemctl disable btcbot 2>/dev/null || true

# 2. 安裝依賴
echo ""
echo ">>> 步驟 2: 安裝 Python 依賴..."
pip3 install -r /root/multi-market-bot/requirements.txt

# 3. 建立目錄
echo ""
echo ">>> 步驟 3: 建立目錄結構..."
mkdir -p /root/multi-market-bot/logs
mkdir -p /root/multi-market-bot/data

# 4. 檢查 .env 文件
echo ""
echo ">>> 步驟 4: 檢查環境配置..."
if [ ! -f /root/multi-market-bot/.env ]; then
    echo "  ⚠️  .env 文件不存在！"
    echo "  正在從舊的 btcbot 遷移密鑰..."

    # 嘗試從舊的 btcbot 環境文件遷移
    OLD_ENV=""
    if [ -f /root/btc-bot/.env ]; then
        OLD_ENV="/root/btc-bot/.env"
    elif [ -f /etc/systemd/system/btcbot.service ]; then
        OLD_ENV=$(grep "EnvironmentFile" /etc/systemd/system/btcbot.service | cut -d= -f2)
    fi

    if [ -n "$OLD_ENV" ] && [ -f "$OLD_ENV" ]; then
        # 提取密鑰
        HL_SECRET=$(grep -E "^HL_SECRET" "$OLD_ENV" | head -1 | cut -d= -f2-)
        HL_ACCOUNT=$(grep -E "^HL_ACCOUNT" "$OLD_ENV" | head -1 | cut -d= -f2-)

        if [ -n "$HL_SECRET" ] && [ -n "$HL_ACCOUNT" ]; then
            cat > /root/multi-market-bot/.env << EOF
HL_SECRET=${HL_SECRET}
HL_ACCOUNT=${HL_ACCOUNT}
TOTAL_CAPITAL=800
EOF
            echo "  ✅ 已從 $OLD_ENV 遷移密鑰"
        else
            echo "  ❌ 無法提取密鑰，請手動建立 .env 文件"
            echo "  參考: /root/multi-market-bot/.env.example"
            exit 1
        fi
    else
        echo "  ❌ 找不到舊的環境文件，請手動建立 .env 文件"
        echo "  參考: /root/multi-market-bot/.env.example"
        exit 1
    fi
fi

echo "  ✅ .env 文件已就緒"

# 5. 安裝 systemd 服務
echo ""
echo ">>> 步驟 5: 安裝 systemd 服務..."
cp /root/multi-market-bot/multi-market-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable multi-market-bot
echo "  ✅ 服務已安裝"

# 6. 啟動
echo ""
echo ">>> 步驟 6: 啟動交易系統..."
systemctl start multi-market-bot
sleep 3

# 7. 檢查狀態
echo ""
echo ">>> 步驟 7: 檢查運行狀態..."
if systemctl is-active --quiet multi-market-bot; then
    echo "  ✅ 系統已成功啟動！"
    echo ""
    echo "  常用命令:"
    echo "    查看日誌:  journalctl -u multi-market-bot -f"
    echo "    停止系統:  systemctl stop multi-market-bot"
    echo "    重啟系統:  systemctl restart multi-market-bot"
    echo "    查看狀態:  systemctl status multi-market-bot"
else
    echo "  ❌ 啟動失敗，查看日誌:"
    journalctl -u multi-market-bot --no-pager -n 30
fi

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  部署完成！                                                 ║"
echo "╚══════════════════════════════════════════════════════════════╝"
