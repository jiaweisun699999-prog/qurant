# ── NumPy 2.0 兼容性补丁 (修复 empyrical 库调用 np.NINF 崩溃问题) ───
import numpy as np
if not hasattr(np, "NINF"):
    np.NINF = -np.inf

from vnpy.event import EventEngine
from vnpy.trader.engine import MainEngine
from vnpy.trader.ui import MainWindow, create_qapp

# ── 期货接口 ─────────────────────────────────────────────────────────
from vnpy_ctp import CtpGateway              # 上期所CTP（商品期货/金融期货）
# from vnpy_ctptest import CtptestGateway    # CTP 仿真测试接口
# from vnpy_mini import MiniGateway          # 飞马/小CTP（郑商所）
# from vnpy_sopt import SoptGateway          # 上期所期权
# from vnpy_rohon import RohonGateway        # 融航期货
# from vnpy_tts import TtsGateway            # TTS 仿真

# ── A股/股票接口 ──────────────────────────────────────────────────────
from vnpy_xtp import XtpGateway              # 中泰证券 XTP（A股现货、期权）
# from vnpy_tora import ToraStockGateway     # 华鑫 TORA 股票
# from vnpy_tora import ToraOptionGateway    # 华鑫 TORA 期权

# ── 策略/应用模块 ──────────────────────────────────────────────────────
from vnpy_ctastrategy import CtaStrategyApp        # CTA 策略
from vnpy_ctabacktester import CtaBacktesterApp    # CTA 回测
# from vnpy_spreadtrading import SpreadTradingApp   # 价差套利
from vnpy_algotrading import AlgoTradingApp       # 算法交易
# from vnpy_portfoliostrategy import PortfolioStrategyApp  # 组合策略
from vnpy_datamanager import DataManagerApp       # 数据管理
from vnpy_datarecorder import DataRecorderApp     # 行情录制
from vnpy_riskmanager import RiskManagerApp       # 风险管理
# from vnpy_scripttrader import ScriptTraderApp     # 脚本交易
from vnpy_chartwizard import ChartWizardApp       # K线图表
# from vnpy_paperaccount import PaperAccountApp     # 模拟交易账户


def main():
    """
    启动 VeighNa Trader 量化交易终端
    同时加载：期货(CTP) + A股/股票(中泰XTP) 双接口
    """
    qapp = create_qapp()

    event_engine = EventEngine()
    main_engine = MainEngine(event_engine)

    # ── 注册交易接口（可同时登录多个接口）─────────────────────────────
    main_engine.add_gateway(CtpGateway)       # 期货：上期 CTP
    main_engine.add_gateway(XtpGateway)       # 股票：中泰 XTP

    # main_engine.add_gateway(CtptestGateway)
    # main_engine.add_gateway(MiniGateway)
    # main_engine.add_gateway(SoptGateway)
    # main_engine.add_gateway(ToraStockGateway)
    # main_engine.add_gateway(ToraOptionGateway)

    # ── 注册应用模块 ───────────────────────────────────────────────────
    main_engine.add_app(CtaStrategyApp)
    main_engine.add_app(CtaBacktesterApp)
    
    # 注册批量回测模块（支持多股增量同步与一键双击细节复盘）
    from vnpy_batchbacktester import BatchBacktesterApp
    main_engine.add_app(BatchBacktesterApp)
    
    # main_engine.add_app(SpreadTradingApp)
    main_engine.add_app(AlgoTradingApp)
    # main_engine.add_app(PortfolioStrategyApp)
    main_engine.add_app(DataManagerApp)
    main_engine.add_app(DataRecorderApp)
    main_engine.add_app(RiskManagerApp)
    # main_engine.add_app(ScriptTraderApp)
    main_engine.add_app(ChartWizardApp)
    # main_engine.add_app(PaperAccountApp)

    main_window = MainWindow(main_engine, event_engine)
    main_window.showMaximized()

    qapp.exec()


if __name__ == "__main__":
    main()