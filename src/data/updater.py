"""
数据更新器

通过 DataProvider 抽象层获取数据，批量存储到 Parquet。
支持双向增量: 自动检测已有数据范围，向前回填 + 向后追加。
起始日期由 DATA_START_DATE 控制 (默认 2015-01-01，可通过环境变量覆盖)。

全量获取 (首次部署，按顺序执行):
    python -m src.engine.launcher data daily-update           # 1. 行情+指标+截面因子 (自动从 2015 回填)
    python -m src.engine.launcher data update-financials      # 2. 全市场财报 (~5000只，最耗时)
    python -m src.engine.launcher data update-ts-factors      # 3. 时序因子 (依赖财报)

日常增量 (每日运行):
    python -m src.engine.launcher data daily-update           # 行情+指标+截面因子

单项命令:
    python -m src.engine.launcher data status                 # 查看数据状态
    python -m src.engine.launcher data update-daily           # 仅日线行情
    python -m src.engine.launcher data update-indicator       # 仅日线指标
    python -m src.engine.launcher data update-financials 601288.SH  # 指定股票财报
    python -m src.engine.launcher data update-factors         # 仅截面因子
    python -m src.engine.launcher data recalc-factors         # 清空并全量重算截面因子
    python -m src.engine.launcher data recalc-ts-factors      # 清空并全量重算时序因子
"""
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

import pandas as pd

from . import api, storage
from .provider import get_provider, DataProvider
from .settings import DATA_START_DATE

logger = logging.getLogger(__name__)

# API 调用间隔 (秒)
_API_SLEEP = 0.3


