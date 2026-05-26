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
    A股极致多因子分批建仓与持仓上限控制策略 (Stock Quant Multi-Factor Max-Pos Strategy)
    
    【交易规则】
    1. 连跌7天信号：若收盘价连续7天下跌，直接买入 10% 仓位。
    2. 历史百分之80之后信号（价格处于历史最低 20% 分位数）：买入 10% 仓位。
    3. 前3天最低价信号：若今天收盘价是前3天最低价，买入 5% 仓位。
    4. 仓位硬性控制：最大允许同时持有 5 个活跃子仓位（最多占用 50% 资金），一旦达到上限，强制锁定不再加仓，留存 50% 现金！
    5. 每个子仓位均独立计算，盈利达到 +3.5% 时果断止盈抛出，回流现金。
    """

    author = "Antigravity Quant"

    # 策略参数
    total_capital: float = 1000000.0   # 初始总资金 (100万)
    profit_target: float = 0.035       # 止盈点数 (3.5%)
    max_sub_positions: int = 5         # 最大允许同时持有的子仓位数量 (上限控制)
    fall_days: int = 7                 # 连续下跌天数门槛
    percentile_threshold: float = 20.0 # 历史价格分位数门槛 (低于该百分比，即排在历史80%之后)
    lowest_days: int = 3               # 最低价比较天数

    # 策略变量
    current_cash: float = 1000000.0    # 动态现金余额
    active_pos_count: int = 0          # 当前活跃的子仓位数量

    parameters = [
        "total_capital",
        "profit_target",
        "max_sub_positions",
        "fall_days",
        "percentile_threshold",
        "lowest_days"
    ]
    variables = [
        "current_cash",
        "active_pos_count"
    ]

    def on_init(self) -> None:
        """
        策略初始化回调
        """
        self.write_log("A股极致多因子策略初始化...")

        # 实例化指标管理器，容量设为 500 天以获取更长周期的历史价格对比
        self.bg: BarGenerator = BarGenerator(self.on_bar)
        self.am: ArrayManager = ArrayManager(size=500)

        # 维护一个独立的子仓位列表，格式为: [{"buy_price": xx, "volume": xx, "target_price": xx}]
        self.sub_positions: list[dict] = []
        self.current_cash = self.total_capital

        # 预热加载 500 天历史 K 线数据以供分位数计算
        self.load_bar(500)

    def on_start(self) -> None:
        """
        策略启动回调
        """
        self.write_log("A股极致多因子策略启动！")
        self.put_event()

    def on_stop(self) -> None:
        """
        策略停止回调
        """
        self.write_log("A股极致多因子策略停止。")
        self.put_event()

    def on_tick(self, tick: TickData) -> None:
        """
        实时 Tick 更新
        """
        self.bg.update_tick(tick)

    def on_bar(self, bar: BarData) -> None:
        """
        每日 K 线收盘更新
        """
        self.cancel_all()

        # 1. 独立仓位止盈检查 (Check Take Profit for each sub-position)
        # 遍历已持有的子仓位，检查今日是否达到了 +3.5% 的止盈价
        keep_positions = []
        for pos_item in self.sub_positions:
            buy_price = pos_item["buy_price"]
            volume = pos_item["volume"]
            target_price = pos_item["target_price"]

            # 如果今天最高价达到了止盈目标价，执行止盈抛出
            if bar.high_price >= target_price:
                self.write_log(f"【止盈触发】子仓位入场价 {buy_price:.2f} 已盈利3.5%，以目标价 {target_price:.2f} 抛出 {volume} 股")
                self.sell(target_price, volume)
                self.current_cash += volume * target_price
            else:
                keep_positions.append(pos_item)
        
        self.sub_positions = keep_positions
        self.active_pos_count = len(self.sub_positions)

        # 2. 更新指标管理器
        am: ArrayManager = self.am
        am.update_bar(bar)
        if not am.inited:
            return

        # 3. 提取历史收盘价数据用于条件判断
        close_array = am.close
        current_close = bar.close_price

        # ── 信号 1：连续下跌7天 ──
        is_falling_7 = True
        for i in range(-self.fall_days, 0):
            if close_array[i] >= close_array[i-1]:
                is_falling_7 = False
                break

        # ── 信号 2：股价处于历史分位数最低 20%（即排在80%之后） ──
        smaller_count = sum(1 for p in close_array if p < current_close)
        percentile = (smaller_count / len(close_array)) * 100.0
        is_bottom_percentile = percentile <= self.percentile_threshold

        # ── 信号 3：股价是前3天的最低价 ──
        is_lowest_3 = current_close < min(close_array[-4:-1])

        # 4. 执行买入建仓逻辑（必须在活跃仓位数小于上限时才触发）
        
        # 信号 1：连跌7天买入 10% 仓位
        if len(self.sub_positions) < self.max_sub_positions:
            if is_falling_7:
                buy_capital = self.total_capital * 0.10
                volume = int(buy_capital / current_close / 100) * 100
                
                if volume > 0 and self.current_cash >= (volume * current_close):
                    self.write_log(f"【买入信号】收盘价连续{self.fall_days}天下跌！触发10%建仓：价格 {current_close:.2f}，数量 {volume}")
                    self.buy(current_close, volume)
                    self.current_cash -= volume * current_close
                    self.sub_positions.append({
                        "buy_price": current_close,
                        "volume": volume,
                        "target_price": current_close * (1.0 + self.profit_target)
                    })

        # 信号 2：最低 20% 历史分位买入 10% 仓位
        if len(self.sub_positions) < self.max_sub_positions:
            if is_bottom_percentile:
                buy_capital = self.total_capital * 0.10
                volume = int(buy_capital / current_close / 100) * 100
                
                if volume > 0 and self.current_cash >= (volume * current_close):
                    self.write_log(f"【买入信号】股价进入历史最低{self.percentile_threshold}%分位(排在80%后)！触发10%建仓：价格 {current_close:.2f}，数量 {volume}")
                    self.buy(current_close, volume)
                    self.current_cash -= volume * current_close
                    self.sub_positions.append({
                        "buy_price": current_close,
                        "volume": volume,
                        "target_price": current_close * (1.0 + self.profit_target)
                    })

        # 信号 3：前3天最低价买入 5% 仓位
        if len(self.sub_positions) < self.max_sub_positions:
            if is_lowest_3:
                buy_capital = self.total_capital * 0.05
                volume = int(buy_capital / current_close / 100) * 100
                
                if volume > 0 and self.current_cash >= (volume * current_close):
                    self.write_log(f"【买入信号】股价创前{self.lowest_days}天新低！触发5%建仓：价格 {current_close:.2f}，数量 {volume}")
                    self.buy(current_close, volume)
                    self.current_cash -= volume * current_close
                    self.sub_positions.append({
                        "buy_price": current_close,
                        "volume": volume,
                        "target_price": current_close * (1.0 + self.profit_target)
                    })

        self.active_pos_count = len(self.sub_positions)
        self.put_event()

    def on_order(self, order: OrderData) -> None:
        """
        委托单状态更新
        """
        pass

    def on_trade(self, trade: TradeData) -> None:
        """
        成交细节更新
        """
        self.put_event()

    def on_stop_order(self, stop_order: StopOrder) -> None:
        """
        本地止损单更新
        """
        pass
