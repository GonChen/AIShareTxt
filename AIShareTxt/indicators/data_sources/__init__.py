from .base import BaseDataSource
from .akshare_source import AkshareDataSource

__all__ = ['BaseDataSource', 'AkshareDataSource']

def create_gm_source(config):
    """延迟加载 gm 数据源，避免未安装时 import 报错"""
    from .gm_source import GmDataSource
    return GmDataSource(config)
