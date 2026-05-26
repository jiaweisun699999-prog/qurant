# NumPy 2.0 兼容性补丁 (修复 empyrical 库调用 np.NINF 崩溃问题)
import numpy as np
if not hasattr(np, "NINF"):
    np.NINF = -np.inf

import os
import csv
import sys
import time
from datetime import datetime, timedelta
from PySide6 import QtWidgets, QtCore, QtGui

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
            
            # 挂载策略，并传入动态配置的专属参数！
            engine.add_strategy(self.strategy_class, self.strategy_params)
            engine.load_data()
            engine.run_backtesting()
            
            engine.calculate_result()
            stats = engine.calculate_statistics(output=False)

            if stats:
                # 满配所有专业分析指标字典
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
                self.result_signal.emit((item_result, engine)) # 传输计算数据和整个引擎对象
                results.append(item_result)
            else:
                self.log_signal.emit(f"  -> [WARNING] {vt_symbol} 回测失败，本地无数据。")

        self.finished_signal.emit(results)


class StrategyChartDialog(QtWidgets.QDialog):
    """
    至尊高档暗黑风：策略深度分析看板窗口 (完美融合 StatisticsMonitor 表格与 BacktesterChart 四画板图表)
    """
    def __init__(self, vt_symbol, statistics, result_df, parent=None):
        super().__init__(parent)
        self.vt_symbol = vt_symbol
        self.statistics = statistics
        self.result_df = result_df
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle(f"📊 策略回测图表与业绩看板 - {self.vt_symbol}")
        self.resize(1300, 850)
        self.setStyleSheet("background-color: #1a1a1a; color: #ffffff;")

        layout = QtWidgets.QHBoxLayout(self)

        # ── 左半部分：官方业绩统计表格 ──
        left_layout = QtWidgets.QVBoxLayout()
        lbl_stats = QtWidgets.QLabel("📋 官方深度业绩指标")
        lbl_stats.setStyleSheet("font-weight: bold; color: #00dddd; font-size: 13px; margin-bottom: 5px;")
        left_layout.addWidget(lbl_stats)

        from vnpy_ctabacktester.ui.widget import StatisticsMonitor
        self.statistics_monitor = StatisticsMonitor()
        self.statistics_monitor.setMinimumWidth(380)
        self.statistics_monitor.setMaximumWidth(430)
        self.statistics_monitor.setStyleSheet("""
            QTableWidget {
                gridline-color: #2e2e2e;
                background-color: #1e1e1e;
                color: #dddddd;
            }
            QHeaderView::section {
                background-color: #2b2b2b;
                color: #ffffff;
            }
        """)
        self.statistics_monitor.set_data(self.statistics)
        left_layout.addWidget(self.statistics_monitor)
        layout.addLayout(left_layout)

        # ── 右半部分：官方四大净值与盈亏分析图表 ──
        right_layout = QtWidgets.QVBoxLayout()
        lbl_chart = QtWidgets.QLabel("📈 净值回撤与盈亏分布图表 (账户净值/净值回撤/每日盈亏/盈亏分布)")
        lbl_chart.setStyleSheet("font-weight: bold; color: #00dddd; font-size: 13px; margin-bottom: 5px;")
        right_layout.addWidget(lbl_chart)

        from vnpy_ctabacktester.ui.widget import BacktesterChart
        self.chart = BacktesterChart()
        self.chart.set_data(self.result_df)
        right_layout.addWidget(self.chart)

        layout.addLayout(right_layout, stretch=2)


