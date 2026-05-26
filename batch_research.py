# NumPy 2.0 兼容性补丁 (修复 empyrical 库调用 np.NINF 崩溃问题)
import numpy as np
if not hasattr(np, "NINF"):
    np.NINF = -np.inf

import os
import csv
import time
from datetime import datetime, timedelta
from vnpy.trader.constant import Interval, Exchange
from vnpy.trader.object import HistoryRequest
from vnpy.trader.datafeed import get_datafeed
from vnpy.trader.database import get_database
from vnpy_ctastrategy.backtesting import BacktestingEngine

# 引入我们的极致多因子仓位限制策略
from strategies.stock_quant_strategy import StockQuantStrategy


def download_stock_data(symbol: str, exchange_str: str, start_date: datetime):
    """
    全自动从 TuShare 下载指定股票的历史日线数据并保存到本地数据库
    【工业级增量更新版】：
    1. 若本地无数据，自动全量下载自 start_date 至今的全部历史数据。
    2. 若本地已有最新数据，自动秒级跳过，不耗费任何API积分。
    3. 若本地数据偏旧，仅向 TuShare 请求下载缺失的那几天（增量补丁），并无缝拼接导入！
    """
    db = get_database()
    exchange = Exchange(exchange_str)
    
    # ── 1. 检查本地数据库中这只股票的历史数据 ──
    existing_bars = db.load_bar_data(symbol, exchange, Interval.DAILY, start_date, datetime.now())
    
    fetch_start = start_date
    if existing_bars:
        last_bar_datetime = existing_bars[-1].datetime.replace(tzinfo=None)
        
        # 判断本地数据是否已经是最新（避开交易日盘中及非交易日）
        if datetime.now() - last_bar_datetime < timedelta(days=1):
            print(f"[数据最新] {symbol}.{exchange_str} 本地数据已是最新(至 {last_bar_datetime.strftime('%Y-%m-%d')})，无需下载。")
            return True
        elif datetime.now().weekday() >= 5 and datetime.now() - last_bar_datetime < timedelta(days=3):
            # 周末（周六日），且本地已更新到周五最新收盘
            print(f"[数据最新] {symbol}.{exchange_str} 周末无需更新，本地已到最新周五(至 {last_bar_datetime.strftime('%Y-%m-%d')})。")
            return True
            
        # 本地数据偏旧：启动【增量补齐】
        fetch_start = last_bar_datetime + timedelta(days=1)
        print(f"[增量更新] {symbol}.{exchange_str} 本地数据最新至 {last_bar_datetime.strftime('%Y-%m-%d')}，仅抓取之后至今的增量数据...")
    else:
        print(f"[全量下载] {symbol}.{exchange_str} 本地无数据，将全量下载自 {start_date.strftime('%Y-%m-%d')} 至今的全部历史数据...")

    # ── 2. 线上精确下载（仅请求缺失日期段） ──
    datafeed = get_datafeed()
    datafeed.init()
    
    req = HistoryRequest(
        symbol=symbol,
        exchange=exchange,
        start=fetch_start,  # 动态增量起始时间！
        end=datetime.now(),
        interval=Interval.DAILY
    )
    
    bars = datafeed.query_bar_history(req)
    
    if bars:
        db.save_bar_data(bars)
        print(f"[OK] 成功补充 {symbol}.{exchange_str} 增量历史数据：{len(bars)} 条！")
        time.sleep(0.2)  # 频控友好保护
        return True
    else:
        # 如果TuShare接口返回空，可能因为尚未收盘无新数据，亦视为已最新
        print(f"[数据最新] {symbol}.{exchange_str} 线上无更多新成交，本地已是最新。")
        return True


