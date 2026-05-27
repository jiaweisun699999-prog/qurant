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
    逻辑自进化V5：趋势跟踪引擎
    主要改进：
    1. 趋势判定：双均线金叉 + 长期均线确认，取消ADX硬阈值
    2. 入场：回调至中期均线附近的低吸信号，辅以突破近期高点
    3. 出场：宽幅移动止损，分段止盈目标调高，移除时间止损
    4. 风险管理：动态仓位，保留账户回撤与连续亏损暂停
    5. 市场环境：可选基准过滤，也可仅用长期均线
    """

    author = "Antigravity Quant - Evolved V5"

    # 资金参数
    total_capital: float = 1_000_000.0
    risk_per_trade: float = 0.01            # 单笔风险比例（动态权益）
    max_position_pct: float = 0.25          # 单次入场最大市值占比

    # 趋势均线参数
    fast_ema_period: int = 20
    slow_ema_period: int = 60
    very_slow_ema_period: int = 120

    # 回调入场
    pullback_tolerance: float = 0.015       # 价格接近中期均线的最大偏离
    pullback_lookback: int = 5              # 回调确认需要近期最低点接近均线

    # 突破入场
    breakout_period: int = 60               # 唐奇安通道周期

    # 成交量参考
    vol_period: int = 20

    # ATR与止损
    atr_period: int = 14
    initial_atr_stop: float = 3.0           # 初始追踪止损 ATR 倍数
    stop_atr_profit1: float = 2.0           # 盈利 >10% 时的 ATR 倍数
    stop_atr_profit2: float = 1.5           # 盈利 >20% 时的 ATR 倍数
    profit_level1: float = 0.10
    profit_level2: float = 0.20

    # 分段止盈
    target1: float = 0.30
    target2: float = 0.50
    target3: float = 0.80
    sell_ratio1: float = 0.20               # 第一目标卖出20%
    sell_ratio2: float = 0.20               # 第二目标再卖20%
    # 第三目标清仓

    # 风控
    max_acct_dd_pause: float = 0.15         # 账户回撤超15%暂停
    acct_dd_reduce: float = 0.10            # 回撤超10%风险减半
    max_consecutive_losses: int = 4

    # 基准过滤
    benchmark_ma_period: int = 60
    use_benchmark: bool = True
    benchmark_symbol: str = "000300.SHSE"

    # 变量
    current_cash: float = 0.0
    fast_ema: float = 0.0
    slow_ema: float = 0.0
    very_slow_ema: float = 0.0
    atr: float = 0.0
    consecutive_losses: int = 0
    is_market_uptrend: bool = True
    account_peak_value: float = 0.0
    is_trading_paused: bool = False
    current_risk_pct: float = 0.0

    parameters = [
        "total_capital",
        "risk_per_trade",
        "max_position_pct",
        "fast_ema_period",
        "slow_ema_period",
        "very_slow_ema_period",
        "pullback_tolerance",
        "pullback_lookback",
        "breakout_period",
        "vol_period",
        "atr_period",
        "initial_atr_stop",
        "stop_atr_profit1",
        "stop_atr_profit2",
        "profit_level1",
        "profit_level2",
        "target1",
        "target2",
        "target3",
        "sell_ratio1",
        "sell_ratio2",
        "max_acct_dd_pause",
        "acct_dd_reduce",
        "max_consecutive_losses",
        "benchmark_ma_period",
        "use_benchmark",
    ]
    variables = [
        "current_cash",
        "fast_ema",
        "slow_ema",
        "very_slow_ema",
        "atr",
        "consecutive_losses",
        "is_market_uptrend",
        "account_peak_value",
        "is_trading_paused",
        "current_risk_pct",
    ]

    def on_init(self) -> None:
        self.write_log("策略V5初始化...")
        max_period = max(
            self.very_slow_ema_period,
            self.breakout_period,
            self.atr_period + 50
        ) + 200
        self.am: ArrayManager = ArrayManager(size=max_period)
        self.bg: BarGenerator = BarGenerator(self.on_bar)

        # 基准指数
        self.benchmark_am: ArrayManager = ArrayManager(size=max_period)
        self.bg_benchmark: BarGenerator = BarGenerator(
            self.on_bar, window=1, on_window_bar=self.on_benchmark_bar
        )

        self.sub_positions: list = []
        self.current_cash = self.total_capital
        self.account_peak_value = self.total_capital
        self.current_risk_pct = self.risk_per_trade
        self.load_bar(max_period)

    def on_start(self) -> None:
        self.write_log("策略V5启动")
        self.put_event()

    def on_stop(self) -> None:
        self.write_log("策略V5停止")
        self.put_event()

    def on_tick(self, tick: TickData) -> None:
        if tick.vt_symbol == self.vt_symbol:
            self.bg.update_tick(tick)
        elif tick.vt_symbol == self.benchmark_symbol:
            self.bg_benchmark.update_tick(tick)

    def on_bar(self, bar: BarData) -> None:
        self.cancel_all()
        am = self.am
        am.update_bar(bar)
        if not am.inited:
            return

        close = bar.close_price
        high = bar.high_price
        low = bar.low_price
        volume = bar.volume

        # 指标更新
        self.fast_ema = am.ema(self.fast_ema_period)
        self.slow_ema = am.ema(self.slow_ema_period)
        self.very_slow_ema = am.ema(self.very_slow_ema_period)
        self.atr = am.atr(self.atr_period)

        # 账户状态
        acct_value = self.current_cash + sum(
            p["volume"] * close for p in self.sub_positions
        )
        self.account_peak_value = max(self.account_peak_value, acct_value)
        dd = (self.account_peak_value - acct_value) / self.account_peak_value if self.account_peak_value > 0 else 0.0

        if dd >= self.max_acct_dd_pause:
            self.current_risk_pct = 0.0
            self.is_trading_paused = True
        elif dd >= self.acct_dd_reduce:
            self.current_risk_pct = self.risk_per_trade * 0.5
            self.is_trading_paused = False
        else:
            self.current_risk_pct = self.risk_per_trade
            self.is_trading_paused = False

        if self.consecutive_losses >= self.max_consecutive_losses:
            self.is_trading_paused = True

        # 市场环境
        if self.use_benchmark and self.benchmark_am.inited:
            bm_close = self.benchmark_am.close[-1]
            bm_ma = self.benchmark_am.ema(self.benchmark_ma_period)
            self.is_market_uptrend = bm_close > bm_ma
        else:
            self.is_market_uptrend = close > self.very_slow_ema

        vol_ma = np.mean(am.volume[-self.vol_period:]) if am.count >= self.vol_period else volume
        vol_ratio = volume / vol_ma if vol_ma > 0 else 1.0

        # ──── 管理现有持仓 ────
        keep = []
        for pos in self.sub_positions:
            entry_price = pos["buy_price"]
            shares = pos["volume"]
            pos["highest"] = max(high, pos.get("highest", entry_price))
            highest = pos["highest"]
            profit = (close - entry_price) / entry_price

            # 移动止损计算
            if profit < self.profit_level1:
                stop_mult = self.initial_atr_stop
            elif profit < self.profit_level2:
                stop_mult = self.stop_atr_profit1
            else:
                stop_mult = self.stop_atr_profit2

            trail_stop = highest - self.atr * stop_mult
            # 保本止损
            if profit > 0.05:
                trail_stop = max(trail_stop, entry_price)

            # 更新 trailing_stop
            pos["trailing_stop"] = max(pos.get("trailing_stop", trail_stop), trail_stop)

            # 价格触发移动止损
            if low <= pos["trailing_stop"]:
                self._close_pos(pos, max(pos["trailing_stop"], low), "移动止损")
                continue

            # 终极清仓：跌破长期均线
            if close < self.very_slow_ema:
                self._close_pos(pos, close, "跌破长期均线")
                continue

            # 分段止盈
            sell_vol = 0
            if profit >= self.target3 and not pos.get("t3_hit", False):
                sell_vol = shares  # 清仓
                pos["t3_hit"] = True
            elif profit >= self.target2 and not pos.get("t2_hit", False):
                sell_vol = int(shares * self.sell_ratio2 / 100) * 100
                pos["t2_hit"] = True
            elif profit >= self.target1 and not pos.get("t1_hit", False):
                sell_vol = int(shares * self.sell_ratio1 / 100) * 100
                pos["t1_hit"] = True
                # 剩余仓位保本
                pos["trailing_stop"] = max(pos["trailing_stop"], entry_price)

            if sell_vol > 0:
                if sell_vol >= shares:
                    self._close_pos(pos, close, f"分段止盈{profit*100:.1f}%清仓")
                    continue
                else:
                    self.sell(close, sell_vol)
                    self.current_cash += sell_vol * close
                    pos["volume"] -= sell_vol
                    self.consecutive_losses = 0
                    self.write_log(f"部分止盈 {sell_vol}股 @{close:.2f}")

            if pos["volume"] > 0:
                keep.append(pos)

        self.sub_positions = keep

        # ──── 入场条件 ────
        if self.sub_positions or self.is_trading_paused:
            self.put_event()
            return

        # 趋势确认：快线在慢线上方，价格在长期均线上方
        trend_ok = (self.fast_ema > self.slow_ema) and (close > self.very_slow_ema)

        # 市场辅助过滤
        if not self.is_market_uptrend:
            trend_ok = False

        if not trend_ok:
            self.put_event()
            return

        # 信号1：回调到中期均线附近
        pullback_ma = self.slow_ema  # 使用慢速均线作为回调参考
        near_ma = abs(low - pullback_ma) / pullback_ma < self.pullback_tolerance
        # 最近5根K线有低点接近均线
        recent_lows = am.low[-self.pullback_lookback:]
        near_recent = any(abs(l - pullback_ma) / pullback_ma < self.pullback_tolerance for l in recent_lows)
        bullish_candle = close > bar.open_price
        signal_pullback = near_ma and near_recent and bullish_candle

        # 信号2：突破近期高点
        highest_br = am.high[-self.breakout_period:].max()
        signal_breakout = close > highest_br and bullish_candle

        if not (signal_pullback or signal_breakout):
            self.put_event()
            return

        # 计算初始止损 (基于ATR)
        if signal_pullback:
            stop_price = low - self.atr * 2.0
        else:
            stop_price = highest_br - self.atr * 2.0
        stop_price = max(stop_price, 0.01)

        # 仓位计算
        risk_share = close - stop_price
        if risk_share <= 0:
            risk_share = self.atr * 2.0
        max_loss = acct_value * self.current_risk_pct
        vol_risk = int(max_loss / risk_share / 100) * 100
        vol_cash = int(self.current_cash * self.max_position_pct / close / 100) * 100
        final_vol = min(vol_risk, vol_cash)
        if final_vol < 100:
            # 若不足100股且条件允许，以100股入场，控制风险
            if vol_cash >= 100:
                final_vol = 100
            else:
                self.put_event()
                return

        self.buy(close, final_vol)
        self.current_cash -= final_vol * close
        self.sub_positions.append({
            "buy_price": close,
            "volume": final_vol,
            "trailing_stop": stop_price,
            "highest": close,
            "t1_hit": False,
            "t2_hit": False,
            "t3_hit": False,
        })
        msg = f"买入 {final_vol}股 @{close:.2f} 止损{stop_price:.2f}"
        self.write_log(msg)
        self.put_event()

    def on_benchmark_bar(self, bar: BarData) -> None:
        if bar.vt_symbol == self.benchmark_symbol:
            self.benchmark_am.update_bar(bar)

    def _close_pos(self, pos: dict, price: float, reason: str) -> None:
        vol = pos["volume"]
        self.sell(price, vol)
        self.current_cash += vol * price
        pnl_pct = (price - pos["buy_price"]) / pos["buy_price"]
        if pnl_pct > 0:
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
        self.write_log(f"平仓 {vol}股 @{price:.2f} 原因:{reason} 盈亏:{pnl_pct*100:.2f}%")

    def on_order(self, order: OrderData) -> None:
        pass

    def on_trade(self, trade: TradeData) -> None:
        self.put_event()

    def on_stop_order(self, stop_order: StopOrder) -> None:
        pass