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


def find_strategy_class_dynamically(strategy_name: str):
    """
    🔍 动态、反射导入策略类：全载并重载 strategies 下的所有 .py 文件，保证 100% 拿取最新编译的代码。
    """
    import os
    import importlib
    import sys
    
    # 获取 strategies 文件夹的绝对路径
    strategies_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "strategies"))
    if not os.path.exists(strategies_dir):
        strategies_dir = os.path.abspath("strategies")
        
    if not os.path.exists(strategies_dir):
        return None
        
    for filename in os.listdir(strategies_dir):
        if filename.endswith(".py") and not filename.startswith("__"):
            module_name = filename[:-3]
            try:
                full_module_name = f"strategies.{module_name}"
                # 如果模块已被缓存，强制执行 reload，否则 import
                if full_module_name in sys.modules:
                    mod = importlib.reload(sys.modules[full_module_name])
                else:
                    mod = importlib.import_module(full_module_name)
                
                # 检查该模块是否定义了我们所需的策略类
                if hasattr(mod, strategy_name):
                    return getattr(mod, strategy_name)
            except Exception as e:
                print(f"[ERROR] 动态载入策略文件 {filename} 失败: {e}")
    return None


def hot_reload_strategy(strategy_name: str, strategy_class) -> bool:
    """
    ⚡ 动态热重载核心逻辑：清除 sys.modules 缓存，重新加载该模块以及 strategies 包。
    """
    try:
        import importlib
        import sys
        import inspect
        
        # 1. 查找类所在的模块并重载
        module = inspect.getmodule(strategy_class)
        if module:
            module_name = module.__name__
            if module_name in sys.modules:
                importlib.reload(sys.modules[module_name])
                print(f"[HOT_RELOAD] 模块 {module_name} 缓存刷新成功！")
        
        # 2. 刷新 strategies 包
        try:
            import strategies
            importlib.reload(strategies)
        except Exception:
            pass
            
        return True
    except Exception as e:
        print(f"[HOT_RELOAD] 动态刷新模块缓存失败: {e}")
        return False


class AIDiagnosisWorker(QtCore.QThread):
    """
    异步 AI 计算工作线程：保证 UI 永不卡顿，后台与 AI 接口进行通信
    """
    finished_signal = QtCore.Signal(tuple) # 发送 (success_bool, raw_response, parsed_report, parsed_code)

    def __init__(self, vt_symbol, stats, strategy_code, api_key, base_url, model_name):
        super().__init__()
        self.vt_symbol = vt_symbol
        self.stats = stats
        self.strategy_code = strategy_code
        self.api_key = api_key
        self.base_url = base_url
        self.model_name = model_name

    def run(self):
        try:
            # 动态导入我们刚才创建的 ai_client 模块
            from .ai_client import request_ai_diagnosis
            raw_res, report, code = request_ai_diagnosis(
                self.vt_symbol,
                self.stats,
                self.strategy_code,
                self.api_key,
                self.base_url,
                self.model_name
            )
            self.finished_signal.emit((True, raw_res, report, code))
        except Exception as e:
            self.finished_signal.emit((False, str(e), "", ""))


