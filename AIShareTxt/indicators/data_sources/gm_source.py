from typing import Optional
from datetime import datetime, timedelta, date
import pandas as pd
import numpy as np
from .base import BaseDataSource
from ...utils.utils import LoggerManager


class GmDataSource(BaseDataSource):
    """基于掘金量化(gm) SDK 的数据源"""

    # gm 列名 → 项目标准列名
    COLUMN_MAP = {
        'eob': 'date',
        'open': 'open',
        'high': 'high',
        'low': 'low',
        'close': 'close',
        'volume': 'volume',
        'amount': 'turnover',
        'turn_rate': 'turnover_rate',
    }

    # gm 资金流字段 → 项目标准字段
    FUND_FLOW_MAP = {
        'main_net_in': '主力净流入额',
        'main_net_in_rate': '主力净流入占比',
        'super_net_in': '超大单净流入额',
        'super_net_in_rate': '超大单净流入占比',
        'large_net_in': '大单净流入额',
        'large_net_in_rate': '大单净流入占比',
        'mid_net_in': '中单净流入额',
        'mid_net_in_rate': '中单净流入占比',
        'small_net_in': '小单净流入额',
        'small_net_in_rate': '小单净流入占比',
    }

    def __init__(self, config: dict):
        self._config = config
        self._token = config.get('gm', {}).get('token', '')
        self.logger = LoggerManager.get_logger('data_fetcher')
        self._connected = False
        self._connect()

    @property
    def name(self) -> str:
        return 'gm'

    def _connect(self):
        """初始化 gm 连接"""
        if not self._token:
            raise ValueError("GM_TOKEN 未配置，无法使用 gm 数据源")
        from gm.api import set_token
        set_token(self._token)
        self._connected = True
        self.logger.info("gm 数据源连接成功")

    @staticmethod
    def _to_gm_symbol(stock_code: str) -> str:
        """000001 → SZSE.000001, 600000 → SHSE.600000"""
        code = stock_code.strip().zfill(6)
        if code[0] in ('6', '7'):
            return f'SHSE.{code}'
        else:
            return f'SZSE.{code}'

    # ==================== 日线数据 ====================

    def fetch_stock_data(self, stock_code: str, period: str, start_date: str, adjust: str) -> Optional[pd.DataFrame]:
        """获取日线数据，收盘后自动用 current() 补全当天数据"""
        try:
            from gm.api import history

            gm_symbol = self._to_gm_symbol(stock_code)
            self.logger.info(f"[gm] 获取股票 {gm_symbol} 的数据（从 {start_date} 开始）...")

            fields = 'eob,open,high,low,close,volume,amount'
            today_str = datetime.now().strftime('%Y-%m-%d')
            # 兼容 YYYYMMDD 和 YYYY-MM-DD 两种格式
            if '-' not in start_date:
                start_date = f'{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}'
            start_time = f'{start_date} 09:30:00'
            end_time = f'{today_str} 23:59:59'

            raw_data = history(
                symbol=gm_symbol,
                start_time=start_time,
                end_time=end_time,
                frequency='1d',
                fields=fields,
                df=True
            )

            if raw_data is None:
                raw_data = pd.DataFrame()

            # 补充换手率数据（history() 不提供，用 get_history_symbol 补取）
            raw_data = self._enrich_turnover_rate(raw_data, gm_symbol, start_date, today_str)

            # 检查是否需要补全当天数据
            now = datetime.now()
            today = now.date()
            if now.hour >= 15 and not raw_data.empty and 'eob' in raw_data.columns:
                last_eob = pd.Timestamp(raw_data['eob'].iloc[-1]).date()
                if last_eob < today:
                    today_data = self._get_today_data(gm_symbol, fields)
                    if today_data is not None and not today_data.empty:
                        raw_data = pd.concat([raw_data, today_data], ignore_index=True)
                        self.logger.info("[gm] 已用 current() 补全当天数据")

            if raw_data.empty:
                self.logger.warning(f"[gm] 未获取到 {stock_code} 的数据")
                return None

            # 映射列名
            raw_data = raw_data.rename(columns=self.COLUMN_MAP)

            # 按日期去重：同一交易日保留 turnover 更完整的行
            raw_data = self._deduplicate_by_date(raw_data)

            self.logger.info(f"[gm] 获取到 {len(raw_data)} 条数据")
            return raw_data

        except Exception as e:
            self.logger.warning(f"[gm] 获取数据失败：{str(e)}")
            return None

    def _get_today_data(self, gm_symbol: str, fields: str) -> Optional[pd.DataFrame]:
        """用 current() 获取当天快照并转换为 history() 格式"""
        try:
            from gm.api import current as gm_current

            current_data = gm_current(symbols=[gm_symbol], include_call_auction=False)
            if not current_data:
                return None

            item = current_data[0]
            requested_fields = [f.strip() for f in fields.split(',')]
            row = {'eob': item.get('created_at', datetime.now())}

            for field in requested_fields:
                if field in ('eob',):
                    continue
                elif field == 'close':
                    row[field] = item.get('price', 0)
                elif field == 'volume':
                    row[field] = item.get('cum_volume', 0)
                elif field == 'amount':
                    row[field] = item.get('cum_amount', 0)
                else:
                    row[field] = item.get(field, 0)

            return pd.DataFrame([row])

        except Exception as e:
            self.logger.debug(f"[gm] current() 获取当天数据失败：{str(e)}")
            return None

    def _deduplicate_by_date(self, data: pd.DataFrame) -> pd.DataFrame:
        """按日期去重，同一交易日优先保留字段更完整的行，然后回填缺失值"""
        if data.empty or 'date' not in data.columns:
            return data

        data['_date_key'] = data['date'].apply(
            lambda x: pd.Timestamp(x).date() if pd.notna(x) else None
        )

        dup_mask = data.duplicated(subset=['_date_key'], keep=False)
        if not dup_mask.any():
            data.drop(columns=['_date_key'], inplace=True)
            return data

        # 计算每行非NaN字段数作为完整度评分
        check_cols = [c for c in ['turnover', 'turnover_rate'] if c in data.columns]
        if check_cols:
            data['_score'] = data[check_cols].notna().sum(axis=1)
            result = data.sort_values('_score', na_position='first')
            result = result.drop_duplicates(subset=['_date_key'], keep='last')
            result = result.drop(columns=['_score'])
        else:
            result = data.drop_duplicates(subset=['_date_key'], keep='last')

        # 用同日期其他行的有效值回填仍为NaN的字段
        result = result.sort_values('date').reset_index(drop=True)
        for col in check_cols:
            if result[col].isna().any():
                fill_map = data.dropna(subset=[col]).groupby('_date_key')[col].first()
                mask = result[col].isna()
                result.loc[mask, col] = result.loc[mask, '_date_key'].map(fill_map)

        result = result.drop(columns=['_date_key'], errors='ignore')

        removed = len(data) - len(result)
        if removed > 0:
            self.logger.info(f"[gm] 去重：移除了 {removed} 条重复日期数据")

        return result

    def _enrich_turnover_rate(self, data: pd.DataFrame, gm_symbol: str,
                              start_date: str, end_date: str) -> pd.DataFrame:
        """用 get_history_symbol() 补取换手率数据并合并"""
        if data.empty:
            return data

        try:
            from gm.api import get_history_symbol

            hist = get_history_symbol(
                symbol=gm_symbol,
                start_date=start_date,
                end_date=end_date,
                df=True
            )

            if hist is None or hist.empty or 'trade_date' not in hist.columns:
                self.logger.debug("[gm] get_history_symbol 未返回有效数据")
                return data

            # 构建日期→换手率映射
            hist['trade_date'] = pd.to_datetime(hist['trade_date'])
            turn_rate_map = dict(zip(
                hist['trade_date'].dt.date,
                hist['turn_rate']
            ))

            # 将换手率合并到主数据
            data['turn_rate'] = data['eob'].apply(
                lambda x: turn_rate_map.get(pd.Timestamp(x).date(), np.nan)
                if pd.notna(x) else np.nan
            )

            valid_count = data['turn_rate'].notna().sum()
            self.logger.info(f"[gm] 补取换手率数据：{valid_count}/{len(data)} 条有效")

        except Exception as e:
            self.logger.debug(f"[gm] 补取换手率数据失败：{str(e)}")

        return data

    # ==================== 资金流 ====================

    def get_fund_flow_data(self, stock_code: str, target_date=None) -> dict:
        """使用 gm stk_get_money_flow() 获取资金流数据，含5日累计"""
        try:
            from gm.api import stk_get_money_flow

            gm_symbol = self._to_gm_symbol(stock_code)
            self.logger.info(f"[gm] 获取 {gm_symbol} 资金流数据...")

            daily_rows = self._fetch_multi_day_fund_flow(
                stk_get_money_flow, gm_symbol, target_date, days=5
            )

            if not daily_rows:
                self.logger.warning(f"[gm] 未获取到 {stock_code} 的资金流数据")
                return {}

            row = daily_rows[0]
            result = {}
            for gm_field, std_field in self.FUND_FLOW_MAP.items():
                result[std_field] = row.get(gm_field, 0)

            date_val = row.get('trade_date', '')
            result['日期'] = str(date_val)[:10] if date_val else ''

            if len(daily_rows) >= 5:
                recent = pd.DataFrame(daily_rows)
                result['5日主力净流入额'] = recent['main_net_in'].sum()
                result['5日超大单净流入额'] = recent['super_net_in'].sum()
                result['5日大单净流入额'] = recent['large_net_in'].sum()
                result['5日中单净流入额'] = recent['mid_net_in'].sum()
                result['5日小单净流入额'] = recent['small_net_in'].sum()
                result['5日主力净流入占比'] = recent['main_net_in_rate'].mean()
                result['5日超大单净流入占比'] = recent['super_net_in_rate'].mean()
                result['5日大单净流入占比'] = recent['large_net_in_rate'].mean()
                result['5日中单净流入占比'] = recent['mid_net_in_rate'].mean()
                result['5日小单净流入占比'] = recent['small_net_in_rate'].mean()

            self.logger.info(f"[gm] 资金流数据获取成功（{len(daily_rows)}天）")
            return result

        except Exception as e:
            self.logger.warning(f"[gm] 获取资金流数据失败：{str(e)}")
            return {}

    def _fetch_multi_day_fund_flow(self, api_func, gm_symbol: str, target_date, days: int = 5) -> list:
        """逐天查询资金流数据，跳过非交易日"""
        rows = []
        check_date = target_date if target_date else datetime.now().date()
        if hasattr(check_date, 'date') and not isinstance(check_date, date):
            check_date = check_date.date()

        for _ in range(days * 3):
            if len(rows) >= days:
                break
            date_str = check_date.strftime('%Y-%m-%d')
            try:
                raw = api_func(symbols=gm_symbol, trade_date=date_str)
                if raw is not None and not raw.empty:
                    rows.append(raw.iloc[0].to_dict())
            except Exception:
                pass
            check_date = check_date - timedelta(days=1)

        return rows

    # ==================== 基本信息 ====================

    def get_stock_basic_info(self, stock_code: str) -> dict:
        """使用 gm 多个 API 组合获取完整基本信息"""
        gm_symbol = self._to_gm_symbol(stock_code)
        self.logger.info(f"[gm] 获取 {gm_symbol} 基本信息...")

        stock_info = {
            '股票代码': stock_code,
            '股票简称': '未知',
            '行业': '未知',
            '流通市值': 0,
            '总市值': 0,
            '总股本': 0,
            '流通股本': 0,
            '市盈率': '未知',
            '市净率': '未知',
        }

        # 1. 行业 + 名称
        try:
            from gm.api import stk_get_symbol_industry
            ind = stk_get_symbol_industry(symbols=gm_symbol, source='sw2021', level=1)
            if ind is not None and not ind.empty:
                row = ind.iloc[0]
                stock_info['股票简称'] = row.get('sec_name', stock_info['股票简称'])
                stock_info['行业'] = row.get('industry_name', '未知')
        except Exception as e:
            self.logger.debug(f"[gm] 获取行业信息失败：{str(e)}")

        # 2. 市值
        try:
            from gm.api import stk_get_daily_mktvalue
            mv = stk_get_daily_mktvalue(symbol=gm_symbol, fields='tot_mv,a_mv_ex_ltd', df=True)
            if mv is not None and not mv.empty:
                row = mv.iloc[-1]
                stock_info['总市值'] = row.get('tot_mv', 0)
                stock_info['流通市值'] = row.get('a_mv_ex_ltd', 0)
        except Exception as e:
            self.logger.debug(f"[gm] 获取市值失败：{str(e)}")

        # 3. 股本
        try:
            from gm.api import stk_get_daily_basic
            bs = stk_get_daily_basic(symbol=gm_symbol, fields='ttl_shr,circ_shr', df=True)
            if bs is not None and not bs.empty:
                row = bs.iloc[-1]
                stock_info['总股本'] = row.get('ttl_shr', 0)
                stock_info['流通股本'] = row.get('circ_shr', 0)
        except Exception as e:
            self.logger.debug(f"[gm] 获取股本失败：{str(e)}")

        # 4. 估值（PE/PB）
        try:
            from gm.api import stk_get_daily_valuation_pt
            val = stk_get_daily_valuation_pt(symbols=gm_symbol, fields='pe_ttm,pb_mrq', df=True)
            if val is not None and not val.empty:
                row = val.iloc[-1]
                stock_info['市盈率'] = row.get('pe_ttm', '未知')
                stock_info['市净率'] = row.get('pb_mrq', '未知')
        except Exception as e:
            self.logger.debug(f"[gm] 获取估值失败：{str(e)}")

        # 格式化市值单位
        for field, unit_field in [
            ('流通市值', '流通市值_亿'),
            ('总市值', '总市值_亿'),
            ('流通股本', '流通股本_亿股'),
            ('总股本', '总股本_亿股')
        ]:
            val = stock_info.get(field, 0)
            if isinstance(val, (int, float)) and val > 0:
                stock_info[unit_field] = val / 100000000
            else:
                stock_info[unit_field] = 0

        self.logger.info(f"[gm] 基本信息获取成功: {stock_info.get('股票简称')}")
        return stock_info

    def _get_default_basic_info(self, stock_code):
        return {
            '股票代码': stock_code,
            '股票简称': "未知",
            '行业': "未知",
            '流通市值_亿': 0,
            '总市值_亿': 0,
            '流通股本_亿股': 0,
            '总股本_亿股': 0,
            '市盈率': "未知",
            '市净率': "未知"
        }