class DataUpdater:
    """统一数据更新器"""

    def __init__(self, provider_name: str = None):
        self.provider: DataProvider = get_provider(provider_name)
        self._today = datetime.now().strftime('%Y-%m-%d')

    # ==================== 基础数据 ====================

    def update_stock_list(self) -> bool:
        """更新股票列表 (全量覆盖)"""
        print("更新股票列表...", end=' ')
        df = self.provider.fetch_stock_list()
        if df.empty:
            print("失败: 无数据")
            return False
        storage.save(df, 'basic', '', 'stock_list')
        print(f"完成, {len(df)} 条")
        return True

    def update_trade_calendar(self, start_date: str = '2000-01-01', end_date: str = None) -> bool:
        """更新交易日历 (全量覆盖)"""
        if end_date is None:
            end_date = (datetime.now() + timedelta(days=365)).strftime('%Y-%m-%d')
        print(f"更新交易日历 {start_date} ~ {end_date}...", end=' ')
        df = self.provider.fetch_trade_calendar(start_date, end_date)
        if df.empty:
            print("失败: 无数据")
            return False
        storage.save(df, 'basic', '', 'trade_calendar')
        print(f"完成, {len(df)} 条")
        return True

    # ==================== 日线数据 (批量) ====================

    @staticmethod
    def _get_date_ranges(category_sub: str, start_date: str = None, end_date: str = None):
        """计算需要更新的日期范围 (支持向前回填 + 向后增量)

        Returns:
            List[Tuple[str, str]]: 需要更新的 (start, end) 范围列表
        """
        today = datetime.now().strftime('%Y-%m-%d')
        if end_date is None:
            end_date = today

        # 显式指定 start_date → 单段直接返回
        if start_date is not None:
            return [(start_date, end_date)]

        # 自动检测：查找已有数据边界
        category, sub = category_sub.split('/')
        partitions = storage.list_partitions(category, sub)

        if not partitions:
            # 无数据：从 DATA_START_DATE 到 today
            return [(DATA_START_DATE, end_date)]

        # 最早分区的首日 和 最新实际日期
        earliest_partition = partitions[0]  # e.g. '2019-01'
        latest_date = storage.get_latest_date(category, sub)

        ranges = []

        # 向前回填：DATA_START_DATE ~ earliest_partition 首日前一天
        earliest_first_day = f"{earliest_partition}-01"
        if DATA_START_DATE < earliest_first_day:
            backfill_end = (pd.to_datetime(earliest_first_day) - timedelta(days=1)).strftime('%Y-%m-%d')
            ranges.append((DATA_START_DATE, backfill_end))

        # 向后增量：latest_date + 1 ~ end_date
        if latest_date and latest_date < end_date:
            forward_start = (pd.to_datetime(latest_date) + timedelta(days=1)).strftime('%Y-%m-%d')
            ranges.append((forward_start, end_date))

        return ranges

    def update_daily(self, start_date: str = None, end_date: str = None) -> bool:
        """增量更新日线行情 + 复权因子 (支持向前回填 + 向后增量)"""
        ranges = self._get_date_ranges('daily/raw', start_date, end_date)
        if not ranges:
            print("日线数据已是最新")
            return True

        merge_on = ['ts_code', 'trade_date']

        for seg_start, seg_end in ranges:
            print(f"更新日线 {seg_start} ~ {seg_end}")
            trade_dates = api.get_trade_dates(seg_start, seg_end)
            if not trade_dates:
                print("  无交易日")
                continue

            total = len(trade_dates)
            for i, date in enumerate(trade_dates, 1):
                print(f"  [{i}/{total}] {date}...", end=' ')

                df_raw = self.provider.fetch_daily_bulk(trade_date=date)
                if df_raw.empty:
                    print("无数据")
                    time.sleep(_API_SLEEP)
                    continue

                month = storage.get_month(date)
                storage.save(df_raw, 'daily', 'raw', month, mode='merge', merge_on=merge_on)
                time.sleep(_API_SLEEP)

                df_adj = self.provider.fetch_adj_factor_bulk(trade_date=date)
                if not df_adj.empty:
                    storage.save(df_adj, 'daily', 'adj_factor', month, mode='merge', merge_on=merge_on)

                print(f"行情 {len(df_raw)}, 复权 {len(df_adj)}")
                time.sleep(_API_SLEEP)

        print("日线更新完成")
        return True

    def update_daily_indicator(self, start_date: str = None, end_date: str = None) -> bool:
        """增量更新每日指标 (支持向前回填 + 向后增量)"""
        ranges = self._get_date_ranges('daily/indicator', start_date, end_date)
        if not ranges:
            print("每日指标已是最新")
            return True

        merge_on = ['ts_code', 'trade_date']

        for seg_start, seg_end in ranges:
            print(f"更新每日指标 {seg_start} ~ {seg_end}")
            trade_dates = api.get_trade_dates(seg_start, seg_end)
            if not trade_dates:
                print("  无交易日")
                continue

            total = len(trade_dates)
            for i, date in enumerate(trade_dates, 1):
                print(f"  [{i}/{total}] {date}...", end=' ')
                df = self.provider.fetch_daily_indicator_bulk(trade_date=date)
                if df.empty:
                    print("无数据")
                    time.sleep(_API_SLEEP)
                    continue
                month = storage.get_month(date)
                storage.save(df, 'daily', 'indicator', month, mode='merge', merge_on=merge_on)
                print(f"{len(df)} 条")
                time.sleep(_API_SLEEP)

        print("每日指标更新完成")
        return True

    # ==================== 财报数据 (批量) ====================

    @staticmethod
    def _latest_quarter_end() -> str:
        """计算最近一个已完成的季报期 (考虑财报披露滞后)

        规则: 财报通常滞后 1~4 个月披露，保守取前两个季度
        例如 2026-03-15 → 最近完成季报期为 2025-09-30 (Q3)
        """
        now = datetime.now()
        # 当前日期往前推 6 个月，取对应季末
        ref = now - timedelta(days=180)
        quarter_month = (ref.month - 1) // 3 * 3 + 3
        quarter_end_day = {3: 31, 6: 30, 9: 30, 12: 31}[quarter_month]
        return f"{ref.year}-{quarter_month:02d}-{quarter_end_day:02d}"

    def _classify_stocks_for_update(
        self, ts_codes: List[str]
    ) -> tuple:
        """将股票分类: 无数据 / 过期 / 最新

        Returns:
            (need_update, skipped_count): 需要更新的代码列表, 跳过数量
        """
        existing = set(storage.list_financial_partitions('income'))
        cutoff = self._latest_quarter_end()

        need_update = []
        fresh_count = 0

        for code in ts_codes:
            if code not in existing:
                need_update.append(code)
                continue

            # 读取已有 income 的最新 end_date
            try:
                df = pd.read_parquet(
                    storage.get_financial_path('income', code),
                    columns=['end_date'],
                )
                latest = df['end_date'].max() if not df.empty else None
            except Exception:
                latest = None

            if latest is None or latest < cutoff:
                need_update.append(code)
            else:
                fresh_count += 1

        return need_update, fresh_count

    def update_financials(
        self,
        ts_codes: Optional[List[str]] = None,
        sleep: float = _API_SLEEP,
        skip_existing: bool = False,
    ) -> bool:
        """批量更新财报数据 (三大报表 + 财务指标 + 分红 + 股东)

        Args:
            ts_codes: 股票代码列表。None 或空列表时自动获取全部活跃股票
            sleep: API 调用间隔
            skip_existing: 增量模式 — 跳过数据已是最新的股票
                (检查 income 表最新 end_date 是否覆盖最近季报期)
        """
        from . import api as _api

        if not ts_codes:
            all_codes = _api.get_stock_codes(only_active=True)
            print(f"未指定股票列表，自动获取全部活跃股票: {len(all_codes)} 只")
            ts_codes = all_codes

        if skip_existing:
            cutoff = self._latest_quarter_end()
            need_update, fresh_count = self._classify_stocks_for_update(ts_codes)
            print(f"增量模式 (季报截止 {cutoff}): "
                  f"已是最新 {fresh_count} 只, 需更新 {len(need_update)} 只")
            ts_codes = need_update

        total = len(ts_codes)
        if total == 0:
            print("无需更新")
            return True

        print(f"批量更新财报: {total} 只股票")

        for i, ts_code in enumerate(ts_codes, 1):
            print(f"[{i}/{total}] {ts_code}")
            self._update_one_stock_financials(ts_code, sleep)
            if i % 100 == 0:
                print(f"  --- 进度: {i}/{total} ({i*100//total}%) ---")

        print(f"财报批量更新完成: {total} 只")
        return True

    # ==================== 财报数据 (按报告期截面) ====================

    @staticmethod
    def _all_quarter_periods(start_date: str = None) -> List[str]:
        """生成从 start_date 到当前的所有季报期

        Returns:
            ['2015-03-31', '2015-06-30', ..., '2025-09-30']
        """
        start = start_date or DATA_START_DATE
        start_dt = pd.to_datetime(start)
        now = datetime.now()
        periods = []
        for year in range(start_dt.year, now.year + 1):
            for month, day in [(3, 31), (6, 30), (9, 30), (12, 31)]:
                p = f"{year}-{month:02d}-{day:02d}"
                if p >= start[:10] and pd.to_datetime(p) <= now:
                    periods.append(p)
        return periods

    def _find_missing_periods(self, all_periods: List[str]) -> List[str]:
        """检测尚未覆盖的报告期

        策略: 从 income 目录随机抽样若干股票，检查哪些 period 缺失。
        如果多数样本都缺少某个 period，则认为该 period 需要更新。
        """
        existing_codes = storage.list_financial_partitions('income')
        if not existing_codes:
            return all_periods  # 无数据，全部需要

        # 抽样检查 (最多 20 只)
        import random
        sample = random.sample(existing_codes, min(20, len(existing_codes)))

        # 统计每个 period 在样本中的覆盖率
        period_coverage = {p: 0 for p in all_periods}
        for code in sample:
            try:
                df = pd.read_parquet(
                    storage.get_financial_path('income', code),
                    columns=['end_date'],
                )
                covered = set(df['end_date'].dropna().unique())
                for p in all_periods:
                    if p in covered:
                        period_coverage[p] += 1
            except Exception:
                pass

        threshold = len(sample) * 0.8  # 80% 覆盖率视为已有
        missing = [p for p in all_periods if period_coverage[p] < threshold]
        return missing

    def update_financials_by_period(self, start_date: str = None,
                                     sleep: float = _API_SLEEP) -> bool:
        """按报告期截面更新核心财报 (income/balancesheet/cashflow/fina_indicator)

        两阶段:
          1. API 获取: 按 period 截面拉取，汇总到内存 (API 调用 = N_periods × 4)
          2. 批量写入: 按 ts_code 分组，每只股票的文件只读写一次
        """
        import sys

        all_periods = self._all_quarter_periods(start_date)
        missing = self._find_missing_periods(all_periods)

        if not missing:
            print("核心财报数据已是最新 (截面检查)")
            return True

        # (表名, fetch方法, merge去重键)
        tables = [
            ('income', self.provider.fetch_income_by_period, ['ts_code', 'end_date']),
            ('balancesheet', self.provider.fetch_balancesheet_by_period, ['ts_code', 'end_date']),
            ('cashflow', self.provider.fetch_cashflow_by_period, ['ts_code', 'end_date']),
            ('fina_indicator', self.provider.fetch_fina_indicator_by_period, ['ts_code', 'end_date']),
        ]

        # ---- 阶段 1: API 获取，按表汇总 ----
        print(f"阶段1: API 获取 {len(missing)} 个报告期 × {len(tables)} 表 "
              f"= {len(missing) * len(tables)} 次调用")
        sys.stdout.flush()

        # {table_name: [df, df, ...]}
        table_dfs = {name: [] for name, _, _ in tables}

        for period_idx, period in enumerate(missing, 1):
            print(f"  [{period_idx}/{len(missing)}] {period}", end='')
            sys.stdout.flush()
            for table_name, fetch_fn, _ in tables:
                try:
                    df = fetch_fn(period)
                    if not df.empty:
                        table_dfs[table_name].append(df)
                        print(f"  {table_name}:{len(df)}", end='')
                    time.sleep(sleep)
                except Exception as e:
                    logger.warning(f"  {table_name}@{period} 失败: {e}")
                    print(f"  {table_name}:ERR", end='')
            print()  # 换行
            sys.stdout.flush()

        # ---- 阶段 2: 按 ts_code 批量写入 ----
        for table_name, _, merge_on in tables:
            dfs = table_dfs[table_name]
            if not dfs:
                print(f"\n{table_name}: 无新数据")
                continue

            combined = pd.concat(dfs, ignore_index=True)
            grouped = combined.groupby('ts_code')
            total_stocks = len(grouped)
            print(f"\n阶段2: {table_name} 写入 {len(combined)} 条 → {total_stocks} 只股票")
            sys.stdout.flush()

            done = 0
            for ts_code, group in grouped:
                storage.save_financial(
                    group, table_name, ts_code,
                    mode='merge', merge_on=merge_on,
                )
                done += 1
                if done % 500 == 0:
                    print(f"  {done}/{total_stocks}")
                    sys.stdout.flush()

            print(f"  {table_name} 完成: {total_stocks} 只股票")
            sys.stdout.flush()

        print(f"\n截面更新完成: {len(missing)} 个报告期")
        return True

    def _update_one_stock_financials(self, ts_code: str, sleep: float = _API_SLEEP):
        """更新单只股票全部财报数据"""
        tasks = [
            # (存储子目录, 拉取函数, merge去重键)  None=全量覆盖
            ('balancesheet', self.provider.fetch_balancesheet, ['ts_code', 'end_date']),
            ('income', self.provider.fetch_income, ['ts_code', 'end_date']),
            ('cashflow', self.provider.fetch_cashflow, ['ts_code', 'end_date']),
            ('fina_indicator', self.provider.fetch_financial_indicator, ['ts_code', 'end_date']),
            ('dividend', self.provider.fetch_dividend, None),
            ('top10_holders', self.provider.fetch_top10_holders, None),
            ('top10_floatholders', self.provider.fetch_top10_floatholders, None),
            ('pledge_stat', self.provider.fetch_pledge_stat, ['ts_code', 'end_date']),
            ('pledge_detail', self.provider.fetch_pledge_detail, None),
            ('fina_audit', self.provider.fetch_fina_audit, ['ts_code', 'end_date']),
            ('fina_mainbz', self.provider.fetch_fina_mainbz, None),
            ('stk_holdernumber', self.provider.fetch_stk_holdernumber, ['ts_code', 'end_date']),
            ('stk_holdertrade', self.provider.fetch_stk_holdertrade, None),
            ('share_float', self.provider.fetch_share_float, None),
            ('repurchase', self.provider.fetch_repurchase, None),
        ]

        for sub, fetch_fn, merge_on in tasks:
            try:
                df = fetch_fn(ts_code)
                if not df.empty:
                    if merge_on:
                        storage.save_financial(df, sub, ts_code, mode='merge', merge_on=merge_on)
                    else:
                        storage.save_financial(df, sub, ts_code, mode='overwrite')
                    logger.debug(f"  {sub}: {len(df)} 条")
                time.sleep(sleep)
            except Exception as e:
                logger.warning(f"  {sub} 失败: {e}")

    def update_disclosure_date(self, end_date: Optional[str] = None) -> bool:
        """更新财报披露日期 (全市场)，从 DATA_START_DATE 起所有季度"""
        if end_date:
            periods = [end_date]
        else:
            # 生成从 DATA_START_DATE 年份到当前年份的所有季度
            start_year = int(DATA_START_DATE[:4])
            now = datetime.now()
            periods = []
            for year in range(start_year, now.year + 1):
                for month in ['03-31', '06-30', '09-30', '12-31']:
                    p = f"{year}-{month}"
                    if p <= now.strftime('%Y-%m-%d'):
                        periods.append(p)
            periods.sort()
            # 跳过已有文件
            from .settings import FINANCIAL_DATA_DIR
            disc_dir = FINANCIAL_DATA_DIR / 'disclosure_date'
            existing = {f.stem for f in disc_dir.glob('*.parquet')} if disc_dir.exists() else set()
            periods = [p for p in periods if p.replace('-', '') not in existing]
            if not periods:
                print("  披露日期: 已全部获取")
                return True
            print(f"  需获取 {len(periods)} 个季度的披露日期")

        for period in periods:
            print(f"  披露日期 {period}...", end=' ')
            df = self.provider.fetch_disclosure_date(end_date=period)
            if not df.empty:
                storage.save_financial(df, 'disclosure_date', period.replace('-', ''),
                                       mode='overwrite')
                print(f"{len(df)} 条")
            else:
                print("无数据")
            time.sleep(0.5)

        return True

    # ==================== 因子预计算 ====================

    def update_factors(self, start_date: str = None, end_date: str = None,
                       strategy_dir: Path = None) -> bool:
        """预计算截面因子并存储"""
        from .factor_store import compute_and_store_factors
        return compute_and_store_factors(start_date, end_date, strategy_dir)

    def update_ts_factors(self, ts_codes: List[str] = None,
                          strategy_dir: Path = None) -> bool:
        """增量计算时序因子"""
        from .factor_store import compute_and_store_ts_factors
        return compute_and_store_ts_factors(ts_codes, strategy_dir)

    # ==================== 组合更新 ====================

    def init_basic(self):
        """初始化基础数据 (股票列表 + 交易日历)"""
        print("=" * 50)
        print("初始化基础数据")
        print("=" * 50)
        self.update_stock_list()
        self.update_trade_calendar()

    def init_market_data(self, start_date: str = '2020-01-01'):
        """初始化行情数据"""
        print("=" * 50)
        print(f"初始化行情数据 (从 {start_date})")
        print("=" * 50)
        self.update_daily(start_date=start_date)
        self.update_daily_indicator(start_date=start_date)
        print("计算因子...")
        self.update_factors(start_date=start_date)

    def daily_update(self):
        """每日增量更新 (行情 + 指标 + 因子)"""
        print("=" * 50)
        print(f"每日增量更新 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print("=" * 50)
        self.update_stock_list()
        self.update_daily()
        self.update_daily_indicator()
        self.update_factors()
        print("=" * 50)
        print("更新完成")
        print("=" * 50)

    def full_update(self, market_start: str = '2020-01-01',
                    financial_codes: List[str] = None):
        """全量更新 (基础 + 行情 + 财报 + 因子)

        Args:
            market_start: 行情数据起始日期
            financial_codes: 需要更新财报的股票列表, None 则跳过财报
        """
        print("=" * 60)
        print(f"全量更新 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print("=" * 60)

        self.init_basic()
        self.update_daily(start_date=market_start)
        self.update_daily_indicator(start_date=market_start)
        self.update_disclosure_date()

        if financial_codes:
            self.update_financials(financial_codes)
            self.update_ts_factors(financial_codes)

        self.update_factors(start_date=market_start)

        print("=" * 60)
        print("全量更新完成")
        print("=" * 60)


# ==================== 向后兼容的模块级函数 ====================

def _get_updater() -> DataUpdater:
    return DataUpdater()


def update_stock_list():
    return _get_updater().update_stock_list()


def update_trade_calendar(start_date='2000-01-01', end_date=None):
    return _get_updater().update_trade_calendar(start_date, end_date)


def update_daily(start_date=None, end_date=None):
    return _get_updater().update_daily(start_date, end_date)


def update_daily_indicator(start_date=None, end_date=None):
    return _get_updater().update_daily_indicator(start_date, end_date)


def update_financial_statements(ts_code: str, force: bool = False):
    return _get_updater()._update_one_stock_financials(ts_code)


def update_dividend(ts_code: str):
    updater = _get_updater()
    df = updater.provider.fetch_dividend(ts_code)
    if not df.empty:
        storage.save_financial(df, 'dividend', ts_code, mode='overwrite')
    return True


def update_disclosure_date(end_date=None):
    return _get_updater().update_disclosure_date(end_date)


def update_top10_holders(ts_code: str):
    updater = _get_updater()
    df = updater.provider.fetch_top10_holders(ts_code)
    if not df.empty:
        storage.save_financial(df, 'top10_holders', ts_code, mode='overwrite')
    return True


def update_stock_all(ts_code: str):
    print(f"{'=' * 40}")
    print(f"全量更新 {ts_code}")
    print(f"{'=' * 40}")
    updater = _get_updater()
    updater._update_one_stock_financials(ts_code)
    print(f"{ts_code} 全部完成")


def init_basic():
    _get_updater().init_basic()


def init_market_data(start_date='2020-01-01'):
    _get_updater().init_market_data(start_date)


def daily_update():
    _get_updater().daily_update()
