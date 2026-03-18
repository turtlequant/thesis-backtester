"""
CrawlerProvider — 基于 AKShare 的免费数据提供者

实现 DataProvider 协议中单股获取的方法，用于 live-analyze 命令。
批量方法抛出 NotImplementedError（回测应使用 TushareProvider）。

字段映射:
  AKShare 东方财富接口使用英文大写字段名 (TOTAL_ASSETS)。
  本模块内部完成映射，对外暴露与 TushareProvider 一致的列名。
"""
import time
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# AKShare 接口调用间隔（秒），避免被封
_CRAWL_SLEEP = 0.5


def _ts_code_to_symbol(ts_code: str) -> str:
    """601288.SH → SH601288 (东方财富格式)"""
    code, market = ts_code.split('.')
    return f"{market}{code}"


def _ts_code_to_code(ts_code: str) -> str:
    """601288.SH → 601288"""
    return ts_code.split('.')[0]


def _format_date(val) -> Optional[str]:
    """将各种日期格式统一为 YYYY-MM-DD"""
    if pd.isna(val):
        return None
    try:
        return pd.to_datetime(val).strftime('%Y-%m-%d')
    except Exception:
        return None


def _format_date_col(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """格式化某一列为 YYYY-MM-DD"""
    if col in df.columns:
        df[col] = df[col].apply(_format_date)
    return df


# ==================== 财报字段映射 ====================
# 东方财富英文大写 → Tushare 风格小写
# 只映射 Snapshot 和算子实际使用的字段，其余保留原名

_BALANCE_SHEET_MAP = {
    'SECUCODE': 'ts_code',
    'REPORT_DATE': 'end_date',
    'NOTICE_DATE': 'ann_date',
    'TOTAL_ASSETS': 'total_assets',
    'TOTAL_LIAB': 'total_liab',
    'TOTAL_EQUITY': 'total_hldr_eqy_exc_min_int',
    'ACCOUNTS_RECE': 'accounts_receiv',
    'INVENTORY': 'inventories',
    'MONETARYFUNDS': 'money_cap',
    'FIXED_ASSET': 'fix_assets',
    'INTANGIBLE_ASSET': 'intan_assets',
    'GOODWILL': 'goodwill',
    'SHORT_LOAN': 'st_borr',
    'LONG_LOAN': 'lt_borr',
    'BOND_PAYABLE': 'bond_payable',
    'TOTAL_CURRENT_ASSETS': 'total_cur_assets',
    'TOTAL_NONCURRENT_ASSETS': 'total_nca',
    'TOTAL_CURRENT_LIAB': 'total_cur_liab',
    'TOTAL_NONCURRENT_LIAB': 'total_ncl',
    'ADVANCE_RECEIVABLES': 'adv_receipts',
    'ACCOUNTS_PAYABLE': 'acct_payable',
    'MINORITY_EQUITY': 'minority_int',
}

_INCOME_MAP = {
    'SECUCODE': 'ts_code',
    'REPORT_DATE': 'end_date',
    'NOTICE_DATE': 'ann_date',
    'OPERATE_INCOME': 'revenue',
    'OPERATE_COST': 'oper_cost',
    'OPERATE_PROFIT': 'operate_profit',
    'TOTAL_PROFIT': 'total_profit',
    'NETPROFIT': 'n_income',
    'PARENT_NETPROFIT': 'n_income_attr_p',
    'INCOME_TAX': 'income_tax',
    'SALE_EXPENSE': 'sell_exp',
    'MANAGE_EXPENSE': 'admin_exp',
    'FINANCE_EXPENSE': 'fin_exp',
    'RESEARCH_EXPENSE': 'rd_exp',
    'INTEREST_NI': 'interest_ni',
    'INTEREST_INCOME': 'interest_income',
    'INTEREST_EXPENSE': 'interest_expense',
}

_CASHFLOW_MAP = {
    'SECUCODE': 'ts_code',
    'REPORT_DATE': 'end_date',
    'NOTICE_DATE': 'ann_date',
    'NETCASH_OPERATE': 'n_cashflow_act',
    'NETCASH_INVEST': 'n_cashflow_inv_act',
    'NETCASH_FINANCE': 'n_cash_flows_fnc_act',
    'CCE_ADD': 'n_incr_cash_cash_equ',
    'BEGIN_CCE': 'c_cash_equ_beg_period',
    'END_CCE': 'c_cash_equ_end_period',
    'TOTAL_OPERATE_INFLOW': 'c_fr_sale_sg',
    'TOTAL_OPERATE_OUTFLOW': 'total_oper_outflow',
    'BUY_SERVICES_RECEIVED': 'c_paid_goods_s',
    'INVEST_INCOME_RECEIVED': 'c_recp_return_invest',
    'FIXED_ASSET_DISPOSAL': 'c_disp_withdrdings_am',
    'CONSTRUCT_LONG_ASSET': 'c_pay_acq_const_fiam',
}

_FINA_INDICATOR_MAP = {
    '日期': 'end_date',
    '摊薄每股收益(元)': 'eps',
    '每股净资产_调整前(元)': 'bps',
    '每股经营性现金流(元)': 'cfps',
    '净资产收益率(%)': 'roe',
    '总资产利润率(%)': 'roa',
    '销售毛利率(%)': 'grossprofit_margin',
    '销售净利率(%)': 'netprofit_margin',
    '资产负债率(%)': 'debt_to_assets',
    '流动比率': 'current_ratio',
    '速动比率': 'quick_ratio',
}

_DIVIDEND_MAP = {
    '公告日期': 'ann_date',
    '派息': 'cash_div_tax',
    '送股': 'stk_div',
    '转增': 'stk_bo_rate',
    '除权除息日': 'ex_date',
    '股权登记日': 'record_date',
    '进度': 'div_proc',
}

_TOP10_HOLDERS_MAP = {
    '股东名称': 'holder_name',
    '持股数量': 'hold_amount',
    '持股比例': 'hold_ratio',
    '股本性质': 'hold_type',
    '截至日期': 'end_date',
    '公告日期': 'ann_date',
}


class CrawlerProvider:
    """基于 AKShare 的免费数据提供者"""

    def __init__(self):
        try:
            import akshare
            self._ak = akshare
        except ImportError:
            raise ImportError("CrawlerProvider 需要 akshare，请安装: pip install akshare")

    @property
    def name(self) -> str:
        return "crawler"

    # ==================== 日线行情 ====================

    def fetch_daily_single(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取单只股票日线行情（多源回退）"""
        # 数据源优先级: 东方财富 → 新浪 → 腾讯
        sources = [
            ('eastmoney', self._fetch_daily_eastmoney),
            ('sina', self._fetch_daily_sina),
            ('tencent', self._fetch_daily_tencent),
        ]
        for name, fetch_fn in sources:
            try:
                df = fetch_fn(ts_code, start_date, end_date)
                if df is not None and not df.empty:
                    logger.info(f"日线行情 {ts_code}: 使用 {name} 源")
                    return df
            except Exception as e:
                logger.debug(f"日线行情 {ts_code} {name} 失败: {e}")
                continue

        logger.warning(f"日线行情 {ts_code}: 所有数据源均失败")
        return pd.DataFrame()

    def _fetch_daily_eastmoney(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """东方财富日线"""
        code = _ts_code_to_code(ts_code)
        time.sleep(_CRAWL_SLEEP)
        df = self._ak.stock_zh_a_hist(
            symbol=code, period='daily',
            start_date=start_date.replace('-', ''),
            end_date=end_date.replace('-', ''),
            adjust='',
        )
        if df is None or df.empty:
            return pd.DataFrame()
        return self._normalize_daily(df, ts_code, source='eastmoney')

    def _fetch_daily_sina(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """新浪财经日线"""
        code = _ts_code_to_code(ts_code)
        market = 'sh' if ts_code.endswith('.SH') else 'sz'
        time.sleep(_CRAWL_SLEEP)
        df = self._ak.stock_zh_a_daily(symbol=f"{market}{code}", start_date=start_date, end_date=end_date, adjust="")
        if df is None or df.empty:
            return pd.DataFrame()
        return self._normalize_daily(df, ts_code, source='sina')

    def _fetch_daily_tencent(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """腾讯日线（通过 AKShare）"""
        code = _ts_code_to_code(ts_code)
        time.sleep(_CRAWL_SLEEP)
        # stock_zh_a_hist_163 是网易源，也是一个备选
        df = self._ak.stock_zh_a_hist_163(symbol=code, start_date=start_date, end_date=end_date)
        if df is None or df.empty:
            return pd.DataFrame()
        return self._normalize_daily(df, ts_code, source='163')

    def _normalize_daily(self, df: pd.DataFrame, ts_code: str, source: str) -> pd.DataFrame:
        """统一不同数据源的日线列名"""
        # 各源的列名映射
        col_maps = {
            'eastmoney': {
                '日期': 'trade_date', '开盘': 'open', '收盘': 'close',
                '最高': 'high', '最低': 'low', '成交量': 'volume',
                '成交额': 'amount', '涨跌幅': 'pct_chg', '换手率': 'turnover_rate',
            },
            'sina': {
                'date': 'trade_date', 'open': 'open', 'close': 'close',
                'high': 'high', 'low': 'low', 'volume': 'volume',
            },
            '163': {
                '日期': 'trade_date', '开盘价': 'open', '收盘价': 'close',
                '最高价': 'high', '最低价': 'low', '成交量': 'volume',
                '成交金额': 'amount', '涨跌幅': 'pct_chg', '换手率': 'turnover_rate',
            },
        }
        mapping = col_maps.get(source, {})
        df = df.rename(columns=mapping)
        df['ts_code'] = ts_code

        # 统一日期格式
        if 'trade_date' in df.columns:
            df['trade_date'] = pd.to_datetime(df['trade_date']).dt.strftime('%Y-%m-%d')

        # 确保必要列存在
        for col in ['open', 'close', 'high', 'low', 'volume']:
            if col not in df.columns:
                df[col] = None

        return df

    # ==================== 财报数据 ====================

    def fetch_balancesheet(self, ts_code: str) -> pd.DataFrame:
        symbol = _ts_code_to_symbol(ts_code)
        time.sleep(_CRAWL_SLEEP)
        try:
            df = self._ak.stock_balance_sheet_by_report_em(symbol=symbol)
        except Exception as e:
            logger.warning(f"获取资产负债表失败 {ts_code}: {e}")
            return pd.DataFrame()

        if df is None or df.empty:
            return pd.DataFrame()

        df = df.rename(columns=_BALANCE_SHEET_MAP)
        df['ts_code'] = ts_code
        df = _format_date_col(df, 'end_date')
        df = _format_date_col(df, 'ann_date')
        return df

    def fetch_income(self, ts_code: str) -> pd.DataFrame:
        symbol = _ts_code_to_symbol(ts_code)
        time.sleep(_CRAWL_SLEEP)
        try:
            df = self._ak.stock_profit_sheet_by_report_em(symbol=symbol)
        except Exception as e:
            logger.warning(f"获取利润表失败 {ts_code}: {e}")
            return pd.DataFrame()

        if df is None or df.empty:
            return pd.DataFrame()

        df = df.rename(columns=_INCOME_MAP)
        df['ts_code'] = ts_code
        df = _format_date_col(df, 'end_date')
        df = _format_date_col(df, 'ann_date')
        return df

    def fetch_cashflow(self, ts_code: str) -> pd.DataFrame:
        symbol = _ts_code_to_symbol(ts_code)
        time.sleep(_CRAWL_SLEEP)
        try:
            df = self._ak.stock_cash_flow_sheet_by_report_em(symbol=symbol)
        except Exception as e:
            logger.warning(f"获取现金流量表失败 {ts_code}: {e}")
            return pd.DataFrame()

        if df is None or df.empty:
            return pd.DataFrame()

        df = df.rename(columns=_CASHFLOW_MAP)
        df['ts_code'] = ts_code
        df = _format_date_col(df, 'end_date')
        df = _format_date_col(df, 'ann_date')
        return df

    def fetch_financial_indicator(self, ts_code: str) -> pd.DataFrame:
        code = _ts_code_to_code(ts_code)
        time.sleep(_CRAWL_SLEEP)
        try:
            df = self._ak.stock_financial_analysis_indicator(
                symbol=code, start_year='2018',
            )
        except Exception as e:
            logger.warning(f"获取财务指标失败 {ts_code}: {e}")
            return pd.DataFrame()

        if df is None or df.empty:
            return pd.DataFrame()

        df = df.rename(columns=_FINA_INDICATOR_MAP)
        df['ts_code'] = ts_code
        df['ann_date'] = df['end_date']  # 财务指标无独立公告日，用报告期近似
        df = _format_date_col(df, 'end_date')
        df = _format_date_col(df, 'ann_date')
        return df

    def fetch_dividend(self, ts_code: str) -> pd.DataFrame:
        code = _ts_code_to_code(ts_code)
        time.sleep(_CRAWL_SLEEP)
        try:
            df = self._ak.stock_history_dividend_detail(
                symbol=code, indicator='分红',
            )
        except Exception as e:
            logger.warning(f"获取分红数据失败 {ts_code}: {e}")
            return pd.DataFrame()

        if df is None or df.empty:
            return pd.DataFrame()

        df = df.rename(columns=_DIVIDEND_MAP)
        df['ts_code'] = ts_code
        df = _format_date_col(df, 'ann_date')
        df = _format_date_col(df, 'ex_date')
        df = _format_date_col(df, 'record_date')
        return df

    def fetch_top10_holders(self, ts_code: str) -> pd.DataFrame:
        code = _ts_code_to_code(ts_code)
        time.sleep(_CRAWL_SLEEP)
        try:
            df = self._ak.stock_main_stock_holder(stock=code)
        except Exception as e:
            logger.warning(f"获取十大股东失败 {ts_code}: {e}")
            return pd.DataFrame()

        if df is None or df.empty:
            return pd.DataFrame()

        df = df.rename(columns=_TOP10_HOLDERS_MAP)
        df['ts_code'] = ts_code
        df = _format_date_col(df, 'end_date')
        df = _format_date_col(df, 'ann_date')
        return df

    def fetch_individual_info(self, ts_code: str) -> pd.DataFrame:
        """获取个股基本信息（行业、市值等）"""
        code = _ts_code_to_code(ts_code)
        time.sleep(_CRAWL_SLEEP)
        try:
            df = self._ak.stock_individual_info_em(symbol=code)
        except Exception as e:
            logger.warning(f"获取个股信息失败 {ts_code}: {e}")
            return pd.DataFrame()
        return df

    # ==================== 实时增强数据（回测没有的）====================

    def fetch_news(self, ts_code: str, limit: int = 20) -> pd.DataFrame:
        """个股最新新闻（东方财富）"""
        code = _ts_code_to_code(ts_code)
        time.sleep(_CRAWL_SLEEP)
        try:
            df = self._ak.stock_news_em(symbol=code)
            if df is None or df.empty:
                return pd.DataFrame()
            df = df.rename(columns={
                '新闻标题': 'title',
                '新闻内容': 'content',
                '发布时间': 'datetime',
                '文章来源': 'source',
                '新闻链接': 'url',
            })
            return df.head(limit)
        except Exception as e:
            logger.debug(f"获取新闻失败 {ts_code}: {e}")
            return pd.DataFrame()

    def fetch_fund_flow(self, ts_code: str, days: int = 30) -> pd.DataFrame:
        """主力资金流向（近 N 日）"""
        code = _ts_code_to_code(ts_code)
        market = 'sh' if ts_code.endswith('.SH') else 'sz'
        time.sleep(_CRAWL_SLEEP)
        try:
            df = self._ak.stock_individual_fund_flow(stock=code, market=market)
            if df is None or df.empty:
                return pd.DataFrame()
            df = df.rename(columns={
                '日期': 'trade_date',
                '收盘价': 'close',
                '涨跌幅': 'pct_chg',
                '主力净流入-净额': 'main_net_inflow',
                '主力净流入-净占比': 'main_net_inflow_pct',
                '超大单净流入-净额': 'xl_net_inflow',
                '大单净流入-净额': 'lg_net_inflow',
                '中单净流入-净额': 'md_net_inflow',
                '小单净流入-净额': 'sm_net_inflow',
            })
            df['trade_date'] = pd.to_datetime(df['trade_date']).dt.strftime('%Y-%m-%d')
            return df.tail(days)
        except Exception as e:
            logger.debug(f"获取资金流失败 {ts_code}: {e}")
            return pd.DataFrame()

    def fetch_index_daily(self, index_code: str = 'sh000300', days: int = 60) -> pd.DataFrame:
        """大盘指数日线（新浪源，默认沪深300）"""
        time.sleep(_CRAWL_SLEEP)
        try:
            df = self._ak.stock_zh_index_daily(symbol=index_code)
            if df is None or df.empty:
                return pd.DataFrame()
            df = df.rename(columns={'date': 'trade_date'})
            df['trade_date'] = pd.to_datetime(df['trade_date']).dt.strftime('%Y-%m-%d')
            return df.tail(days)
        except Exception as e:
            logger.debug(f"获取指数行情失败 {index_code}: {e}")
            return pd.DataFrame()

    def fetch_industry_summary(self) -> pd.DataFrame:
        """行业板块汇总（同花顺，含涨跌幅/资金流向）"""
        time.sleep(_CRAWL_SLEEP)
        try:
            df = self._ak.stock_board_industry_summary_ths()
            if df is None or df.empty:
                return pd.DataFrame()
            df = df.rename(columns={
                '板块': 'industry',
                '涨跌幅': 'pct_chg',
                '总成交额': 'amount',
                '净流入': 'net_inflow',
                '上涨家数': 'up_count',
                '下跌家数': 'down_count',
            })
            return df
        except Exception as e:
            logger.debug(f"获取行业汇总失败: {e}")
            return pd.DataFrame()

    def fetch_financial_summary_ths(self, ts_code: str) -> pd.DataFrame:
        """同花顺财务摘要（ROE/净利润增长率等，适合行业横向对比）"""
        code = _ts_code_to_code(ts_code)
        time.sleep(_CRAWL_SLEEP)
        try:
            df = self._ak.stock_financial_abstract_ths(symbol=code, indicator='按报告期')
            if df is None or df.empty:
                return pd.DataFrame()
            df = df.rename(columns={
                '报告期': 'end_date',
                '净利润': 'net_profit',
                '净利润同比增长率': 'net_profit_yoy',
                '营业总收入': 'revenue',
                '营业总收入同比增长率': 'revenue_yoy',
                '基本每股收益': 'eps',
                '每股净资产': 'bps',
                '每股经营现金流': 'cfps',
                '净资产收益率': 'roe',
                '资产负债率': 'debt_ratio',
            })
            df = _format_date_col(df, 'end_date')
            df['ts_code'] = ts_code
            return df
        except Exception as e:
            logger.debug(f"获取同花顺财务摘要失败 {ts_code}: {e}")
            return pd.DataFrame()

    # ==================== 降级处理：返回空 DataFrame ====================

    def fetch_top10_floatholders(self, ts_code: str) -> pd.DataFrame:
        """十大流通股东 — 暂无接口，降级"""
        logger.debug(f"CrawlerProvider: 十大流通股东暂不支持 ({ts_code})")
        return pd.DataFrame()

    def fetch_fina_audit(self, ts_code: str) -> pd.DataFrame:
        """审计意见 — 暂无接口，降级"""
        logger.debug(f"CrawlerProvider: 审计意见暂不支持 ({ts_code})")
        return pd.DataFrame()

    def fetch_fina_mainbz(self, ts_code: str) -> pd.DataFrame:
        """主营构成 — 暂无接口，降级"""
        logger.debug(f"CrawlerProvider: 主营构成暂不支持 ({ts_code})")
        return pd.DataFrame()

    def fetch_stk_holdernumber(self, ts_code: str) -> pd.DataFrame:
        """股东人数 — 暂无接口，降级"""
        logger.debug(f"CrawlerProvider: 股东人数暂不支持 ({ts_code})")
        return pd.DataFrame()

    def fetch_stk_holdertrade(self, ts_code: str) -> pd.DataFrame:
        """股东增减持 — 暂无接口，降级"""
        logger.debug(f"CrawlerProvider: 股东增减持暂不支持 ({ts_code})")
        return pd.DataFrame()

    def fetch_pledge_stat(self, ts_code: str) -> pd.DataFrame:
        """股权质押 — 暂无接口，降级"""
        logger.debug(f"CrawlerProvider: 股权质押暂不支持 ({ts_code})")
        return pd.DataFrame()

    def fetch_pledge_detail(self, ts_code: str) -> pd.DataFrame:
        """股权质押明细 — 暂无接口，降级"""
        return pd.DataFrame()

    def fetch_share_float(self, ts_code: str) -> pd.DataFrame:
        """限售解禁 — 暂无接口，降级"""
        return pd.DataFrame()

    def fetch_repurchase(self, ts_code: str) -> pd.DataFrame:
        """回购 — 暂无接口，降级"""
        return pd.DataFrame()

    def fetch_disclosure_date(self, end_date: Optional[str] = None) -> pd.DataFrame:
        """财报披露日期 — 暂无接口，降级"""
        return pd.DataFrame()

    # ==================== 批量方法：不支持 ====================

    def fetch_stock_list(self) -> pd.DataFrame:
        raise NotImplementedError("CrawlerProvider 不支持批量操作，请使用 TushareProvider")

    def fetch_trade_calendar(self, start_date: str, end_date: str) -> pd.DataFrame:
        raise NotImplementedError("CrawlerProvider 不支持批量操作，请使用 TushareProvider")

    def fetch_daily_bulk(self, trade_date: str) -> pd.DataFrame:
        raise NotImplementedError("CrawlerProvider 不支持批量操作，请使用 TushareProvider")

    def fetch_adj_factor_bulk(self, trade_date: str) -> pd.DataFrame:
        raise NotImplementedError("CrawlerProvider 不支持批量操作，请使用 TushareProvider")

    def fetch_daily_indicator_bulk(self, trade_date: str) -> pd.DataFrame:
        raise NotImplementedError("CrawlerProvider 不支持批量操作，请使用 TushareProvider")

    def fetch_income_by_period(self, period: str) -> pd.DataFrame:
        raise NotImplementedError("CrawlerProvider 不支持批量操作，请使用 TushareProvider")

    def fetch_balancesheet_by_period(self, period: str) -> pd.DataFrame:
        raise NotImplementedError("CrawlerProvider 不支持批量操作，请使用 TushareProvider")

    def fetch_cashflow_by_period(self, period: str) -> pd.DataFrame:
        raise NotImplementedError("CrawlerProvider 不支持批量操作，请使用 TushareProvider")

    def fetch_fina_indicator_by_period(self, period: str) -> pd.DataFrame:
        raise NotImplementedError("CrawlerProvider 不支持批量操作，请使用 TushareProvider")