class AIDiagnosisDialog(QtWidgets.QDialog):
    """
    至尊高档暗黑风：AI 首席量化专家智能诊疗与策略自演变大屏
    """
    def __init__(self, vt_symbol, stats, strategy_class, main_engine=None, parent=None):
        super().__init__(parent)
        self.vt_symbol = vt_symbol
        self.stats = stats
        self.strategy_class = strategy_class
        self.main_engine = main_engine

        # 获取策略源代码路径与内容
        import inspect
        try:
            self.strategy_file_path = os.path.abspath(inspect.getfile(self.strategy_class))
            with open(self.strategy_file_path, "r", encoding="utf-8") as f:
                self.original_code = f.read()
        except Exception as e:
            self.strategy_file_path = ""
            self.original_code = f"# 无法读取策略源代码，原因：{str(e)}"

        self.evolved_code = ""
        self.init_ui()
        self.load_settings()

    def init_ui(self):
        self.setWindowTitle(f"🧠 AI 首席量化专家诊疗室 & 策略演进中心 - {self.vt_symbol}")
        self.resize(1300, 820)
        self.setStyleSheet("background-color: #1a1a1a; color: #ffffff;")

        layout = QtWidgets.QVBoxLayout(self)

        # ── 1. 顶部高端信息卡片 ──
        header_frame = QtWidgets.QFrame()
        header_frame.setStyleSheet("background-color: #242424; border-radius: 6px; border: 1px solid #333;")
        header_layout = QtWidgets.QHBoxLayout(header_frame)

        lbl_title = QtWidgets.QLabel(f"🧠 AI 首席专家诊疗中... [ 标的: {self.vt_symbol} | 当前策略类: {self.strategy_class.__name__} ]")
        lbl_title.setStyleSheet("font-weight: bold; font-size: 14px; color: #00dddd;")
        header_layout.addWidget(lbl_title)

        # 简要业绩快速对照
        total_return_str = self.stats.get("total_return", "N/A")
        sharpe_str = self.stats.get("sharpe_ratio", "N/A")
        max_dd_str = self.stats.get("max_ddpercent", "N/A")
        summary_text = f"总收益率: {total_return_str} | 夏普比率: {sharpe_str} | 最大回撤: {max_dd_str}"
        lbl_summary = QtWidgets.QLabel(summary_text)
        lbl_summary.setStyleSheet("font-weight: bold; color: #ff3c3c; font-size: 13px;")
        header_layout.addWidget(lbl_summary, alignment=QtCore.Qt.AlignmentFlag.AlignRight)

        layout.addWidget(header_frame)

        # ── 2. AI 接口配置面板 ──
        config_group = QtWidgets.QGroupBox("⚙️ AI 诊断引擎接口配置 (支持中国大陆代理通道)")
        config_group.setStyleSheet("QGroupBox { font-size: 11px; margin-top: 5px; }")
        config_layout = QtWidgets.QHBoxLayout(config_group)

        config_layout.addWidget(QtWidgets.QLabel("API Key:"))
        self.api_key_edit = QtWidgets.QLineEdit()
        self.api_key_edit.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("请输入 Gemini 或 OpenAI 兼容的 API Key")
        config_layout.addWidget(self.api_key_edit)

        config_layout.addWidget(QtWidgets.QLabel("Base URL:"))
        self.base_url_edit = QtWidgets.QLineEdit()
        self.base_url_edit.setPlaceholderText("例如: https://generativelanguage.googleapis.com/v1beta/openai")
        config_layout.addWidget(self.base_url_edit)

        config_layout.addWidget(QtWidgets.QLabel("模型名称:"))
        self.model_edit = QtWidgets.QLineEdit()
        self.model_edit.setPlaceholderText("例如: gemini-1.5-pro")
        config_layout.addWidget(self.model_edit)

        self.btn_save_config = QtWidgets.QPushButton("💾 保存配置")
        self.btn_save_config.setStyleSheet("background-color: #3a3a3a; color: #fff; padding: 4px 10px; border-radius: 4px;")
        self.btn_save_config.clicked.connect(self.save_settings)
        config_layout.addWidget(self.btn_save_config)

        layout.addWidget(config_group)

        # ── 3. 核心分屏大屏区域 ──
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)

        # 左侧：AI 诊断报告 (Markdown 渲染)
        left_widget = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        lbl_left = QtWidgets.QLabel("📋 首席量化专家深度诊断报告 (Markdown)")
        lbl_left.setStyleSheet("font-weight: bold; color: #00dddd; font-size: 13px; margin-bottom: 3px;")
        left_layout.addWidget(lbl_left)

        self.report_browser = QtWidgets.QTextBrowser()
        self.report_browser.setStyleSheet("background-color: #121212; border: 1px solid #333; font-family: 'Segoe UI', 'Microsoft YaHei'; padding: 12px; font-size: 13px; line-height: 150%;")
        self.report_browser.setPlaceholderText("点击下方【🚀 启动 AI 智能诊断】按钮。大模型将秒级提取本股票在各时间窗口下的真实盈亏曲线与成交明细，进行深度归因并提出专业的指标与逻辑改进策略报告...")
        left_layout.addWidget(self.report_browser)

        splitter.addWidget(left_widget)

        # 右侧：策略代码差异对比与自演进
        right_widget = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        lbl_right = QtWidgets.QLabel("💻 策略代码自演进与 AST 安全校验盾")
        lbl_right.setStyleSheet("font-weight: bold; color: #00dddd; font-size: 13px; margin-bottom: 3px;")
        right_layout.addWidget(lbl_right)

        self.code_tabs = QtWidgets.QTabWidget()
        
        self.orig_code_edit = QtWidgets.QTextEdit()
        self.orig_code_edit.setReadOnly(True)
        self.orig_code_edit.setStyleSheet("background-color: #151515; font-family: Consolas; font-size: 12px; color: #888888; border: 1px solid #333;")
        self.orig_code_edit.setPlainText(self.original_code)

        self.evolve_code_edit = QtWidgets.QTextEdit()
        self.evolve_code_edit.setStyleSheet("background-color: #0f1c1f; font-family: Consolas; font-size: 12px; color: #00ffcc; border: 1px solid #005555;")
        self.evolve_code_edit.setPlaceholderText("AI 重写演进后的优化代码将在此显示。\nAI 进化完成后，您也可以在此文本框内自由地手动修改、微调代码！")
        self.evolve_code_edit.textChanged.connect(self.run_local_ast_check)

        self.code_tabs.addTab(self.orig_code_edit, "⏪ 原始策略源代码")
        self.code_tabs.addTab(self.evolve_code_edit, "🟢 AI 优化进化版代码 (可在此手动微调)")
        
        right_layout.addWidget(self.code_tabs)

        # AST 校验状态栏
        self.ast_status_label = QtWidgets.QLabel("⌛ 状态: 等待 AI 生成优化代码...")
        self.ast_status_label.setStyleSheet("background-color: #242424; padding: 6px; font-weight: bold; border-radius: 4px; border: 1px solid #333; color: #888; font-size: 12px;")
        right_layout.addWidget(self.ast_status_label)

        splitter.addWidget(right_widget)
        splitter.setSizes([550, 750])

        layout.addWidget(splitter)

        # ── 4. 底部控制按钮栏 ──
        btn_layout = QtWidgets.QHBoxLayout()

        self.btn_run_ai = QtWidgets.QPushButton("🚀 启动 AI 智能诊断")
        self.btn_run_ai.setFixedHeight(45)
        self.btn_run_ai.setStyleSheet("""
            QPushButton {
                background-color: #008c8c;
                color: white;
                font-weight: bold;
                font-size: 13px;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #00aaaa;
            }
        """)
        self.btn_run_ai.clicked.connect(self.start_ai_diagnosis)
        btn_layout.addWidget(self.btn_run_ai)

        self.btn_evolve = QtWidgets.QPushButton("⚡ 一键进化策略 & 热重载")
        self.btn_evolve.setFixedHeight(45)
        self.btn_evolve.setEnabled(False)
        self.btn_evolve.setStyleSheet("""
            QPushButton {
                background-color: #4a0082;
                color: #00ffff;
                border: 1px solid #00dddd;
                font-weight: bold;
                font-size: 13px;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #00dddd;
                color: #1a1a1a;
            }
            QPushButton:disabled {
                background-color: #333333;
                color: #888888;
                border: none;
            }
        """)
        self.btn_evolve.clicked.connect(self.evolve_and_reload)
        btn_layout.addWidget(self.btn_evolve)

        self.btn_rerun_backtest = QtWidgets.QPushButton("🔄 立即重跑回测验证")
        self.btn_rerun_backtest.setFixedHeight(45)
        self.btn_rerun_backtest.setEnabled(False)
        self.btn_rerun_backtest.setStyleSheet("""
            QPushButton {
                background-color: #ff3c3c;
                color: white;
                font-weight: bold;
                font-size: 13px;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #ff5c5c;
            }
            QPushButton:disabled {
                background-color: #333333;
                color: #888888;
                border: none;
            }
        """)
        self.btn_rerun_backtest.clicked.connect(self.rerun_backtest)
        btn_layout.addWidget(self.btn_rerun_backtest)

        close_btn = QtWidgets.QPushButton("返回复盘大盘")
        close_btn.setFixedHeight(45)
        close_btn.setStyleSheet("background-color: #555555; color: #ffffff; border-radius: 6px;")
        close_btn.clicked.connect(self.reject)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

    def load_settings(self):
        from .ai_client import load_ai_config
        config = load_ai_config()
        self.api_key_edit.setText(config.get("api_key", ""))
        self.base_url_edit.setText(config.get("base_url", ""))
        self.model_edit.setText(config.get("model_name", ""))

    def save_settings(self):
        from .ai_client import save_ai_config
        save_ai_config(
            self.api_key_edit.text(),
            self.base_url_edit.text(),
            self.model_edit.text()
        )
        QtWidgets.QMessageBox.information(self, "成功", "AI 接口配置已成功保存！")

    def run_local_ast_check(self):
        code = self.evolve_code_edit.toPlainText().strip()
        if not code:
            self.ast_status_label.setText("⌛ 状态: 等待 AI 生成优化代码...")
            self.ast_status_label.setStyleSheet("background-color: #242424; padding: 6px; font-weight: bold; border-radius: 4px; border: 1px solid #333; color: #888;")
            self.btn_evolve.setEnabled(False)
            return

        from .ai_client import validate_strategy_code
        ok, msg = validate_strategy_code(code)
        if ok:
            self.ast_status_label.setText("🟢 恭喜！代码安全与语法校验 100% 通过！")
            self.ast_status_label.setStyleSheet("background-color: #0b2e13; padding: 6px; font-weight: bold; border-radius: 4px; border: 1px solid #1e7e34; color: #28a745;")
            self.btn_evolve.setEnabled(True)
        else:
            self.ast_status_label.setText(f"🔴 安全校验未通过: {msg}")
            self.ast_status_label.setStyleSheet("background-color: #4b121a; padding: 6px; font-weight: bold; border-radius: 4px; border: 1px solid #dc3545; color: #dc3545;")
            self.btn_evolve.setEnabled(False)

    def start_ai_diagnosis(self):
        api_key = self.api_key_edit.text().strip()
        base_url = self.base_url_edit.text().strip()
        model_name = self.model_edit.text().strip()

        if not api_key:
            QtWidgets.QMessageBox.warning(self, "提示", "请先配置并保存 API Key！")
            return

        self.btn_run_ai.setEnabled(False)
        self.btn_run_ai.setText("⏳ AI 深度计算中，约耗时 30-60 秒...")
        self.report_browser.setHtml("<h3 style='color: #00dddd;'>🧠 AI 首席专家正在阅览您的个股回测指标，深度诊断中，请耐心等待...</h3>")

        self.worker = AIDiagnosisWorker(
            self.vt_symbol,
            self.stats,
            self.original_code,
            api_key,
            base_url,
            model_name
        )
        self.worker.finished_signal.connect(self.on_ai_diagnosis_finished)
        self.worker.start()

    def on_ai_diagnosis_finished(self, result_tuple):
        success, raw_res, report, code = result_tuple
        self.btn_run_ai.setEnabled(True)
        self.btn_run_ai.setText("🚀 启动 AI 智能诊断")

        if success:
            self.report_browser.setMarkdown(report)
            self.evolved_code = code
            self.evolve_code_edit.setPlainText(code)
            self.code_tabs.setCurrentIndex(1) # 自动切到演进后的代码页
            QtWidgets.QMessageBox.information(self, "AI 诊断成功", "AI 首席分析师已出具专业诊断报告，并生成了优化代码！\n请查看代码并进行安全确认。")
        else:
            self.report_browser.setHtml(f"<h3 style='color: #ff3c3c;'>❌ AI 诊断失败，原因：</h3><p>{raw_res}</p>")
            QtWidgets.QMessageBox.critical(self, "AI 诊断失败", f"接口调用失败，详情：\n{raw_res}")

    def evolve_and_reload(self):
        code = self.evolve_code_edit.toPlainText().strip()
        if not code:
            return

        from .ai_client import validate_strategy_code
        ok, msg = validate_strategy_code(code)
        if not ok:
            QtWidgets.QMessageBox.warning(self, "安全拦截", f"代码未通过安全与语法校验，拒绝写入！原因：\n{msg}")
            return

        if not self.strategy_file_path:
            QtWidgets.QMessageBox.critical(self, "错误", "未找到策略的源代码文件路径，无法保存。")
            return

        reply = QtWidgets.QMessageBox.question(
            self,
            "确认覆盖代码",
            f"确认将 AI 优化的新代码写入策略源文件？\n这会直接覆盖您原本的文件：\n{os.path.basename(self.strategy_file_path)}",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No
        )
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            return

        try:
            # 1. 安全备份
            backup_path = self.strategy_file_path + ".bak"
            with open(self.strategy_file_path, "r", encoding="utf-8") as orig_f:
                backup_content = orig_f.read()
            with open(backup_path, "w", encoding="utf-8") as bak_f:
                bak_f.write(backup_content)

            # 2. 写入新代码到本地工作区策略文件
            with open(self.strategy_file_path, "w", encoding="utf-8") as f:
                f.write(code)

            # 🚨 灵魂修复第一步：同时强行写入/更新 Python site-packages 下的同名策略文件！
            # 彻底解决由于 python 寻找 CWD 及 site-packages 缓存导致的旧策略代码执迷不悟的 Bug！
            try:
                import vnpy_ctastrategy
                site_strategies_dir = os.path.join(os.path.dirname(vnpy_ctastrategy.__file__), "strategies")
                if os.path.exists(site_strategies_dir):
                    site_file_path = os.path.join(site_strategies_dir, os.path.basename(self.strategy_file_path))
                    # 备份 site-packages 里的旧文件
                    if os.path.exists(site_file_path):
                        site_backup = site_file_path + ".bak"
                        with open(site_file_path, "r", encoding="utf-8") as sf:
                            site_orig_content = sf.read()
                        with open(site_backup, "w", encoding="utf-8") as sbf:
                            sbf.write(site_orig_content)
                    # 写入新代码
                    with open(site_file_path, "w", encoding="utf-8") as sf:
                        sf.write(code)
                    print(f"[HOT_RELOAD] 成功同步进化后的新策略代码至 site-packages: {site_file_path}")
            except Exception as e_site:
                print(f"[HOT_RELOAD] 同步策略代码至 site-packages 失败: {e_site}")

            # 3. 动态热重载模块缓存
            success = hot_reload_strategy(self.strategy_class.__name__, self.strategy_class)

            # 3.5 核心防线突破：同步进化后的策略默认参数到主界面的 GUI 参数配置缓存中，防止旧参数被强行覆盖！
            new_class = None
            try:
                # 寻找主 BatchBacktestApp 实例
                parent_app = None
                curr = self.parent()
                while curr:
                    if curr.__class__.__name__ == "BatchBacktestApp":
                        parent_app = curr
                        break
                    curr = curr.parent()
                
                if parent_app:
                    # 动态反射载入我们最新写入的 Class 结构
                    new_class = find_strategy_class_dynamically(self.strategy_class.__name__)
                    if new_class:
                        default_setting = {}
                        if hasattr(new_class, "parameters") and new_class.parameters:
                            for param_name in new_class.parameters:
                                if hasattr(new_class, param_name):
                                    default_setting[param_name] = getattr(new_class, param_name)
                        # 重写主窗口的策略参数缓存 dictionary，彻底解决 GUI 参数旧缓存覆盖新代码的 Bug！
                        parent_app.strategy_settings[new_class.__name__] = default_setting
                        print(f"[HOT_RELOAD] 已成功将 AI 进化的新参数覆盖至 GUI 缓存: {default_setting}")
            except Exception as e_sync:
                print(f"[HOT_RELOAD] 同步参数缓存失败: {e_sync}")

            # 4. 若在 VeighNa 引擎中，刷新其内部策略注册字典
            if self.main_engine:
                try:
                    backtester_engine = self.main_engine.get_engine("CtaBacktester")
                    backtester_engine.reload_strategy_class()
                    # 🚨 灵魂修复第二步：强行用我们最新从本地动态加载出来的 new_class 覆盖官方 backtester_engine.classes 缓存！
                    # 即使由于 CWD 或 CTP/XTP 环境导致官方回测重载依旧指向旧缓存，此处也能完成绝对的降维打击与精准替换！
                    if not new_class:
                        new_class = find_strategy_class_dynamically(self.strategy_class.__name__)
                    if new_class:
                        backtester_engine.classes[self.strategy_class.__name__] = new_class
                        print(f"[HOT_RELOAD] 已强制将最新策略类注入官方 BacktesterEngine classes 字典！")
                except Exception as e_reload:
                    print(f"[HOT_RELOAD] 刷新官方回测注册表及强制注入类失败: {e_reload}")

            if success:
                QtWidgets.QMessageBox.information(
                    self,
                    "一键进化成功！",
                    f"🎉 策略已成功保存并动态热重载！\n历史备份已存至: {os.path.basename(backup_path)}"
                )
                self.btn_rerun_backtest.setEnabled(True)
            else:
                QtWidgets.QMessageBox.warning(self, "热重载部分失败", "新代码已成功写入，但模块缓存重载失败，建议重启软件以确保生效。")
                self.btn_rerun_backtest.setEnabled(True)

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "写入失败", f"策略保存过程中发生错误：\n{str(e)}")

    def rerun_backtest(self):
        # 弹窗提示：即将关闭控制面板并自动重跑
        self.accept()


