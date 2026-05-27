# -*- coding: utf-8 -*-
import numpy as np
from PySide6 import QtWidgets, QtCore, QtGui
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from vnpy.trader.constant import Direction, Offset


class PortfolioSimulatorWindow(QtWidgets.QDialog):
    """
    一键多股组合资金分配与截面模拟大屏 (至尊暗黑风)
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("💼 一键多股组合资金分配模拟器")
        self.resize(1200, 800)
        self.setStyleSheet("background-color: #1a1a1a; color: #ffffff;")

        # Layout
        main_layout = QtWidgets.QHBoxLayout(self)

        # Left Column: Parameters & Results
        left_layout = QtWidgets.QVBoxLayout()
        left_layout.setContentsMargins(10, 10, 10, 10)

        # Group 1: Parameters
        param_group = QtWidgets.QGroupBox("⚙️ 组合资金分配控制")
        param_layout = QtWidgets.QGridLayout(param_group)

        param_layout.addWidget(QtWidgets.QLabel("组合总本金 (元):"), 0, 0)
        self.capital_spin = QtWidgets.QDoubleSpinBox()
        self.capital_spin.setRange(10000.0, 100000000.0)
        self.capital_spin.setSingleStep(50000.0)
        self.capital_spin.setValue(1000000.0)
        self.capital_spin.setDecimals(1)
        self.capital_spin.setStyleSheet("background-color: #2b2b2b; color: #ffffff;")
        param_layout.addWidget(self.capital_spin, 0, 1)

        param_layout.addWidget(QtWidgets.QLabel("最大持仓个股数量:"), 1, 0)
        self.max_holdings_spin = QtWidgets.QSpinBox()
        self.max_holdings_spin.setRange(1, 50)
        self.max_holdings_spin.setValue(5)
        self.max_holdings_spin.setStyleSheet("background-color: #2b2b2b; color: #ffffff;")
        param_layout.addWidget(self.max_holdings_spin, 1, 1)

        param_layout.addWidget(QtWidgets.QLabel("单股最大资金占比:"), 2, 0)
        self.max_pct_spin = QtWidgets.QDoubleSpinBox()
        self.max_pct_spin.setRange(0.01, 1.0)
        self.max_pct_spin.setSingleStep(0.05)
        self.max_pct_spin.setValue(0.20)  # 20%
        self.max_pct_spin.setDecimals(2)
        self.max_pct_spin.setStyleSheet("background-color: #2b2b2b; color: #ffffff;")
        param_layout.addWidget(self.max_pct_spin, 2, 1)

        left_layout.addWidget(param_group)

        # Run Button
        self.run_btn = QtWidgets.QPushButton("⚡ 开始组合资金优化回测")
        self.run_btn.setFixedHeight(45)
        self.run_btn.setStyleSheet("""
            QPushButton {
                background-color: #008c8c;
                color: white;
                font-weight: bold;
                font-size: 13px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #00aaaa;
            }
        """)
        self.run_btn.clicked.connect(self.run_simulation)
        left_layout.addWidget(self.run_btn)

        # Group 2: Results Table
        res_group = QtWidgets.QGroupBox("📋 组合优化业绩指标")
        res_layout = QtWidgets.QVBoxLayout(res_group)
        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(2)
        self.table.setRowCount(8)
        self.table.setHorizontalHeaderLabels(["业绩指标", "模拟数值"])
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #1e1e1e;
                color: #dddddd;
                gridline-color: #2e2e2e;
            }
        """)
        
        metrics = [
            "组合初始资金", "组合期末净值", "组合总盈亏", 
            "组合总收益率", "组合年化收益", "最大资金回撤", 
            "百分比最大回撤", "组合夏普比率"
        ]
        for i, metric in enumerate(metrics):
            item_name = QtWidgets.QTableWidgetItem(metric)
            item_name.setFont(QtGui.QFont("Segoe UI", 9, QtGui.QFont.Weight.Bold))
            item_value = QtWidgets.QTableWidgetItem("-")
            item_value.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(i, 0, item_name)
            self.table.setItem(i, 1, item_value)

        res_layout.addWidget(self.table)
        left_layout.addWidget(res_group)

        # Close Button
        close_btn = QtWidgets.QPushButton("关闭组合看板")
        close_btn.setFixedHeight(35)
        close_btn.setStyleSheet("background-color: #555; color: #fff; border-radius: 4px;")
        close_btn.clicked.connect(self.reject)
        left_layout.addWidget(close_btn)

        # Right Column: Tabbed Panel (Chart and Tables)
        right_layout = QtWidgets.QVBoxLayout()
        right_layout.setContentsMargins(10, 10, 10, 10)

        self.right_tabs = QtWidgets.QTabWidget()
        self.right_tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #444444;
                background-color: #1a1a1a;
            }
            QTabBar::tab {
                background-color: #2b2b2b;
                color: #dddddd;
                padding: 8px 16px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                margin-right: 2px;
                font-weight: bold;
            }
            QTabBar::tab:selected {
                background-color: #008c8c;
                color: #ffffff;
            }
            QTabBar::tab:hover {
                background-color: #3b3b3b;
            }
        """)

        # Tab 1: Chart
        chart_widget = QtWidgets.QWidget()
        chart_vbox = QtWidgets.QVBoxLayout(chart_widget)
        
        self.fig = Figure(figsize=(7, 5), facecolor='#1a1a1a')
        self.canvas = FigureCanvas(self.fig)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_facecolor('#1a1a1a')
        self.ax.spines['bottom'].set_color('#555555')
        self.ax.spines['top'].set_color('#555555')
        self.ax.spines['left'].set_color('#555555')
        self.ax.spines['right'].set_color('#555555')
        self.ax.tick_params(axis='x', colors='#ffffff')
        self.ax.tick_params(axis='y', colors='#ffffff')
        self.ax.yaxis.label.set_color('#ffffff')
        self.ax.xaxis.label.set_color('#ffffff')
        self.ax.title.set_color('#ffffff')
        
        chart_vbox.addWidget(self.canvas)
        self.right_tabs.addTab(chart_widget, "📈 组合资产净值增长曲线")

        # Tab 2: Exposure Chart
        exposure_widget = QtWidgets.QWidget()
        exposure_vbox = QtWidgets.QVBoxLayout(exposure_widget)
        
        self.fig_exp = Figure(figsize=(7, 5), facecolor='#1a1a1a')
        self.canvas_exp = FigureCanvas(self.fig_exp)
        self.ax_exp_cash = self.fig_exp.add_subplot(111)
        self.ax_exp_cash.set_facecolor('#1a1a1a')
        
        self.ax_exp_holdings = self.ax_exp_cash.twinx()
        
        self.ax_exp_cash.spines['bottom'].set_color('#555555')
        self.ax_exp_cash.spines['top'].set_color('#555555')
        self.ax_exp_cash.spines['left'].set_color('#555555')
        self.ax_exp_cash.spines['right'].set_color('#555555')
        self.ax_exp_cash.tick_params(axis='x', colors='#ffffff')
        self.ax_exp_cash.tick_params(axis='y', colors='#ffb84d')
        self.ax_exp_cash.yaxis.label.set_color('#ffb84d')
        self.ax_exp_cash.xaxis.label.set_color('#ffffff')
        
        self.ax_exp_holdings.tick_params(axis='y', colors='#80e5ff')
        self.ax_exp_holdings.yaxis.label.set_color('#80e5ff')
        
        exposure_vbox.addWidget(self.canvas_exp)
        self.right_tabs.addTab(exposure_widget, "📊 组合资金占用与仓位暴露")

        # Tab 3: Logs
        details_widget = QtWidgets.QWidget()
        details_layout = QtWidgets.QVBoxLayout(details_widget)
        
        self.details_tabs = QtWidgets.QTabWidget()
        
        # Sub-tab 1: Trades Table
        self.trades_table = QtWidgets.QTableWidget()
        self.trades_table.setColumnCount(7)
        self.trades_table.setHorizontalHeaderLabels([
            "成交时间", "股票代码", "动作", "成交均价", "成交数量", "变动现金", "剩余现金"
        ])
        self.trades_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.trades_table.setStyleSheet("background-color: #121212; gridline-color: #2b2b2b;")
        
        # Sub-tab 2: Daily PnL Table
        self.daily_table = QtWidgets.QTableWidget()
        self.daily_table.setColumnCount(6)
        self.daily_table.setHorizontalHeaderLabels([
            "交易日期", "总资产净值", "可用现金", "当前持仓股票", "持仓只数", "日盈亏"
        ])
        self.daily_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.daily_table.setStyleSheet("background-color: #121212; gridline-color: #2b2b2b;")
        
        self.details_tabs.addTab(self.trades_table, "📜 组合历史成交明细 (实际执行)")
        self.details_tabs.addTab(self.daily_table, "🗃️ 组合每日盯市与持仓明细")
        
        details_layout.addWidget(self.details_tabs)
        self.right_tabs.addTab(details_widget, "🤝 组合历史成交与每日持仓细节")

        right_layout.addWidget(self.right_tabs)

        # Add columns to main layout
        main_layout.addLayout(left_layout, 2)
        main_layout.addLayout(right_layout, 5)

    def run_simulation(self):
        try:
            # 🚨 字体修复补丁：强制配置 Matplotlib 在 Windows 环境下支持完美的中文渲染，解决小方块乱码！
            import matplotlib
            matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'Segoe UI', 'Arial']
            matplotlib.rcParams['axes.unicode_minus'] = False

            # 1. Read parameters
            total_capital = self.capital_spin.value()
            max_holdings = self.max_holdings_spin.value()
            max_allocation_pct = self.max_pct_spin.value()

            # 2. Extract trades and dates
            parent = self.parent_app
            all_trades = []
            all_dates = set()
            daily_closes = {}

            for vt_symbol, engine in parent.backtest_engines.items():
                daily_closes[vt_symbol] = {}
                # Extract trades
                for trade in engine.trades.values():
                    all_trades.append({
                        "vt_symbol": vt_symbol,
                        "symbol": trade.symbol,
                        "exchange": trade.exchange,
                        "price": trade.price,
                        "volume": trade.volume,
                        "direction": trade.direction,
                        "offset": trade.offset,
                        "datetime": trade.datetime
                    })
                # Extract daily closes
                for date_key, daily_res in engine.daily_results.items():
                    all_dates.add(date_key)
                    daily_closes[vt_symbol][date_key] = daily_res.close_price

            if not all_trades:
                QtWidgets.QMessageBox.warning(self, "提示", "所有回测个股均无成交记录，无法进行资金分配模拟！")
                return

            sorted_dates = sorted(list(all_dates))
            all_trades.sort(key=lambda x: x["datetime"])

            # Group trades by date
            trades_by_date = {}
            for t in all_trades:
                t_date = t["datetime"].date()
                if t_date not in trades_by_date:
                    trades_by_date[t_date] = []
                trades_by_date[t_date].append(t)

            # 3. Simulate day-by-day
            portfolio_cash = total_capital
            holdings = {} # {vt_symbol: {"volume": volume, "entry_price": entry_price}}
            daily_equity = []
            daily_cash = []
            daily_holdings_cnt = []
            portfolio_trades_log = []
            portfolio_daily_log = []
            rate = 0.0003  # 0.03% commission rate

            for d in sorted_dates:
                day_trades = trades_by_date.get(d, [])
                
                # A. Handle SELLs first to release cash
                for t in day_trades:
                    is_sell = (t["direction"] == Direction.SHORT or 
                               t["direction"].value == "空" or 
                               t["offset"] == Offset.CLOSE or 
                               t["offset"].value == "平")
                    if is_sell:
                        vt_symbol = t["vt_symbol"]
                        if vt_symbol in holdings:
                            shares = holdings[vt_symbol]["volume"]
                            sell_price = t["price"]
                            gross_value = shares * sell_price
                            commission = gross_value * rate
                            net_cash_returned = gross_value - commission
                            portfolio_cash += net_cash_returned
                            
                            portfolio_trades_log.append({
                                "datetime": t["datetime"].strftime("%Y-%m-%d %H:%M:%S"),
                                "vt_symbol": vt_symbol,
                                "direction": "卖出",
                                "price": f"¥{sell_price:,.2f}",
                                "volume": f"{shares} 股",
                                "cash_change": f"+¥{net_cash_returned:,.2f}",
                                "remaining_cash": f"¥{portfolio_cash:,.2f}"
                            })
                            del holdings[vt_symbol]

                # B. Handle BUYs second if we have slots and cash
                max_single_stock_capital = total_capital * max_allocation_pct
                for t in day_trades:
                    is_buy = (t["direction"] == Direction.LONG or 
                              t["direction"].value == "多" or 
                              t["offset"] == Offset.OPEN or 
                              t["offset"].value == "开")
                    if is_buy:
                        vt_symbol = t["vt_symbol"]
                        if vt_symbol not in holdings and len(holdings) < max_holdings:
                            entry_price = t["price"]
                            shares = int(max_single_stock_capital / entry_price / 100) * 100
                            if shares >= 100:
                                cost = shares * entry_price
                                commission = cost * rate
                                total_cost = cost + commission
                                if portfolio_cash >= total_cost:
                                    portfolio_cash -= total_cost
                                    holdings[vt_symbol] = {
                                        "volume": shares,
                                        "entry_price": entry_price
                                    }
                                    portfolio_trades_log.append({
                                        "datetime": t["datetime"].strftime("%Y-%m-%d %H:%M:%S"),
                                        "vt_symbol": vt_symbol,
                                        "direction": "买入",
                                        "price": f"¥{entry_price:,.2f}",
                                        "volume": f"{shares} 股",
                                        "cash_change": f"-¥{total_cost:,.2f}",
                                        "remaining_cash": f"¥{portfolio_cash:,.2f}"
                                    })

                # C. Compute total portfolio value at market close
                current_holdings_value = 0.0
                for vt_symbol, hold in holdings.items():
                    close_price = daily_closes[vt_symbol].get(d, None)
                    if close_price is None:
                        close_price = hold["entry_price"]
                    current_holdings_value += hold["volume"] * close_price

                total_equity = portfolio_cash + current_holdings_value
                daily_equity.append(total_equity)
                daily_cash.append(portfolio_cash)
                daily_holdings_cnt.append(len(holdings))

                # Holdings description string
                holdings_desc = ", ".join([f"{symbol}({hold['volume']}股)" for symbol, hold in holdings.items()]) if holdings else "空仓"
   
                daily_pnl = total_equity - daily_equity[-2] if len(daily_equity) > 1 else 0.0
   
                portfolio_daily_log.append({
                    "date": d.strftime("%Y-%m-%d"),
                    "total_equity": f"¥{total_equity:,.2f}",
                    "available_cash": f"¥{portfolio_cash:,.2f}",
                    "holdings": holdings_desc,
                    "holdings_count": f"{len(holdings)} 只",
                    "daily_pnl": f"{'+' if daily_pnl > 0 else ''}¥{daily_pnl:,.2f}",
                    "daily_pnl_raw": daily_pnl
                })

            # 4. Compute statistics
            end_equity = daily_equity[-1]
            total_net_pnl = end_equity - total_capital
            total_return = (total_net_pnl / total_capital) * 100.0

            total_days = len(sorted_dates)
            annual_return = ((end_equity / total_capital) ** (252 / total_days) - 1) * 100.0 if total_days > 0 else 0.0

            # Drawdown
            max_equity = total_capital
            max_dd_val = 0.0
            max_dd_pct = 0.0
            for eq in daily_equity:
                if eq > max_equity:
                    max_equity = eq
                dd_val = eq - max_equity
                dd_pct = (eq - max_equity) / max_equity * 100.0
                if dd_pct < max_dd_pct:
                    max_dd_pct = dd_pct
                if dd_val < max_dd_val:
                    max_dd_val = dd_val

            # Sharpe
            daily_returns = []
            for i in range(1, len(daily_equity)):
                ret = (daily_equity[i] - daily_equity[i-1]) / daily_equity[i-1]
                daily_returns.append(ret)
            if daily_returns:
                avg_ret = sum(daily_returns) / len(daily_returns)
                std_ret = np.std(daily_returns)
                sharpe = (avg_ret / std_ret * np.sqrt(252)) if std_ret > 0 else 0.0
            else:
                sharpe = 0.0

            # 5. Populate Table
            self.table.item(0, 1).setText(f"¥{total_capital:,.2f}")
            self.table.item(1, 1).setText(f"¥{end_equity:,.2f}")
            
            pnl_item = self.table.item(2, 1)
            pnl_item.setText(f"¥{total_net_pnl:,.2f}")
            pnl_item.setForeground(QtGui.QColor(255, 100, 100) if total_net_pnl >= 0 else QtGui.QColor(100, 255, 100))
            pnl_item.setFont(QtGui.QFont("Segoe UI", 9, QtGui.QFont.Weight.Bold))

            ret_item = self.table.item(3, 1)
            ret_item.setText(f"{total_return:.2f}%")
            ret_item.setForeground(QtGui.QColor(255, 100, 100) if total_return >= 0 else QtGui.QColor(100, 255, 100))
            ret_item.setFont(QtGui.QFont("Segoe UI", 9, QtGui.QFont.Weight.Bold))

            ann_item = self.table.item(4, 1)
            ann_item.setText(f"{annual_return:.2f}%")
            ann_item.setForeground(QtGui.QColor(255, 100, 100) if annual_return >= 0 else QtGui.QColor(100, 255, 100))
            ann_item.setFont(QtGui.QFont("Segoe UI", 9, QtGui.QFont.Weight.Bold))

            self.table.item(5, 1).setText(f"¥{max_dd_val:,.2f}")
            
            dd_item = self.table.item(6, 1)
            dd_item.setText(f"{max_dd_pct:.2f}%")
            dd_item.setForeground(QtGui.QColor(100, 180, 255))
            dd_item.setFont(QtGui.QFont("Segoe UI", 9, QtGui.QFont.Weight.Bold))

            self.table.item(7, 1).setText(f"{sharpe:.2f}")

            # 6. Populating Trades Table
            self.trades_table.setRowCount(0)
            self.trades_table.setRowCount(len(portfolio_trades_log))
            for row_idx, log in enumerate(portfolio_trades_log):
                for col_idx, key in enumerate(["datetime", "vt_symbol", "direction", "price", "volume", "cash_change", "remaining_cash"]):
                    item = QtWidgets.QTableWidgetItem(log[key])
                    item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                    if key == "direction":
                        if log[key] == "买入":
                            item.setForeground(QtGui.QColor(255, 100, 100))
                            item.setFont(QtGui.QFont("Segoe UI", 9, QtGui.QFont.Weight.Bold))
                        else:
                            item.setForeground(QtGui.QColor(100, 255, 100))
                            item.setFont(QtGui.QFont("Segoe UI", 9, QtGui.QFont.Weight.Bold))
                    elif key == "cash_change":
                        if log[key].startswith("+"):
                            item.setForeground(QtGui.QColor(100, 255, 100))
                        else:
                            item.setForeground(QtGui.QColor(255, 100, 100))
                    elif key == "vt_symbol":
                        item.setForeground(QtGui.QColor(100, 200, 255))
                    self.trades_table.setItem(row_idx, col_idx, item)

            # 7. Populating Daily Table
            self.daily_table.setRowCount(0)
            self.daily_table.setRowCount(len(portfolio_daily_log))
            for row_idx, log in enumerate(portfolio_daily_log):
                for col_idx, key in enumerate(["date", "total_equity", "available_cash", "holdings", "holdings_count", "daily_pnl"]):
                    item = QtWidgets.QTableWidgetItem(log[key])
                    item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                    if key == "daily_pnl":
                        raw_pnl = log["daily_pnl_raw"]
                        if raw_pnl > 0:
                            item.setForeground(QtGui.QColor(255, 100, 100))
                            item.setFont(QtGui.QFont("Segoe UI", 9, QtGui.QFont.Weight.Bold))
                        elif raw_pnl < 0:
                            item.setForeground(QtGui.QColor(100, 255, 100))
                            item.setFont(QtGui.QFont("Segoe UI", 9, QtGui.QFont.Weight.Bold))
                    elif key == "holdings":
                        item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)
                        if log[key] != "空仓":
                            item.setForeground(QtGui.QColor(255, 215, 0))
                    self.daily_table.setItem(row_idx, col_idx, item)

            # 8. Plot NAV Chart
            self.ax.clear()
            self.ax.set_title("📈 组合分配下总净值资金增长曲线 (Net Asset Value Curve)", color='#ffffff', fontsize=12, fontweight='bold')
            self.ax.set_ylabel("账户净值 (元)", color='#ffffff')
            self.ax.set_xlabel("回测时间周期", color='#ffffff')
            
            dates_display = [d.strftime('%Y-%m') for d in sorted_dates]
            x_indices = np.linspace(0, len(sorted_dates)-1, 8, dtype=int)
            x_labels = [dates_display[i] for i in x_indices]
            
            self.ax.plot(sorted_dates, daily_equity, label="组合资产净值", color="#00dddd", linewidth=2.0)
            self.ax.axhline(total_capital, color="#888888", linestyle="--", alpha=0.7)
            self.ax.set_xticks([sorted_dates[i] for i in x_indices])
            self.ax.set_xticklabels(x_labels, rotation=15)
            self.ax.legend(facecolor='#1a1a1a', labelcolor='#ffffff')
            self.ax.grid(True, color="#333333", linestyle=":")
            
            self.canvas.draw()

            # 9. Plot Exposure Chart
            self.ax_exp_cash.clear()
            self.ax_exp_holdings.clear()
            
            self.ax_exp_cash.set_title("📊 组合资金占用与持仓数量波动图 (Exposure & Cash Allocation)", color='#ffffff', fontsize=12, fontweight='bold')
            self.ax_exp_cash.set_ylabel("可用现金池金额 (元)", color='#ffb84d')
            self.ax_exp_cash.set_xlabel("回测时间周期", color='#ffffff')
            self.ax_exp_holdings.set_ylabel("当前持仓个股数量 (只)", color='#80e5ff')
            
            self.ax_exp_cash.fill_between(sorted_dates, daily_cash, color="#ffb84d", alpha=0.15, label="可用现金金额")
            self.ax_exp_cash.plot(sorted_dates, daily_cash, color="#ffb84d", linewidth=1.5, alpha=0.85)
            self.ax_exp_holdings.step(sorted_dates, daily_holdings_cnt, where='post', color="#80e5ff", linewidth=2.0, label="持仓个股数")
            
            lines_1, labels_1 = self.ax_exp_cash.get_legend_handles_labels()
            lines_2, labels_2 = self.ax_exp_holdings.get_legend_handles_labels()
            self.ax_exp_cash.legend(lines_1 + lines_2, labels_1 + labels_2, facecolor='#1a1a1a', labelcolor='#ffffff')
            
            self.ax_exp_cash.set_xticks([sorted_dates[i] for i in x_indices])
            self.ax_exp_cash.set_xticklabels(x_labels, rotation=15)
            self.ax_exp_cash.grid(True, color="#333333", linestyle=":")
            
            self.canvas_exp.draw()

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "模拟错误", f"组合资金分配模拟运行失败，原因：\n{str(e)}")
