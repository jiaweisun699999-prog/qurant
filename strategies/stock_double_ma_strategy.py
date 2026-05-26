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


class StockDoubleMaStrategy(CtaTemplate):
    """
    A股专用双均线单边做多策略 (Stock Long-Only Double MA Strategy)
    - 仅限做多，不支持做空，完全符合A股普通交易规则
    - 金叉买入，死叉卖出
    """

    author = "Antigravity Quant"

    # 策略参数
    fast_window: int = 10      # 短周期均线窗口
    slow_window: int = 30      # 长周期均线窗口
    fixed_size: int = 100000    # 默认交易数量 (A股按百股单位进行买卖)

    # 策略变量
    fast_ma0: float = 0.0      # 当前快均线值
    fast_ma1: float = 0.0      # 上一期快均线值
    slow_ma0: float = 0.0      # 当前慢均线值
    slow_ma1: float = 0.0      # 上一期慢均线值

    parameters = ["fast_window", "slow_window", "fixed_size"]
    variables = ["fast_ma0", "fast_ma1", "slow_ma0", "slow_ma1"]

    def on_init(self) -> None:
        """
        策略初始化回调，加载历史数据并初始化指标
        """
        self.write_log("A股双均线策略初始化...")

        self.bg: BarGenerator = BarGenerator(self.on_bar)
        self.am: ArrayManager = ArrayManager()

        # 加载 10 天的历史 K 线来预热计算均线指标
        self.load_bar(10)

    def on_start(self) -> None:
        """
        策略启动回调
        """
        self.write_log("A股双均线策略启动！")
        self.put_event()

    def on_stop(self) -> None:
        """
        策略停止回调
        """
        self.write_log("A股双均线策略停止。")
        self.put_event()

    def on_tick(self, tick: TickData) -> None:
        """
        实时 Tick 数据更新回调
        """
        self.bg.update_tick(tick)

    def on_bar(self, bar: BarData) -> None:
        """
        历史/实时 K 线更新回调（每个 Bar 结束时触发）
        """
        # 撤销所有尚未成交的限价委托，保证策略没有滞留委托
        self.cancel_all()

        # 更新指标管理器
        am: ArrayManager = self.am
        am.update_bar(bar)
        if not am.inited:
            return

        # 计算快速均线和上一期快速均线
        fast_ma: np.ndarray = am.sma(self.fast_window, array=True)
        self.fast_ma0 = fast_ma[-1]
        self.fast_ma1 = fast_ma[-2]

        # 计算慢速均线和上一期慢速均线
        slow_ma: np.ndarray = am.sma(self.slow_window, array=True)
        self.slow_ma0 = slow_ma[-1]
        self.slow_ma1 = slow_ma[-2]

        # 判断金叉和死叉
        cross_over: bool = self.fast_ma0 > self.slow_ma0 and self.fast_ma1 < self.slow_ma1
        cross_below: bool = self.fast_ma0 < self.slow_ma0 and self.fast_ma1 > self.slow_ma1

        if cross_over:
            # 金叉：如果没有持仓，买入开多（买入固定手数）
            if self.pos == 0:
                self.write_log(f"触发金叉！买入开多：价格 {bar.close_price}，数量 {self.fixed_size}")
                self.buy(bar.close_price, self.fixed_size)

        elif cross_below:
            # 死叉：如果有持仓，卖出平多（卖出清空所持多头仓位）
            if self.pos > 0:
                self.write_log(f"触发死叉！卖出平多：价格 {bar.close_price}，数量 {self.pos}")
                self.sell(bar.close_price, self.pos)

        # 把策略状态变量同步推送到 GUI 界面上显示
        self.put_event()

    def on_order(self, order: OrderData) -> None:
        """
        委托单状态更新回调
        """
        pass

    def on_trade(self, trade: TradeData) -> None:
        """
        成交细节更新回调
        """
        self.put_event()

    def on_stop_order(self, stop_order: StopOrder) -> None:
        """
        本地止损单更新回调
        """
        pass
