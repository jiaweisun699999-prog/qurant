# NumPy 2.0 兼容性补丁 (修复 empyrical 库调用 np.NINF 崩溃问题)
import numpy as np
if not hasattr(np, 'NINF'):
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

# ── 导入解耦后的模块类 ──
from .worker import BacktestWorker
from .chart_dialog import StrategyChartDialog
from .ai_diagnosis import AIDiagnosisWorker, AIDiagnosisDialog, StockDetailWindow, find_strategy_class_dynamically, hot_reload_strategy
from .portfolio import PortfolioSimulatorWindow


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
        self.stocks_edit.setPlaceholderText("请输入股票，一行一个，格式例如:\n000630.SZSE\n000001.SZSE\n600519.SSE\n002594.SZSE\n601318.SSE\n002511.SZSE\n600030.SSE")
        self.stocks_edit.setText("000630.SZSE\n000001.SZSE\n600519.SSE\n002594.SZSE\n601318.SSE\n002511.SZSE\n600030.SSE")
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

        btn_hbox = QtWidgets.QHBoxLayout()
        
        self.export_btn = QtWidgets.QPushButton("💾 导出精美 Excel/CSV 报表")
        self.export_btn.setFixedHeight(40)
        self.export_btn.clicked.connect(self.export_to_csv)
        self.export_btn.setEnabled(False)
        btn_hbox.addWidget(self.export_btn)
        
        self.portfolio_btn = QtWidgets.QPushButton("💼 一键多股组合资金分配模拟器")
        self.portfolio_btn.setFixedHeight(40)
        self.portfolio_btn.setStyleSheet("""
            QPushButton {
                background-color: #5b3b8c;
                color: white;
                font-weight: bold;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #7b5baf;
            }
            QPushButton:disabled {
                background-color: #444;
                color: #888;
            }
        """)
        self.portfolio_btn.clicked.connect(self.show_portfolio_simulator)
        self.portfolio_btn.setEnabled(False)
        btn_hbox.addWidget(self.portfolio_btn)
        
        right_layout.addLayout(btn_hbox)

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
        
        # 1. 强制刷新硬盘最新代码在 sys.modules 中的缓存！(这是核心防线，刷新底层 Python 导入缓存)
        strategy_class = find_strategy_class_dynamically(strategy_name)

        # 2. 如果是 VeighNa 界面集成模式，额外通知官方回测引擎同步重载它的 classes 注册字典
        if self.main_engine:
            try:
                backtester_engine = self.main_engine.get_engine("CtaBacktester")
                backtester_engine.reload_strategy_class()
                # 🚨 灵魂修复：将我们从本地动态加载出来的最新 strategy_class 强行注入并覆盖官方引擎的 classes 注册字典！
                # 绝不直接用官方 `backtester_engine.classes[strategy_name]` 覆盖掉好不容易加载的最新本地类，
                # 这样不管是官方回测还是批量回测，都保证用的是同一份最新修改的代码！
                if strategy_class:
                    backtester_engine.classes[strategy_name] = strategy_class
                    print(f"[VEIGHNA] 成功注入本地最新策略类 {strategy_name} 到官方 Classes 注册表！")
            except Exception as e:
                print(f"[VEIGHNA] 通知官方回测引擎重载出错: {e}")

        if not strategy_class:
            QtWidgets.QMessageBox.critical(self, "错误", f"无法在策略库中定位 【{strategy_name}】 类定义，请检查 strategies 目录！")
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
        if "汇总" in vt_symbol:
            return
            
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
        self.portfolio_btn.setEnabled(True)
        self.tab_widget.setCurrentIndex(0)
        
        # ── 🎯 灵魂计算：计算批量回测全局汇总报表指标 ──
        if self.results_data:
            total_net_pnl = 0.0
            total_commission = 0.0
            total_trades = 0
            returns = []
            annual_returns = []
            dd_pcts = []
            sharpes = []
            win_stocks = 0
            total_stocks = len(self.results_data)
            
            for key, data in self.results_data.items():
                try:
                    # 清理并转换格式化字符串为浮点数
                    pnl_val = float(data["total_net_pnl"].replace(",", "").replace("¥", ""))
                    comm_val = float(data["total_commission"].replace(",", "").replace("¥", ""))
                    trade_val = int(data["total_trade_count"].replace(",", ""))
                    ret_val = float(data["total_return"].replace("%", "").replace(",", ""))
                    ann_val = float(data["annual_return"].replace("%", "").replace(",", ""))
                    dd_val = float(data["max_ddpercent"].replace("%", "").replace(",", ""))
                    sharpe_val = float(data["sharpe_ratio"].replace(",", ""))
                    
                    total_net_pnl += pnl_val
                    total_commission += comm_val
                    total_trades += trade_val
                    returns.append(ret_val)
                    annual_returns.append(ann_val)
                    dd_pcts.append(dd_val)
                    sharpes.append(sharpe_val)
                    
                    if pnl_val > 0:
                        win_stocks += 1
                except Exception as e_calc:
                    print(f"[SUMMARY_CALC] 解析单股数据失败: {e_calc}")

            # 计算平均值和胜率
            avg_return = sum(returns) / len(returns) if returns else 0.0
            avg_annual_return = sum(annual_returns) / len(annual_returns) if annual_returns else 0.0
            avg_dd = sum(dd_pcts) / len(dd_pcts) if dd_pcts else 0.0
            max_dd = min(dd_pcts) if dd_pcts else 0.0 # 最大回撤为负值，因此最小值是最差情况
            avg_sharpe = sum(sharpes) / len(sharpes) if sharpes else 0.0
            win_rate = (win_stocks / total_stocks) * 100.0 if total_stocks else 0.0

            # 1. 在表格底部追加一行“汇总平均”行，采用独特的蓝色极佳高亮显示
            summary_row = self.table_widget.rowCount()
            self.table_widget.insertRow(summary_row)
            
            headers_keys = [
                "vt_symbol", "start_date", "end_date", "total_days", "profit_days",
                "loss_days", "capital", "end_balance", "total_net_pnl", "total_commission",
                "total_return", "annual_return", "max_drawdown", "max_ddpercent", "max_drawdown_duration",
                "total_trade_count", "sharpe_ratio"
            ]
            
            summary_data = {
                "vt_symbol": "📊 汇总平均",
                "start_date": "-",
                "end_date": "-",
                "total_days": "-",
                "profit_days": "-",
                "loss_days": "-",
                "capital": "-",
                "end_balance": "-",
                "total_net_pnl": f"{total_net_pnl:,.2f}",
                "total_commission": f"{total_commission:,.2f}",
                "total_return": f"{avg_return:.2f}%",
                "annual_return": f"{avg_annual_return:.2f}%",
                "max_drawdown": "-",
                "max_ddpercent": f"{avg_dd:.2f}%",
                "max_drawdown_duration": "-",
                "total_trade_count": str(total_trades),
                "sharpe_ratio": f"{avg_sharpe:.2f}"
            }
            
            for col, key in enumerate(headers_keys):
                item = QtWidgets.QTableWidgetItem(summary_data[key])
                item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                
                # 🚨 灵魂优化：使用尊贵暗色调底色 (深蓝灰)，完美融入暗黑模式，并解决白底白字的对比度灾难！
                item.setBackground(QtGui.QColor(38, 52, 74))
                item.setFont(QtGui.QFont("Segoe UI", 10, QtGui.QFont.Weight.Bold))
                
                # 🚨 必须对所有列都显式设定前景字色，防止暗黑模式下默认的白色/浅灰色字在亮色背景下失效！
                if key in ["total_return", "annual_return", "total_net_pnl"]:
                    val = float(summary_data[key].replace("%", "").replace(",", ""))
                    if val > 0:
                        item.setForeground(QtGui.QColor(255, 100, 100)) # 鲜艳亮红
                    elif val < 0:
                        item.setForeground(QtGui.QColor(100, 255, 100)) # 鲜艳亮绿
                    else:
                        item.setForeground(QtGui.QColor(240, 240, 240)) # 亮白色
                elif key in ["max_ddpercent"]:
                    item.setForeground(QtGui.QColor(100, 180, 255)) # 鲜艳天蓝
                elif key == "vt_symbol":
                    item.setForeground(QtGui.QColor(255, 215, 0)) # 尊贵金黄色高亮标题
                else:
                    item.setForeground(QtGui.QColor(240, 240, 240)) # 亮白色，确保手续费、成交笔数、夏普比率等文字完美清晰！
                
                self.table_widget.setItem(summary_row, col, item)

            # 2. 弹出一个豪华大字报式的汇总大视窗弹窗
            msg_box = QtWidgets.QMessageBox(self)
            msg_box.setWindowTitle("🏆 批量回测大功告成！")
            msg_box.setIcon(QtWidgets.QMessageBox.Icon.Information)
            
            summary_html = f"""
            <h3>🎉 所有选定股票的历史批量回测已全部完成！</h3>
            <hr/>
            <table border="0" cellpadding="5" cellspacing="0" style="font-size: 13px;">
                <tr><td><b>📈 平均总收益率:</b></td><td style="color:{'#ff3c3c' if avg_return >= 0 else '#3cff3c'}; font-size: 15px;"><b>{avg_return:.2f}%</b></td></tr>
                <tr><td><b>📅 平均年化收益率:</b></td><td style="color:{'#ff3c3c' if avg_annual_return >= 0 else '#3cff3c'}; font-size: 14px;"><b>{avg_annual_return:.2f}%</b></td></tr>
                <tr><td><b>🛡️ 平均最大回撤:</b></td><td style="color:#0078d4;"><b>{avg_dd:.2f}%</b></td></tr>
                <tr><td><b>💥 最差个股最大回撤:</b></td><td style="color:#e81123;"><b>{max_dd:.2f}%</b></td></tr>
                <tr><td><b>📊 平均夏普比率:</b></td><td><b>{avg_sharpe:.2f}</b></td></tr>
                <tr><td><b>🎯 组合总盈亏:</b></td><td style="color:{'#ff3c3c' if total_net_pnl >= 0 else '#3cff3c'}; font-size: 14px;"><b>¥{total_net_pnl:,.2f}</b></td></tr>
                <tr><td><b>💰 总交易手续费:</b></td><td>¥{total_commission:,.2f}</td></tr>
                <tr><td><b>🤝 盈利个股胜率:</b></td><td style="color:#d83b01;"><b>{win_rate:.1f}% ({win_stocks}/{total_stocks})</b></td></tr>
                <tr><td><b>🔄 总交易笔数:</b></td><td>{total_trades} 笔</td></tr>
            </table>
            <hr/>
            <p style="color:#555;">💡 <i>双击下方表格中的任意个股行，即可进入包含成交、K线及盈亏曲线的交互式复盘窗口！</i></p>
            """
            msg_box.setText(summary_html)
            msg_box.exec()
        else:
            QtWidgets.QMessageBox.information(
                self, 
                "批量回测完成", 
                "恭喜！历史批量回测已运行完成！"
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

    def show_portfolio_simulator(self):
        if not self.backtest_engines:
            QtWidgets.QMessageBox.warning(self, "提示", "没有可用的回测引擎数据！请先运行批量回测。")
            return
            
        dialog = PortfolioSimulatorWindow(self)
        dialog.exec()
