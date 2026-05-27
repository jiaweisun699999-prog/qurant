# -*- coding: utf-8 -*-
import os
import sys
import time
import inspect
from PySide6 import QtWidgets, QtCore, QtGui
from .chart_dialog import StrategyChartDialog


def find_strategy_class_dynamically(strategy_name: str):
    """
    🔍 动态、反射导入策略类：全载并重载 strategies 下的所有 .py 文件，保证 100% 拿取最新编译的代码。
    """
    strategies_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "strategies"))
    if not os.path.exists(strategies_dir):
        strategies_dir = os.path.abspath("strategies")
        
    if not os.path.exists(strategies_dir):
        return None
        
    import importlib
    for filename in os.listdir(strategies_dir):
        if filename.endswith(".py") and not filename.startswith("__"):
            module_name = filename[:-3]
            try:
                full_module_name = f"strategies.{module_name}"
                if full_module_name in sys.modules:
                    mod = importlib.reload(sys.modules[full_module_name])
                else:
                    mod = importlib.import_module(full_module_name)
                
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
        module = inspect.getmodule(strategy_class)
        if module:
            module_name = module.__name__
            if module_name in sys.modules:
                importlib.reload(sys.modules[module_name])
                print(f"[HOT_RELOAD] 模块 {module_name} 缓存刷新成功！")
        
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
            self.code_tabs.setCurrentIndex(1)
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
            backup_path = self.strategy_file_path + ".bak"
            with open(self.strategy_file_path, "r", encoding="utf-8") as orig_f:
                backup_content = orig_f.read()
            with open(backup_path, "w", encoding="utf-8") as bak_f:
                bak_f.write(backup_content)

            with open(self.strategy_file_path, "w", encoding="utf-8") as f:
                f.write(code)

            try:
                import vnpy_ctastrategy
                site_strategies_dir = os.path.join(os.path.dirname(vnpy_ctastrategy.__file__), "strategies")
                if os.path.exists(site_strategies_dir):
                    site_file_path = os.path.join(site_strategies_dir, os.path.basename(self.strategy_file_path))
                    if os.path.exists(site_file_path):
                        site_backup = site_file_path + ".bak"
                        with open(site_file_path, "r", encoding="utf-8") as sf:
                            site_orig_content = sf.read()
                        with open(site_backup, "w", encoding="utf-8") as sbf:
                            sbf.write(site_orig_content)
                    with open(site_file_path, "w", encoding="utf-8") as sf:
                        sf.write(code)
                    print(f"[HOT_RELOAD] 成功同步进化后的新策略代码至 site-packages: {site_file_path}")
            except Exception as e_site:
                print(f"[HOT_RELOAD] 同步策略代码至 site-packages 失败: {e_site}")

            success = hot_reload_strategy(self.strategy_class.__name__, self.strategy_class)

            new_class = None
            try:
                parent_app = None
                curr = self.parent()
                while curr:
                    if curr.__class__.__name__ == "BatchBacktestApp":
                        parent_app = curr
                        break
                    curr = curr.parent()
                
                if parent_app:
                    new_class = find_strategy_class_dynamically(self.strategy_class.__name__)
                    if new_class:
                        default_setting = {}
                        if hasattr(new_class, "parameters") and new_class.parameters:
                            for param_name in new_class.parameters:
                                if hasattr(new_class, param_name):
                                    default_setting[param_name] = getattr(new_class, param_name)
                        parent_app.strategy_settings[new_class.__name__] = default_setting
                        print(f"[HOT_RELOAD] 已成功将 AI 进化的新参数覆盖至 GUI 缓存: {default_setting}")
            except Exception as e_sync:
                print(f"[HOT_RELOAD] 同步参数缓存失败: {e_sync}")

            if self.main_engine:
                try:
                    backtester_engine = self.main_engine.get_engine("CtaBacktester")
                    backtester_engine.reload_strategy_class()
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
        parent_app = self.parent()
        strategy_name = parent_app.strategy_combo.currentText()

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
            self.accept()
            parent_app.start_batch_backtest()
