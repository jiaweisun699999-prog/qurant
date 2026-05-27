# -*- coding: utf-8 -*-
import time
from datetime import datetime, timedelta
from PySide6 import QtCore
from vnpy.trader.constant import Interval, Exchange
from vnpy.trader.object import HistoryRequest
from vnpy.trader.datafeed import get_datafeed
from vnpy.trader.database import get_database
from vnpy_ctastrategy.backtesting import BacktestingEngine


class BacktestWorker(QtCore.QThread):
    """
    泛型异步回测工作线程：基于 PySide6.Signal
    支持传入任何任意的策略类和对应的运行参数字典，0 硬编码！
    """
    log_signal = QtCore.Signal(str)
    result_signal = QtCore.Signal(tuple) # 发送元组 (result_dict, engine_object)
    finished_signal = QtCore.Signal(list)

    def __init__(self, stocks, start_date, end_date, strategy_class, strategy_params, params):
        super().__init__()
        self.stocks = stocks
        self.start_date = start_date
        self.end_date = end_date
        self.strategy_class = strategy_class
        self.strategy_params = strategy_params
        self.params = params
        self.is_running = True

    def run(self):
        db = get_database()
        datafeed = get_datafeed()
        datafeed.init()

        results = []

        # ── 1. 数据智能抓取阶段 ──
        self.log_signal.emit("=== [第一阶段：数据自动补充与抓取] ===")
        for symbol, exchange_str in self.stocks:
            if not self.is_running:
                break

            exchange = Exchange(exchange_str)
            self.log_signal.emit(f"[智能缓存校验] 检查 {symbol}.{exchange_str} 本地数据...")
            
            existing_bars = db.load_bar_data(symbol, exchange, Interval.DAILY, self.start_date, datetime.now())
            
            fetch_start = self.start_date
            need_download = True
            
            if existing_bars:
                last_bar_datetime = existing_bars[-1].datetime.replace(tzinfo=None)
                # 校验数据新鲜度
                if datetime.now() - last_bar_datetime < timedelta(days=1):
                    self.log_signal.emit(f"  -> 本地数据已是最新 (至 {last_bar_datetime.strftime('%Y-%m-%d')})，跳过下载。")
                    need_download = False
                elif datetime.now().weekday() >= 5 and datetime.now() - last_bar_datetime < timedelta(days=3):
                    self.log_signal.emit(f"  -> 周末无需更新，本地数据已至最新周五 (至 {last_bar_datetime.strftime('%Y-%m-%d')})。")
                    need_download = False
                else:
                    fetch_start = last_bar_datetime + timedelta(days=1)
                    self.log_signal.emit(f"  -> 本地数据偏旧，增量起止时间：{fetch_start.strftime('%Y-%m-%d')}。")

            if need_download:
                self.log_signal.emit(f"  -> 正在从 TuShare 增量下载 {symbol}.{exchange_str} 数据...")
                req = HistoryRequest(
                    symbol=symbol,
                    exchange=exchange,
                    start=fetch_start,
                    end=datetime.now(),
                    interval=Interval.DAILY
                )
                bars = datafeed.query_bar_history(req)
                if bars:
                    db.save_bar_data(bars)
                    self.log_signal.emit(f"  -> [OK] 成功补充 {symbol}.{exchange_str} 数据：{len(bars)} 条！")
                    time.sleep(0.2)
                else:
                    self.log_signal.emit(f"  -> [OK] 接口未返回更多新成交，本地已是最新。")

        # ── 2. 批量回测阶段 ──
        self.log_signal.emit("\n=== [第二阶段：多股批量自动回测] ===")
        for symbol, exchange_str in self.stocks:
            if not self.is_running:
                break

            vt_symbol = f"{symbol}.{exchange_str}"
            self.log_signal.emit(f"[运行中] 正在为 {vt_symbol} 跑回测算法...")

            engine = BacktestingEngine()
            engine.set_parameters(
                vt_symbol=vt_symbol,
                interval=Interval.DAILY,
                start=self.start_date,
                end=self.end_date,
                rate=0.0003,
                slippage=0.01,
                size=1.0,
                pricetick=0.01,
                capital=self.params["total_capital"],
            )
            
            engine.add_strategy(self.strategy_class, self.strategy_params)
            engine.load_data()
            engine.run_backtesting()
            
            engine.calculate_result()
            stats = engine.calculate_statistics(output=False)

            if stats:
                item_result = {
                    "vt_symbol": vt_symbol,
                    "start_date": str(stats["start_date"]),
                    "end_date": str(stats["end_date"]),
                    "total_days": str(stats["total_days"]),
                    "profit_days": str(stats["profit_days"]),
                    "loss_days": str(stats["loss_days"]),
                    "capital": f"{stats['capital']:,.2f}",
                    "end_balance": f"{stats['end_balance']:,.2f}",
                    "total_net_pnl": f"{stats['total_net_pnl']:,.2f}",
                    "total_commission": f"{stats['total_commission']:,.2f}",
                    "total_return": f"{stats['total_return']:.2f}%",
                    "annual_return": f"{stats['annual_return']:.2f}%",
                    "max_drawdown": f"{stats['max_drawdown']:,.2f}",
                    "max_ddpercent": f"{stats['max_ddpercent']:.2f}%",
                    "max_drawdown_duration": str(stats["max_drawdown_duration"]),
                    "total_trade_count": str(stats["total_trade_count"]),
                    "sharpe_ratio": f"{stats['sharpe_ratio']:.2f}",
                }
                self.log_signal.emit(f"  -> {vt_symbol} 回测完成！总收益：{item_result['total_return']}，最大回撤：{item_result['max_ddpercent']}")
                self.result_signal.emit((item_result, engine))
                results.append(item_result)
            else:
                self.log_signal.emit(f"  -> [WARNING] {vt_symbol} 回测失败，本地无数据。")

        self.finished_signal.emit(results)
