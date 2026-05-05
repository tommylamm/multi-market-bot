"""
多市場多策略交易系統 v1.1
主程式入口 — 修復 shutdown 超時問題
"""

import asyncio
import os
import sys
import signal
import threading

# 確保模組路徑正確
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from portfolio_manager import PortfolioManager
from telegram_notifier import notify_system_shutdown


async def async_main():
    print("""
╔══════════════════════════════════════════════════════════════╗
║       Multi-Market Trading System v1.1                      ║
║       多市場多策略量化交易系統                                ║
║                                                              ║
║       Markets: BTC, ETH, SOL, OIL, PAXG                    ║
║       Strategies: Trend, Mean Reversion, Breakout           ║
╚══════════════════════════════════════════════════════════════╝
    """)

    pm = PortfolioManager()

    # 優雅退出
    shutdown_event = asyncio.Event()

    def shutdown_handler():
        print("\n\n  收到退出信號，正在安全關閉...")
        shutdown_event.set()

    loop = asyncio.get_event_loop()

    # 在 asyncio loop 中註冊信號
    try:
        loop.add_signal_handler(signal.SIGTERM, shutdown_handler)
        loop.add_signal_handler(signal.SIGINT, shutdown_handler)
    except NotImplementedError:
        # Windows 不支持 add_signal_handler
        signal.signal(signal.SIGTERM, lambda s, f: shutdown_handler())
        signal.signal(signal.SIGINT, lambda s, f: shutdown_handler())

    # 啟動主任務
    main_task = asyncio.create_task(pm.run())
    pm.start_price_monitor()

    # 等待 shutdown 信號或主任務完成
    shutdown_wait = asyncio.create_task(shutdown_event.wait())
    done, pending = await asyncio.wait(
        [main_task, shutdown_wait],
        return_when=asyncio.FIRST_COMPLETED,
    )

    # 收到退出信號
    if shutdown_event.is_set():
        print("  正在平倉所有持倉...")
        try:
            pm.executor.close_all("系統關閉")
        except Exception as e:
            print(f"  平倉時出錯: {e}")
        pm.print_status()

        uptime = pm.start_time and (__import__("time").time() - pm.start_time) / 3600 or 0
        notify_system_shutdown(
            total_pnl=pm.executor.get_total_pnl(),
            daily_pnl=pm.risk.daily_pnl,
            balance=pm.executor.get_account_balance(),
            total_trades=pm.total_trades,
            uptime_h=uptime,
        )

        # 停止數據源
        await pm.feed.stop()

        # 取消未完成的任務
        for task in pending:
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=3)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

    print("  系統已安全退出。")


def main():
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        print("\n  系統已安全退出。")
    except SystemExit:
        pass


if __name__ == "__main__":
    main()