def run_single_backtest(symbol: str, exchange_str: str, start_date: datetime, end_date: datetime):
    """
    为单只股票运行 StockQuantStrategy 策略回测并返回核心数据统计
    """
    vt_symbol = f"{symbol}.{exchange_str}"
    print(f"\n[运行回测] 开始为 {vt_symbol} 运行量化回测...")
    
    # 实例化 VeighNa 核心回测引擎
    engine = BacktestingEngine()
    
    # 设置回测参数
    engine.set_parameters(
        vt_symbol=vt_symbol,
        interval=Interval.DAILY,
        start=start_date,
        end=end_date,
        rate=0.0003,       # 万三手续费率
        slippage=0.01,     # A股一分钱滑点
        size=1.0,          # 股票合约乘数为 1.0
        pricetick=0.01,    # 最小价格变动一分钱
        capital=1000000.0, # 起始资金 100 万
    )
    
    # 挂载策略
    engine.add_strategy(StockDoubleMaStrategy, {})
    
    # 载入本地数据并执行回测
    engine.load_data()
    engine.run_backtesting()
    
    # 计算统计指标
    engine.calculate_result()
    stats = engine.calculate_statistics(output=False)
    
    if not stats:
        print(f"[WARNING] {vt_symbol} 回测失败，可能在此时间范围内本地数据库没有数据，请先抓取数据。")
        return None
        
    return stats


def main():
    # ── 1. 定义您想要批量验证的 A股 股票列表 ──────────────────────
    stocks_to_test = [
        ("000630", "SZSE"),  # 铜陵有色
        ("000001", "SZSE"),  # 平安银行
        ("600519", "SSE"),   # 贵州茅台
        ("002594", "SZSE"),  # 比亚迪
        ("601318", "SSE"),   # 中国平安
    ]
    
    # ── 2. 定义回测的时间窗口 ──────────────────────────────────
    start_time = datetime(2018, 5, 19)
    end_time = datetime(2026, 5, 25)
    
    # ── 3. 全自动智能增量缓存校验与精确抓取 ────────────────────
    print("=== [第一阶段：数据自动补充与抓取] ===")
    for symbol, exchange_str in stocks_to_test:
        download_stock_data(symbol, exchange_str, start_time)
        
    # ── 4. 批量运行回测并汇总结果 ──────────────────────────────
    print("\n=== [第二阶段：多股批量自动回测] ===")
    results_summary = []
    
    for symbol, exchange_str in stocks_to_test:
        stats = run_single_backtest(symbol, exchange_str, start_time, end_time)
        if stats:
            results_summary.append({
                "股票代码": f"{symbol}.{exchange_str}",
                "起始资金": f"{stats['capital']:,.2f}",
                "结束资金": f"{stats['end_balance']:,.2f}",
                "总收益率": f"{stats['total_return']:.2f}%",
                "年化收益": f"{stats['annual_return']:.2f}%",
                "最大回撤": f"{stats['max_drawdown']:,.2f}",
                "百分比最大回撤": f"{stats['max_ddpercent']:.2f}%",
                "总盈亏": f"{stats['total_net_pnl']:,.2f}",
                "总交易次数": stats["total_trade_count"],
                "夏普比率": f"{stats['sharpe_ratio']:.2f}",
            })
            
    # ── 5. 导出分析对比 CSV 报表 ──────────────────────────
    report_filename = "batch_backtest_report.csv"
    if results_summary:
        headers = list(results_summary[0].keys())
        with open(report_filename, mode="w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(results_summary)
            
        print(f"\n=== [全自动化批量回测大功告成！] ===")
        print(f"[报告生成] 所有股票的回测核心指标已自动生成对比报表：{os.path.abspath(report_filename)}")
        print("\n[对比摘要] 下面是回测对比摘要列表：")
        print(f"{'股票代码':<12} | {'总收益率':<10} | {'年化收益':<10} | {'百分比最大回撤':<14} | {'夏普比率':<8}")
        print("-" * 65)
        for r in results_summary:
            print(f"{r['股票代码']:<12} | {r['总收益率']:<10} | {r['年化收益']:<10} | {r['百分比最大回撤']:<14} | {r['夏普比率']:<8}")
            
if __name__ == "__main__":
    main()
