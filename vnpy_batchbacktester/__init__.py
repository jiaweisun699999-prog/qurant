from vnpy.trader.app import BaseApp
from vnpy.trader.engine import BaseEngine, MainEngine
from PySide6 import QtCore
from .ui import BatchBacktestApp

class BatchBacktestEngine(BaseEngine):
    """
    极简影子引擎：继承自 BaseEngine
    完美避开局部 VN.py add_app 对 engine_class 不判空的底层 bug！
    """
    def __init__(self, main_engine: MainEngine, event_engine: QtCore.Signal):
        super().__init__(main_engine, event_engine, "BatchBacktester")


class BatchBacktesterApp(BaseApp):
    """
    官方格式的 批量回测 功能应用包定义 (已关联极简影子引擎)
    """
    app_name = "BatchBacktester"
    app_module = "vnpy_batchbacktester"
    app_path = __file__
    display_name = "批量回测"
    engine_class = BatchBacktestEngine
    widget_name = "BatchBacktestApp"   # 🚨 核心反射字符串，解决 getattr 反射加载报错！
    widget_class = BatchBacktestApp
    icon_name = "backtest.ico"
