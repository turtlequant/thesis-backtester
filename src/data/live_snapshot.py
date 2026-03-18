"""
实时快照生成器 — 基于 CrawlerProvider

和 snapshot.py 的 create_snapshot 功能相同，但数据直接从 CrawlerProvider 获取，
不依赖本地 Parquet 存储和 Tushare API。

用于 live-analyze 命令。
"""
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pandas as pd

from .snapshot import StockSnapshot
from .crawler import CrawlerProvider

logger = logging.getLogger(__name__)


def create_live_snapshot(
    ts_code: str,
    provider: CrawlerProvider = None,
    price_lookback_days: int = 365 * 3,
) -> StockSnapshot:
    """
    从免费数据源实时生成数据快照

    Args:
        ts_code: 股票代码，如 '601288.SH'
        provider: CrawlerProvider 实例（默认自动创建）
        price_lookback_days: 行情回看天数

    Returns:
        StockSnapshot
    """
    if provider is None:
        provider = CrawlerProvider()

    cutoff_date = datetime.now().strftime('%Y-%m-%d')

    # 获取个股基本信息（带重试）
    stock_name, industry = ts_code, ''
    for attempt in range(3):
        try:
            info_df = provider.fetch_individual_info(ts_code)
            if not info_df.empty:
                info_dict = dict(zip(info_df['item'], info_df['value']))
                stock_name = info_dict.get('股票简称', ts_code)
                industry = info_dict.get('行业', '')
                break
        except Exception as e:
            if attempt < 2:
                import time
                time.sleep(1)
            else:
                logger.warning(f"获取个股信息失败（已重试3次）: {e}")

    snapshot = StockSnapshot(
        ts_code=ts_code,
        stock_name=stock_name,
        industry=industry,
        cutoff_date=cutoff_date,
        generated_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    )

    # ==================== 并行获取数据 ====================
    price_start = (pd.to_datetime(cutoff_date) - pd.Timedelta(days=price_lookback_days)).strftime('%Y-%m-%d')

    loaders = {
        'price_history': lambda: provider.fetch_daily_single(ts_code, price_start, cutoff_date),
        'balancesheet': lambda: provider.fetch_balancesheet(ts_code),
        'income': lambda: provider.fetch_income(ts_code),
        'cashflow': lambda: provider.fetch_cashflow(ts_code),
        'fina_indicator': lambda: provider.fetch_financial_indicator(ts_code),
        'dividend': lambda: provider.fetch_dividend(ts_code),
        'top10_holders': lambda: provider.fetch_top10_holders(ts_code),
        'top10_floatholders': lambda: provider.fetch_top10_floatholders(ts_code),
        'fina_audit': lambda: provider.fetch_fina_audit(ts_code),
        'fina_mainbz': lambda: provider.fetch_fina_mainbz(ts_code),
        'pledge_stat': lambda: provider.fetch_pledge_stat(ts_code),
        'stk_holdernumber': lambda: provider.fetch_stk_holdernumber(ts_code),
        'stk_holdertrade': lambda: provider.fetch_stk_holdertrade(ts_code),
        'share_float': lambda: provider.fetch_share_float(ts_code),
        'repurchase': lambda: provider.fetch_repurchase(ts_code),
    }

    data = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {k: executor.submit(fn) for k, fn in loaders.items()}
        for k, fut in futures.items():
            try:
                data[k] = fut.result()
            except Exception as e:
                logger.warning(f"获取 {k} 失败: {e}")
                data[k] = pd.DataFrame()

    # ==================== 赋值到 Snapshot ====================

    # 行情
    snapshot.price_history = data['price_history']
    if not snapshot.price_history.empty:
        snapshot.data_sources.append('daily_price')

    # daily_indicators 免费源没有，留空（算子会降级处理）
    snapshot.daily_indicators = pd.DataFrame()

    # 财报 — 按 ann_date 过滤（CrawlerProvider 已提供 ann_date 列）
    for attr in ['balancesheet', 'income', 'cashflow', 'fina_indicator']:
        df = data[attr]
        if not df.empty and 'ann_date' in df.columns:
            df = df[df['ann_date'].notna()]
            df = df[df['ann_date'] <= cutoff_date]
        setattr(snapshot, attr, df)
        if not df.empty:
            snapshot.data_sources.append(attr)

    # 按 ann_date 过滤的补充数据
    for attr, date_col in [
        ('dividend', 'ann_date'),
        ('top10_holders', 'ann_date'),
        ('top10_floatholders', 'ann_date'),
        ('fina_audit', 'ann_date'),
        ('stk_holdernumber', 'ann_date'),
        ('stk_holdertrade', 'ann_date'),
        ('repurchase', 'ann_date'),
        ('share_float', 'float_date'),
    ]:
        df = data[attr]
        if not df.empty and date_col in df.columns:
            df = df[df[date_col].notna()]
            df = df[df[date_col] <= cutoff_date]
        setattr(snapshot, attr, df)
        if not df.empty:
            snapshot.data_sources.append(attr)

    # 无日期过滤
    for attr in ['fina_mainbz', 'pledge_stat']:
        df = data[attr]
        setattr(snapshot, attr, df)
        if not df.empty:
            snapshot.data_sources.append(attr)

    # ==================== 实时增强数据（回测没有的）====================

    # 新闻
    try:
        snapshot.news = provider.fetch_news(ts_code, limit=15)
        if not snapshot.news.empty:
            snapshot.data_sources.append('news')
    except Exception:
        snapshot.news = pd.DataFrame()

    # 主力资金流
    try:
        snapshot.fund_flow = provider.fetch_fund_flow(ts_code, days=30)
        if not snapshot.fund_flow.empty:
            snapshot.data_sources.append('fund_flow')
    except Exception:
        snapshot.fund_flow = pd.DataFrame()

    # 大盘指数
    try:
        snapshot.index_daily = provider.fetch_index_daily('sh000300', days=60)
        if not snapshot.index_daily.empty:
            snapshot.data_sources.append('index_daily')
    except Exception:
        snapshot.index_daily = pd.DataFrame()

    # 行业板块汇总
    try:
        snapshot.industry_summary = provider.fetch_industry_summary()
        if not snapshot.industry_summary.empty:
            snapshot.data_sources.append('industry_summary')
    except Exception:
        snapshot.industry_summary = pd.DataFrame()

    # ==================== 元数据 ====================
    if not snapshot.balancesheet.empty and 'end_date' in snapshot.balancesheet.columns:
        snapshot.latest_report_period = snapshot.balancesheet['end_date'].max()

    if snapshot.price_history.empty:
        snapshot.warnings.append("无行情数据")
    if snapshot.balancesheet.empty:
        snapshot.warnings.append("无资产负债表")
    if snapshot.income.empty:
        snapshot.warnings.append("无利润表")

    logger.info(f"实时快照生成完成: {ts_code} | 数据源: {len(snapshot.data_sources)} | 警告: {len(snapshot.warnings)}")
    return snapshot
