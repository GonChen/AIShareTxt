from abc import ABC, abstractmethod
from typing import Optional
from datetime import date
import pandas as pd


class BaseDataSource(ABC):
    """数据源抽象基类"""

    @abstractmethod
    def fetch_stock_data(self, stock_code: str, period: str, start_date: str, adjust: str) -> Optional[pd.DataFrame]:
        """
        获取股票日线数据

        Returns:
            原始 DataFrame，列名由各数据源自行映射到标准格式后返回，
            由调度器统一调用 _process_stock_data 做清洗
        """
        ...

    @abstractmethod
    def get_fund_flow_data(self, stock_code: str, target_date: Optional[date] = None) -> dict:
        """获取资金流数据"""
        ...

    @abstractmethod
    def get_stock_basic_info(self, stock_code: str) -> dict:
        """获取股票基本信息"""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """数据源名称"""
        ...