class StockDetailWindow(QtWidgets.QDialog):
    """
    个股回测复盘控制台窗口 (完美集成 AI 诊断与自演进中心)
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
        self.setMinimumSize(480, 420)
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
        self.btn_candle = QtWidgets.QPushButton("📈 策略分析图表")
        
        # 💡 至尊高亮 AI 诊疗演进大按钮！
        self.btn_ai_diagnosis = QtWidgets.QPushButton("🧠 AI 首席专家智能诊断与策略进化")

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

        # 极致酷炫的紫色流光风格 AI 按钮
        self.btn_ai_diagnosis.setStyleSheet("""
            QPushButton {
                background-color: #4a0082;
                color: #00ffff;
                border: 2px solid #00dddd;
                border-radius: 6px;
                padding: 14px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #00dddd;
                color: #1a1a1a;
                border-color: #ffffff;
            }
        """)

        self.btn_trade.clicked.connect(self.show_trades)
        self.btn_order.clicked.connect(self.show_orders)
        self.btn_daily.clicked.connect(self.show_daily)
        self.btn_candle.clicked.connect(self.show_candle)
        self.btn_ai_diagnosis.clicked.connect(self.show_ai_diagnosis)

        btn_layout.addWidget(self.btn_trade, 0, 0)
        btn_layout.addWidget(self.btn_order, 0, 1)
        btn_layout.addWidget(self.btn_daily, 1, 0)
        btn_layout.addWidget(self.btn_candle, 1, 1)
        
        # AI 按钮跨越两列，占据底部
        btn_layout.addWidget(self.btn_ai_diagnosis, 2, 0, 1, 2)
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
        try:
            result_df = self.engine.calculate_result()
            stats = self.engine.calculate_statistics(df=result_df, output=False)
            dialog = StrategyChartDialog(self.vt_symbol, stats, result_df, self)
            dialog.exec()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "警告", f"加载策略分析图表看板失败，原因：\n{str(e)}")

    def show_ai_diagnosis(self):
        """
        🚀 调起极致专业的 AI 量化诊断与策略自进化大屏！
        """
        parent_app = self.parent() # BatchBacktestApp
        strategy_name = parent_app.strategy_combo.currentText()

        # 动态重载、高保真地发现最新的类定义
        strategy_class = find_strategy_class_dynamically(strategy_name)
        if not strategy_class:
            QtWidgets.QMessageBox.critical(self, "错误", f"无法在策略库中定位 【{strategy_name}】 的代码，请检查 strategies 目录！")
            return

        dialog = AIDiagnosisDialog(
            self.vt_symbol,
            self.data_row,
            strategy_class,
            self.main_engine,
            self
        )

        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            # 💡 用户点击了“立即重跑回测验证”
            # 先关闭个股复盘面板，再秒级触发主面板的一键批量回测！
            self.accept()
            parent_app.start_batch_backtest()



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
