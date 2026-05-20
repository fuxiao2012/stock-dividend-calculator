"""数据提供者抽象基类 — 港股/美股扩展点"""
from abc import ABC, abstractmethod
from typing import Optional
import pandas as pd


class DividendProvider(ABC):
    """分红数据提供者接口"""

    @abstractmethod
    def get_dividend_detail(self, stock_code: str) -> pd.DataFrame:
        """获取单只股票的完整分红明细"""

    @abstractmethod
    def get_dividend_summary(self) -> pd.DataFrame:
        """获取全市场分红汇总数据"""

    @abstractmethod
    def get_upcoming_dividends(self, date: Optional[str] = None) -> pd.DataFrame:
        """获取指定日期附近的分红预告"""

    @abstractmethod
    def get_stock_info(self, stock_code: str) -> dict:
        """获取股票基本信息 (名称, 上市日期, 行业等)"""

    @abstractmethod
    def get_all_stocks(self) -> pd.DataFrame:
        """获取全市场股票列表 (code, name)"""


def create_provider(market: str = "A") -> DividendProvider:
    """工厂函数：根据市场创建对应 Provider 实例"""
    if market == "A":
        from .akshare_provider import AkshareDividendProvider
        return AkshareDividendProvider()
    raise ValueError(f"不支持的市场: {market}")
