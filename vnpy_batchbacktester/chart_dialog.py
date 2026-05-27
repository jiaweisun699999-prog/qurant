# -*- coding: utf-8 -*-
from PySide6 import QtWidgets, QtCore, QtGui
from vnpy_ctabacktester.ui.widget import StatisticsMonitor, BacktesterChart


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

        self.chart = BacktesterChart()
        self.chart.set_data(self.result_df)
        right_layout.addWidget(self.chart)

        layout.addLayout(right_layout, stretch=2)