class StockDetailWindow(QtWidgets.QDialog):
    """
    个股回测复盘控制台窗口 (复用原生 UI 接口)
    """
    def __init__(self, vt_symbol, data_row, engine, main_engine, event_engine, parent=None):
        super().__init__(parent)
        self.vt_symbol = vt_symbol
        self.data_row = data_row
        self.engine = engine
        self.main_engine = main_engine
        self.event_engine = event_engine
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle(f"📊 个股回测复盘控制面板: {self.vt_symbol}")
        self.setMinimumSize(450, 320)
        self.setStyleSheet("background-color: #242424; color: #ffffff;")

        layout = QtWidgets.QVBoxLayout(self)

        info_group = QtWidgets.QGroupBox("📈 核心业绩摘要")
        info_layout = QtWidgets.QGridLayout(info_group)
        info_layout.addWidget(QtWidgets.QLabel("初始本金:"), 0, 0)
        info_layout.addWidget(QtWidgets.QLabel(self.data_row["capital"]), 0, 1)
        info_layout.addWidget(QtWidgets.QLabel("期末净值:"), 0, 2)
        info_layout.addWidget(QtWidgets.QLabel(self.data_row["end_balance"]), 0, 3)
        
        lbl_return = QtWidgets.QLabel("总收益率:")
        lbl_return.setStyleSheet("font-weight: bold; color: #ff3c3c;")
        info_layout.addWidget(lbl_return, 1, 0)
        info_layout.addWidget(QtWidgets.QLabel(self.data_row["total_return"]), 1, 1)

        lbl_dd = QtWidgets.QLabel("最大回撤:")
        lbl_dd.setStyleSheet("font-weight: bold; color: #50b4ff;")
        info_layout.addWidget(lbl_dd, 1, 2)
        info_layout.addWidget(QtWidgets.QLabel(self.data_row["max_ddpercent"]), 1, 3)
        layout.addWidget(info_group)

        btn_group = QtWidgets.QGroupBox("🔍 细节数据复盘与深度分析")
        btn_layout = QtWidgets.QGridLayout(btn_group)
        btn_layout.setSpacing(15)

        self.btn_trade = QtWidgets.QPushButton("📊 交易成交记录")
        self.btn_order = QtWidgets.QPushButton("📋 委托下单记录")
        self.btn_daily = QtWidgets.QPushButton("💰 每日盯市盈亏")
        self.btn_candle = QtWidgets.QPushButton("📈 策略分析图表") # 升级为多画板分析

        btn_qss = """
            QPushButton {
                background-color: #3b3b3b;
                color: #ffffff;
                border: 1px solid #555555;
                border-radius: 6px;
                padding: 12px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #008c8c;
                border-color: #00dddd;
            }
        """

        for btn in [self.btn_trade, self.btn_order, self.btn_daily, self.btn_candle]:
            btn.setStyleSheet(btn_qss)

        self.btn_trade.clicked.connect(self.show_trades)
        self.btn_order.clicked.connect(self.show_orders)
        self.btn_daily.clicked.connect(self.show_daily)
        self.btn_candle.clicked.connect(self.show_candle)

        btn_layout.addWidget(self.btn_trade, 0, 0)
        btn_layout.addWidget(self.btn_order, 0, 1)
        btn_layout.addWidget(self.btn_daily, 1, 0)
        btn_layout.addWidget(self.btn_candle, 1, 1)
        layout.addWidget(btn_group)

        close_btn = QtWidgets.QPushButton("返回批量列表")
        close_btn.setFixedHeight(35)
        close_btn.setStyleSheet("background-color: #555; color: #fff; border-radius: 4px;")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    def show_trades(self):
        try:
            from vnpy_ctabacktester.ui.widget import BacktestingResultDialog, BacktestingTradeMonitor
            dialog = BacktestingResultDialog(
                self.main_engine,
                self.event_engine,
                f"[{self.vt_symbol}] 回测成交记录",
                BacktestingTradeMonitor
            )
            dialog.update_data(self.engine.get_all_trades())
            dialog.exec()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "警告", f"加载成交记录失败，原因：\n{str(e)}")

    def show_orders(self):
        try:
            from vnpy_ctabacktester.ui.widget import BacktestingResultDialog, BacktestingOrderMonitor
            dialog = BacktestingResultDialog(
                self.main_engine,
                self.event_engine,
                f"[{self.vt_symbol}] 回测委托记录",
                BacktestingOrderMonitor
            )
            dialog.update_data(self.engine.get_all_orders())
            dialog.exec()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "警告", f"加载委托记录失败。")

    def show_daily(self):
        try:
            from vnpy_ctabacktester.ui.widget import BacktestingResultDialog, DailyResultMonitor
            dialog = BacktestingResultDialog(
                self.main_engine,
                self.event_engine,
                f"[{self.vt_symbol}] 每日盯市盈亏",
                DailyResultMonitor
            )
            dialog.update_data(self.engine.get_all_daily_results())
            dialog.exec()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "警告", f"加载每日盈亏失败。")

    def show_candle(self):
        """
        核心升级：调起极其炫丽的“多面板图表 + 20+深度业绩表格”至尊分析窗口！
        """
        try:
            result_df = self.engine.calculate_result()
            stats = self.engine.calculate_statistics(df=result_df, output=False)
            
            dialog = StrategyChartDialog(self.vt_symbol, stats, result_df, self)
            dialog.exec()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "警告", f"加载策略分析图表看板失败，原因：\n{str(e)}")


