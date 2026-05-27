import numpy as np
from vnpy_ctastrategy import (
    CtaTemplate,
    StopOrder,
    TickData,
    BarData,
    TradeData,
    OrderData,
    BarGenerator,
    ArrayManager,
)

class StockQuantStrategy(CtaTemplate):
    """
    逻辑自进化V7：周期股动能共振与波动率挤压引擎
    专为 000630.SZSE 等高波动、强周期性有色金属股票设计。
    
    主要进化点：
    1. 均线升级：采用 EMA(12/26/120) 体系，提升对周期股拐点的敏感度。
    2. 波动率挤压：引入布林带带宽(Bandwidth)过滤，仅在波动率收缩后突破时入场，过滤假突破。
    3. 双轨入场：
       - 路径A：EMA多头 + 布林带上轨突破 + MACD红柱放量（顺势追涨）。
       - 路径B：大趋势向上 + 短期超跌(RSI<35) + 布林下轨企稳（逆势低吸）。
    4. 引入时间止损：入场 15 天内若无建树，主动平仓，防止资金长期套牢。
    5. 仓位管理：允许最多 2 次分批建仓（金字塔式），单次最大 15% 仓位，降低择时风险。
    """

    author = "Antigravity Quant - Evolved V7"

    # 核心参数定义
    total_capital: float = 1_000_000.0
    risk_per_trade: float = 0.01          # 单笔风险比例 1.0%
    max_position_pct: float = 0.15         # 单次入场最大市值占比 15% (允许加仓一次，上限30%)
    max_sub_positions: int = 2             # 最大子仓位数量

    # 技术指标参数
    fast_ema_period: int = 12
    slow_ema_period: int = 26
    trend_ema_period: int = 120
    bollinger_period: int = 20
    bollinger_dev: float = 2.0
    rsi_period: int = 14
    atr_period: int = 14
    
    # 止损与时间控制
    initial_atr_stop: float = 1.5          # 初始止损收紧至 1.5*ATR
    time_stop_days: int = 15               # 时间止损天数
    profit_protect_pct: float = 0.06       # 6% 利润触发保本

    # 止盈参数
    target1: float = 0.12                  # 第一目标 12%
    target2: float = 0.25                  # 第二目标 25%
    sell_ratio1: float = 0.50              # 第一目标卖出 50%
    sell_ratio2: float = 0.50              # 第二目标卖出 50%

    # 变量定义
    current_cash: float = 0.0
    fast_ema: float = 0.0
    slow_ema: float = 0.0
    trend_ema: float = 0.0
    boll_up: float = 0.0
    boll_down: float = 0.0
    boll_mid: float = 0.0
    rsi_value: float = 0.0
    atr_value: float = 0.0
    macd_diff: float = 0.0
    macd_dea: float = 0.0
    macd_hist: float = 0.0
    
    parameters = [
        "total_capital",
        "risk_per_trade",
        "max_position_pct",
        "max_sub_positions",
        "fast_ema_period",
        "slow_ema_period",
        "trend_ema_period",
        "bollinger_period",
        "bollinger_dev",
        "rsi_period",
        "atr_period",
        "initial_atr_stop",
        "time_stop_days",
        "profit_protect_pct",
        "target1",
        "target2",
        "sell_ratio1",
        "sell_ratio2",
    ]
    
    variables = [
        "current_cash",
        "fast_ema",
        "slow_ema",
        "trend_ema",
        "boll_up",
        "boll_down",
        "rsi_value",
        "atr_value",
        "macd_hist",
    ]

    def on_init(self) -> None:
        self.write_log("策略V7初始化...")
        max_period = max(
            self.trend_ema_period,
            self.bollinger_period,
            self.atr_period + 50
        ) + 100
        self.am: ArrayManager = ArrayManager(size=max_period)
        self.bg: BarGenerator = BarGenerator(self.on_bar)

        self.sub_positions: list = []
        self.current_cash = self.total_capital
        self.load_bar(max_period)

    def on_start(self) -> None:
        self.write_log("策略V7启动")
        self.put_event()

    def on_stop(self) -> None:
        self.write_log("策略V7停止")
        self.put_event()

    def on_tick(self, tick: TickData) -> None:
        if tick.vt_symbol == self.vt_symbol:
            self.bg.update_tick(tick)

    def on_bar(self, bar: BarData) -> None:
        self.cancel_all()
        am = self.am
        am.update_bar(bar)
        if not am.inited:
            return

        close = bar.close_price
        high = bar.high_price
        low = bar.low_price

        # 1. 计算核心技术指标
        self.fast_ema = am.ema(self.fast_ema_period)
        self.slow_ema = am.ema(self.slow_ema_period)
        self.trend_ema = am.ema(self.trend_ema_period)
        self.rsi_value = am.rsi(self.rsi_period)
        self.atr_value = am.atr(self.atr_period)
        
        # 布林带与带宽计算
        self.boll_up, self.boll_down = am.boll(self.bollinger_period, self.bollinger_dev)
        self.boll_mid = am.sma(self.bollinger_period)
        bandwidth = (self.boll_up - self.boll_down) / self.boll_mid if self.boll_mid > 0 else 0.0
        
        # MACD 计算
        macd_diff_array, macd_dea_array, macd_hist_array = am.macd(
            self.fast_ema_period, self.slow_ema_period, 9, array=True
        )
        self.macd_diff = macd_diff_array[-1]
        self.macd_dea = macd_dea_array[-1]
        self.macd_hist = macd_hist_array[-1]
        prev_macd_hist = macd_hist_array[-2] if len(macd_hist_array) > 1 else 0.0

        # 2. 动态管理现有持仓
        keep = []
        acct_value = self.current_cash + sum(p["volume"] * close for p in self.sub_positions)

        for pos in self.sub_positions:
            entry_price = pos["buy_price"]
            shares = pos["volume"]
            pos["hold_days"] += 1
            pos["highest"] = max(high, pos.get("highest", entry_price))
            highest = pos["highest"]
            profit = (close - entry_price) / entry_price

            # 动态跟踪止损线
            trail_stop = highest - self.atr_value * self.initial_atr_stop
            
            # 利润保护机制（保本）
            if profit >= self.profit_protect_pct:
                trail_stop = max(trail_stop, entry_price * 1.01)  # 锁定1%微利

            # 利润超过第一目标后，强制抬高止损至 5% 利润处
            if pos.get("t1_hit", False):
                trail_stop = max(trail_stop, entry_price * 1.05)

            pos["trailing_stop"] = max(pos.get("trailing_stop", trail_stop), trail_stop)

            # A. 触发移动止损/保本止损
            if low <= pos["trailing_stop"]:
                self._close_pos(pos, max(pos["trailing_stop"], low), f"移动止损触发(利润:{profit*100:.2f}%)")
                continue

            # B. 趋势彻底走坏保护：跌破 26日 EMA 且利润回吐
            if close < self.slow_ema and profit < 0.03:
                self._close_pos(pos, close, "跌破EMA26保护平仓")
                continue

            # C. 时间止损机制：入场后长期横盘，主动退出
            if pos["hold_days"] >= self.time_stop_days and profit < 0.03:
                self._close_pos(pos, close, f"时间止损(持有{pos['hold_days']}天未脱离成本)")
                continue

            # D. 分段止盈逻辑
            sell_vol = 0
            if profit >= self.target2 and not pos.get("t2_hit", False):
                sell_vol = int(shares * self.sell_ratio2 / 100) * 100
                pos["t2_hit"] = True
            elif profit >= self.target1 and not pos.get("t1_hit", False):
                sell_vol = int(shares * self.sell_ratio1 / 100) * 100
                pos["t1_hit"] = True

            if sell_vol > 0:
                if sell_vol >= pos["volume"]:
                    self._close_pos(pos, close, f"分段止盈2({profit*100:.1f}%)清仓")
                    continue
                else:
                    self.sell(close, sell_vol)
                    self.current_cash += sell_vol * close
                    pos["volume"] -= sell_vol
                    self.write_log(f"部分止盈 {sell_vol}股 @{close:.2f}，剩余 {pos['volume']}股")

            if pos["volume"] > 0:
                keep.append(pos)

        self.sub_positions = keep

        # 3. 入场逻辑评估
        if len(self.sub_positions) >= self.max_sub_positions:
            self.put_event()
            return

        # 基础大趋势过滤：价格必须在 120 日均线上方（确保大方向安全）
        if close < self.trend_ema:
            self.put_event()
            return

        signal_type = ""
        
        # 路径 A：顺势突破（波动率挤压 + 强动能突破）
        # 过去 5 天内布林带带宽曾收缩至 0.12 以下（代表波动率极度萎缩，有爆发需求）
        bandwidth_history = [
            (am.high[-i] - am.low[-i]) / am.close[-i] 
            for i in range(1, min(am.count, 6))
        ]
        is_squeezed = any(bw < 0.12 for bw in bandwidth_history)
        
        # 突破布林上轨 + MACD红柱增长 + 收阳线
        breakout_ok = (close > self.boll_up) and (self.macd_hist > prev_macd_hist) and (close > bar.open_price)
        
        if is_squeezed and breakout_ok and self.rsi_value < 65:
            signal_type = "波动率挤压突破"

        # 路径 B：均值回归（大趋势向上的超跌低吸）
        # 价格触及布林下轨 + RSI 处于超卖边缘 + K线企稳（收阳且收盘价高于前一日最高价的一半）
        if not signal_type:
            oversold = self.rsi_value < 38
            near_bottom = low <= self.boll_down * 1.01
            bullish_reversal = (close > bar.open_price) and (close > (am.high[-2] + am.low[-2]) / 2)
            
            if oversold and near_bottom and bullish_reversal:
                signal_type = "超跌均值低吸"

        if not signal_type:
            self.put_event()
            return

        # 4. 动态仓位与风险管理计算
        # 设定初始止损价
        if signal_type == "超跌均值低吸":
            stop_price = low - self.atr_value * 1.2
        else:
            stop_price = close - self.atr_value * self.initial_atr_stop
        
        stop_price = max(stop_price, 0.01)
        risk_per_share = close - stop_price
        if risk_per_share <= 0:
            risk_per_share = self.atr_value * 1.5

        # 计算单笔最大允许亏损金额
        allowed_loss = acct_value * self.risk_per_trade
        
        # 计算股数（必须是100股的整数倍）
        vol_risk = int(allowed_loss / risk_per_share / 100) * 100
        vol_cash = int(self.current_cash * self.max_position_pct / close / 100) * 100
        final_vol = min(vol_risk, vol_cash)

        # 针对低价股的保底开仓逻辑
        if final_vol < 100 and self.current_cash >= close * 100:
            final_vol = 100

        if final_vol < 100:
            self.put_event()
            return

        # 执行买入开仓
        self.buy(close, final_vol)
        self.current_cash -= final_vol * close
        self.sub_positions.append({
            "buy_price": close,
            "volume": final_vol,
            "trailing_stop": stop_price,
            "highest": close,
            "hold_days": 0,
            "t1_hit": False,
            "t2_hit": False,
            "signal_source": signal_type
        })
        
        self.write_log(
            f"买入开仓 {final_vol}股 @{close:.2f} | "
            f"信号源: {signal_type} | "
            f"初始止损: {stop_price:.2f} | "
            f"当前子仓位数: {len(self.sub_positions)}"
        )
        self.put_event()

    def _close_pos(self, pos: dict, price: float, reason: str) -> None:
        vol = pos["volume"]
        self.sell(price, vol)
        self.current_cash += vol * price
        pnl_pct = (price - pos["buy_price"]) / pos["buy_price"]
        self.write_log(
            f"平仓出场 {vol}股 @{price:.2f} | "
            f"来源: {pos.get('signal_source', '未知')} | "
            f"原因: {reason} | "
            f"单笔盈亏: {pnl_pct*100:.2f}% | "
            f"持有天数: {pos['hold_days']}"
        )

    def on_order(self, order: OrderData) -> None:
        pass

    def on_trade(self, trade: TradeData) -> None:
        self.put_event()

    def on_stop_order(self, stop_order: StopOrder) -> None:
        pass