class BatchBacktestApp(QtWidgets.QMainWindow):
    """
    豪华暗黑风多股批量回测图形终端主窗口 (完美支持多策略动态发现与参数编辑)
    """
    def __init__(self, main_engine=None, event_engine=None):
        super().__init__()
        self.main_engine = main_engine
        self.event_engine = event_engine
        
        self.backtest_engines = {}
        self.results_data = {}
        
        # 缓存每个策略修改后的参数配置字典 {strategy_name: params_dict}
        self.strategy_settings = {}

        self.init_ui()
        self.init_strategy_combobox()

    def init_ui(self):
        self.setWindowTitle("A股极致多因子批量自动回测研究系统 (Batch Backtester)")
        self.resize(1200, 750)
        self.set_dark_theme()

        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QtWidgets.QHBoxLayout(central_widget)

        # ── 1. 左侧参数配置区 ──
        left_frame = QtWidgets.QFrame()
        left_frame.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        left_frame.setFixedWidth(350)
        left_layout = QtWidgets.QVBoxLayout(left_frame)
        
        left_layout.addWidget(QtWidgets.QLabel("📋 批量测试股票列表 (代码.交易所):"))
        self.stocks_edit = QtWidgets.QTextEdit()
        self.stocks_edit.setPlaceholderText("请输入股票，一行一个，格式例如:\n000630.SZSE\n000001.SZSE\n600519.SSE\n002594.SZSE\n601318.SSE")
        self.stocks_edit.setText("000630.SZSE\n000001.SZSE\n600519.SSE\n002594.SZSE\n601318.SSE")
        left_layout.addWidget(self.stocks_edit)

        # 📅 回测时间段选择
        date_group = QtWidgets.QGroupBox("📅 回测时间范围选择")
        date_layout = QtWidgets.QGridLayout(date_group)
        date_layout.addWidget(QtWidgets.QLabel("开始日期:"), 0, 0)
        self.start_date_edit = QtWidgets.QDateEdit(QtCore.QDate(2018, 5, 19))
        self.start_date_edit.setCalendarPopup(True)
        date_layout.addWidget(self.start_date_edit, 0, 1)
        
        date_layout.addWidget(QtWidgets.QLabel("结束日期:"), 1, 0)
        self.end_date_edit = QtWidgets.QDateEdit(QtCore.QDate(2026, 5, 25))
        self.end_date_edit.setCalendarPopup(True)
        date_layout.addWidget(self.end_date_edit, 1, 1)
        left_layout.addWidget(date_group)

        # 🎯 策略选择与参数配置区
        strat_group = QtWidgets.QGroupBox("🎯 策略库动态选择")
        strat_layout = QtWidgets.QVBoxLayout(strat_group)
        
        strat_layout.addWidget(QtWidgets.QLabel("选择交易策略:"))
        self.strategy_combo = QtWidgets.QComboBox()
        self.strategy_combo.setStyleSheet("background-color: #2b2b2b; color: #00dddd; padding: 4px; font-weight: bold;")
        strat_layout.addWidget(self.strategy_combo)
        
        self.config_param_btn = QtWidgets.QPushButton("⚙️ 配置所选策略运行参数")
        self.config_param_btn.setFixedHeight(35)
        self.config_param_btn.setStyleSheet("""
            QPushButton {
                background-color: #3b3b3b;
                color: #ffffff;
                border: 1px solid #666;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #008c8c;
                border-color: #00dddd;
            }
        """)
        self.config_param_btn.clicked.connect(self.configure_strategy_parameters)
        strat_layout.addWidget(self.config_param_btn)
        
        strat_layout.addWidget(self.config_param_btn)
        
        left_layout.addWidget(strat_group)

        # ⚙️ 通用回测参数微调
        engine_group = QtWidgets.QGroupBox("🛠️ 回测引擎参数微调")
        engine_layout = QtWidgets.QGridLayout(engine_group)
        
        engine_layout.addWidget(QtWidgets.QLabel("初始总资金 (元):"), 0, 0)
        self.capital_spin = QtWidgets.QDoubleSpinBox()
        self.capital_spin.setRange(10000.0, 100000000.0)
        self.capital_spin.setSingleStep(10000.0)
        self.capital_spin.setValue(1000000.0)
        self.capital_spin.setDecimals(1)
        engine_layout.addWidget(self.capital_spin, 0, 1)
        
        left_layout.addWidget(engine_group)

        # 控制按钮
        self.run_btn = QtWidgets.QPushButton("🚀 开始批量回测")
        self.run_btn.setFixedHeight(50)
        self.run_btn.setStyleSheet("""
            QPushButton {
                background-color: #008c8c;
                color: white;
                font-weight: bold;
                font-size: 14px;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #00aaaa;
            }
            QPushButton:disabled {
                background-color: #555555;
                color: #888888;
            }
        """)
        self.run_btn.clicked.connect(self.start_batch_backtest)
        left_layout.addWidget(self.run_btn)

        # ── 2. 右侧数据展示与日志区 ──
        right_layout = QtWidgets.QVBoxLayout()
        self.tab_widget = QtWidgets.QTabWidget()
        
        # 升级为17列全指标豪华报表表格
        self.table_widget = QtWidgets.QTableWidget()
        self.table_widget.setColumnCount(17)
        self.table_widget.setHorizontalHeaderLabels([
            "股票代码", "首个交易日", "最后交易日", "总交易日", "盈利交易日", 
            "亏损交易日", "起始资金", "结束资金", "总盈亏", "总手续费", 
            "总收益率", "年化收益", "最大回撤", "百分比最大回撤", "最大回撤天数",
            "总成交笔数", "夏普比率"
        ])
        self.table_widget.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.table_widget.setSortingEnabled(True)
        self.table_widget.cellDoubleClicked.connect(self.show_stock_detail_dialog)
        
        self.tab_widget.addTab(self.table_widget, "📊 批量回测结果报表 (💡 双击任意股票行进入深度复盘)")
        
        self.log_text = QtWidgets.QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("background-color: #121212; color: #00dd00; font-family: Consolas;")
        self.tab_widget.addTab(self.log_text, "💻 实时控制台日志")
        
        right_layout.addWidget(self.tab_widget)

        self.export_btn = QtWidgets.QPushButton("💾 导出精美 Excel/CSV 报表")
        self.export_btn.setFixedHeight(40)
        self.export_btn.clicked.connect(self.export_to_csv)
        self.export_btn.setEnabled(False)
        right_layout.addWidget(self.export_btn)

        main_layout.addWidget(left_frame)
        main_layout.addLayout(right_layout)

    def set_dark_theme(self):
        palette = QtGui.QPalette()
        palette.setColor(QtGui.QPalette.ColorGroup.All, QtGui.QPalette.ColorRole.Window, QtGui.QColor(30, 30, 30))
        palette.setColor(QtGui.QPalette.ColorGroup.All, QtGui.QPalette.ColorRole.WindowText, QtGui.QColor(220, 220, 220))
        palette.setColor(QtGui.QPalette.ColorGroup.All, QtGui.QPalette.ColorRole.Base, QtGui.QColor(40, 40, 40))
        palette.setColor(QtGui.QPalette.ColorGroup.All, QtGui.QPalette.ColorRole.AlternateBase, QtGui.QColor(30, 30, 30))
        palette.setColor(QtGui.QPalette.ColorGroup.All, QtGui.QPalette.ColorRole.Text, QtGui.QColor(220, 220, 220))
        palette.setColor(QtGui.QPalette.ColorGroup.All, QtGui.QPalette.ColorRole.Button, QtGui.QColor(50, 50, 50))
        palette.setColor(QtGui.QPalette.ColorGroup.All, QtGui.QPalette.ColorRole.ButtonText, QtGui.QColor(220, 220, 220))
        palette.setColor(QtGui.QPalette.ColorGroup.All, QtGui.QPalette.ColorRole.BrightText, QtCore.Qt.GlobalColor.red)
        palette.setColor(QtGui.QPalette.ColorGroup.All, QtGui.QPalette.ColorRole.Highlight, QtGui.QColor(0, 140, 140))
        palette.setColor(QtGui.QPalette.ColorGroup.All, QtGui.QPalette.ColorRole.HighlightedText, QtCore.Qt.GlobalColor.white)
        self.setPalette(palette)
        
        self.setStyleSheet("""
            QGroupBox {
                border: 1px solid #444444;
                border-radius: 6px;
                margin-top: 12px;
                font-weight: bold;
                color: #00dddd;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 3px 0 3px;
            }
            QTableWidget {
                gridline-color: #333333;
                background-color: #1e1e1e;
                alternate-background-color: #252525;
            }
            QHeaderView::section {
                background-color: #2b2b2b;
                color: #dddddd;
                padding: 4px;
                border: 1px solid #3a3a3a;
                font-weight: bold;
            }
        """)

    def init_strategy_combobox(self):
        """
        核心升级：动态扫描并发现您策略库里的所有策略！
        """
        if self.main_engine:
            try:
                # 从官方回测引擎动态提取所有加载好的策略名
                backtester_engine = self.main_engine.get_engine("CtaBacktester")
                
                # 🚨 关键灵魂修复：如果官方回测引擎还未初始化（尚未扫描硬盘），我们主动代为触发扫描！
                if not backtester_engine.classes:
                    backtester_engine.init_engine()
                
                class_names = backtester_engine.get_strategy_class_names()
                class_names.sort()
                
                if class_names:
                    self.strategy_combo.addItems(class_names)
                else:
                    self.strategy_combo.addItem("StockQuantStrategy")
                
                # 默认选中我们的黄金多因子策略
                ix = self.strategy_combo.findText("StockQuantStrategy")
                if ix >= 0:
                    self.strategy_combo.setCurrentIndex(ix)
            except Exception as e:
                self.strategy_combo.addItem("StockQuantStrategy")
        else:
            # 独立运行退避：默认写入最核心的 StockQuantStrategy
            self.strategy_combo.addItem("StockQuantStrategy")

    def configure_strategy_parameters(self):
        """
        调起 VeighNa 官方原生的可滚动参数编辑器，实现对 100% 任意策略的自由配置！
        """
        strategy_name = self.strategy_combo.currentText()
        if not strategy_name:
            QtWidgets.QMessageBox.warning(self, "提示", "请先选择需要配置的交易策略！")
            return

        # 获取默认配置字典
        if strategy_name not in self.strategy_settings:
            if self.main_engine:
                try:
                    backtester_engine = self.main_engine.get_engine("CtaBacktester")
                    default_setting = backtester_engine.get_default_setting(strategy_name)
                    self.strategy_settings[strategy_name] = default_setting
                except Exception:
                    self.strategy_settings[strategy_name] = {}
            else:
                # 独立运行退避黄金参数
                if strategy_name == "StockQuantStrategy":
                    self.strategy_settings[strategy_name] = {
                        "profit_target": 0.035,
                        "max_sub_positions": 5,
                        "fall_days": 7,
                        "percentile_threshold": 20.0,
                        "lowest_days": 3,
                    }
                else:
                    self.strategy_settings[strategy_name] = {}

        current_setting = self.strategy_settings[strategy_name]

        # 调起官方原生编辑器！
        try:
            from vnpy_ctabacktester.ui.widget import BacktestingSettingEditor
            dialog = BacktestingSettingEditor(strategy_name, current_setting)
            if dialog.exec() == dialog.DialogCode.Accepted:
                new_setting = dialog.get_setting()
                self.strategy_settings[strategy_name] = new_setting
                QtWidgets.QMessageBox.information(self, "参数配置成功", f"【{strategy_name}】参数配置已成功保存并在批量运行时生效！")
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "提示", f"启动官方参数配置窗失败，错误：{str(e)}")

    def start_batch_backtest(self):
        """
        解析输入并启动后台异步回测任务
        """
        raw_text = self.stocks_edit.toPlainText().strip()
        if not raw_text:
            QtWidgets.QMessageBox.warning(self, "警告", "股票列表不能为空！")
            return
        
        stocks = []
        for line in raw_text.split("\n"):
            line = line.strip()
            if not line:
                continue
            if "." not in line:
                QtWidgets.QMessageBox.warning(self, "警告", f"股票格式输入错误：'{line}'，必须包含交易所，例如 '000630.SZSE'")
                return
            parts = line.split(".")
            stocks.append((parts[0], parts[1]))

        start_date = datetime.combine(self.start_date_edit.date().toPyDate(), datetime.min.time())
        end_date = datetime.combine(self.end_date_edit.date().toPyDate(), datetime.max.time())

        # ── 🎯 提取策略及动态参数 ──
        strategy_name = self.strategy_combo.currentText()
        if not strategy_name:
            QtWidgets.QMessageBox.warning(self, "警告", "必须选择要回测的交易策略！")
            return
        
        # 寻找对应的策略 Class 类对象
        strategy_class = None
        if self.main_engine:
            try:
                backtester_engine = self.main_engine.get_engine("CtaBacktester")
                strategy_class = backtester_engine.classes[strategy_name]
            except Exception:
                pass

        if not strategy_class:
            # 退避策略导入
            if strategy_name == "StockQuantStrategy":
                from strategies.stock_quant_strategy import StockQuantStrategy
                strategy_class = StockQuantStrategy
            else:
                QtWidgets.QMessageBox.critical(self, "错误", f"无法提取策略 【{strategy_name}】 类对象，请检查 run.py 导入路径！")
                return

        # 提取当前配好的参数，如果没有配置，则去抓取默认配置
        if strategy_name not in self.strategy_settings:
            if self.main_engine:
                try:
                    backtester_engine = self.main_engine.get_engine("CtaBacktester")
                    self.strategy_settings[strategy_name] = backtester_engine.get_default_setting(strategy_name)
                except Exception:
                    self.strategy_settings[strategy_name] = {}
            else:
                if strategy_name == "StockQuantStrategy":
                    self.strategy_settings[strategy_name] = {
                        "profit_target": 0.035,
                        "max_sub_positions": 5,
                        "fall_days": 7,
                        "percentile_threshold": 20.0,
                        "lowest_days": 3,
                    }
                else:
                    self.strategy_settings[strategy_name] = {}

        strategy_params = self.strategy_settings[strategy_name]

        # 通用回测引擎参数
        params = {
            "total_capital": self.capital_spin.value(),
        }

        self.table_widget.setRowCount(0)
        self.log_text.clear()
        self.backtest_engines.clear()
        self.results_data.clear()
        
        self.run_btn.setEnabled(False)
        self.run_btn.setText("⏳ 批量回测运行中...")
        self.tab_widget.setCurrentIndex(1)

        # 启动泛型回测工作线程！
        self.worker = BacktestWorker(stocks, start_date, end_date, strategy_class, strategy_params, params)
        self.worker.log_signal.connect(self.append_log)
        self.worker.result_signal.connect(self.insert_result_row)
        self.worker.finished_signal.connect(self.on_backtest_finished)
        self.worker.start()

    def append_log(self, text):
        self.log_text.append(text)
        self.log_text.moveCursor(QtGui.QTextCursor.MoveOperation.End)

    def insert_result_row(self, data_tuple):
        data, engine = data_tuple
        vt_symbol = data["vt_symbol"]
        
        self.results_data[vt_symbol] = data
        self.backtest_engines[vt_symbol] = engine
        
        row = self.table_widget.rowCount()
        self.table_widget.insertRow(row)

        # 17列豪华报表字段键名
        headers_keys = [
            "vt_symbol", "start_date", "end_date", "total_days", "profit_days",
            "loss_days", "capital", "end_balance", "total_net_pnl", "total_commission",
            "total_return", "annual_return", "max_drawdown", "max_ddpercent", "max_drawdown_duration",
            "total_trade_count", "sharpe_ratio"
        ]

        for col, key in enumerate(headers_keys):
            item = QtWidgets.QTableWidgetItem(data[key])
            item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            
            # 专业高亮展示
            if key in ["total_return", "annual_return", "total_net_pnl"]:
                val = float(data[key].replace("%", "").replace(",", ""))
                if val > 0:
                    item.setForeground(QtGui.QColor(255, 60, 60))
                    item.setFont(QtGui.QFont("Segoe UI", 10, QtGui.QFont.Weight.Bold))
                elif val < 0:
                    item.setForeground(QtGui.QColor(60, 255, 60))
            elif key in ["max_ddpercent", "max_drawdown"]:
                item.setForeground(QtGui.QColor(80, 180, 255))
            
            self.table_widget.setItem(row, col, item)

    def show_stock_detail_dialog(self, row, column):
        item = self.table_widget.item(row, 0)
        if not item:
            return
            
        vt_symbol = item.text()
        engine = self.backtest_engines.get(vt_symbol, None)
        data_row = self.results_data.get(vt_symbol, None)

        if not engine:
            QtWidgets.QMessageBox.warning(self, "提示", f"未找到 {vt_symbol} 的回测计算实例。")
            return

        dialog = StockDetailWindow(
            vt_symbol, 
            data_row, 
            engine, 
            self.main_engine, 
            self.event_engine, 
            self
        )
        dialog.exec()

    def on_backtest_finished(self, results):
        self.run_btn.setEnabled(True)
        self.run_btn.setText("🚀 开始批量回测")
        self.export_btn.setEnabled(True)
        self.tab_widget.setCurrentIndex(0)
        
        QtWidgets.QMessageBox.information(
            self, 
            "批量回测大功告成", 
            "恭喜！所有所选股票的历史批量回测已运行完成！\n💡 双击表格中的任意股票行即可进入原汁原味的成交、K线、每日盈亏复盘！"
        )

    def export_to_csv(self):
        if not self.results_data:
            return
        
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "保存报表", "batch_backtest_report.csv", "CSV Files (*.csv)")
        if not path:
            return
        
        try:
            # 导出全套17列Excel报表指标
            headers = [
                "股票代码", "首个交易日", "最后交易日", "总交易日", "盈利交易日", 
                "亏损交易日", "起始资金", "结束资金", "总盈亏", "总手续费", 
                "总收益率", "年化收益", "最大回撤额度", "百分比最大回撤", "最大回撤天数",
                "总成交笔数", "夏普比率"
            ]
            headers_keys = [
                "vt_symbol", "start_date", "end_date", "total_days", "profit_days",
                "loss_days", "capital", "end_balance", "total_net_pnl", "total_commission",
                "total_return", "annual_return", "max_drawdown", "max_ddpercent", "max_drawdown_duration",
                "total_trade_count", "sharpe_ratio"
            ]

            with open(path, mode="w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                for row_data in self.results_data.values():
                    row_list = [row_data[key] for key in headers_keys]
                    writer.writerow(row_list)
                    
            QtWidgets.QMessageBox.information(self, "导出成功", f"报表已保存至:\n{path}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "错误", f"导出失败：\n{str(e)}")
