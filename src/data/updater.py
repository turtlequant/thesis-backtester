"""Provider-neutral downloader and incremental updater.

Long BaoStock history is bootstrapped by stock/date ranges; once that baseline
exists, its tail is updated by trading-day full-market snapshots.  Both provider
paths write the same logical datasets into provider-isolated SQLite databases.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd

from . import storage
from .config import get_data_start_date
from .provider import DataProvider, get_provider

logger = logging.getLogger(__name__)
_API_SLEEP = 0.3


class UpdateCancelled(RuntimeError):
    pass


class NoDataAvailable(RuntimeError):
    """A valid provider query completed but returned no usable rows."""

    pass


class DataUpdater:
    """Download datasets from one provider without cross-provider fallback."""

    def __init__(
        self,
        provider_name: str = None,
        progress: Optional[Callable[[Dict[str, object]], None]] = None,
        cancel_event=None,
    ):
        self.provider: DataProvider = get_provider(provider_name)
        self.provider_name = self.provider.name
        self.progress = progress
        self.cancel_event = cancel_event

    def _emit(
        self,
        stage: str,
        message: str,
        current: int = 0,
        total: int = 0,
    ) -> None:
        if self.progress:
            self.progress(
                {
                    "stage": stage,
                    "message": message,
                    "current": current,
                    "total": total,
                    "percent": round(current * 100 / total, 1) if total else 0,
                }
            )

    def _check_cancelled(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise UpdateCancelled("下载任务已取消")

    def close(self) -> None:
        closer = getattr(self.provider, "close", None)
        if closer:
            closer()

    # ---------- Basic data ----------

    def update_stock_list(self) -> bool:
        self._emit("stock_list", "正在更新股票列表")
        frame = self.provider.fetch_stock_list()
        if frame.empty:
            return False
        stored = storage.save(
            frame,
            "basic",
            "",
            "stock_list",
            provider=self.provider_name,
        )
        if stored:
            from .api import clear_basic_caches

            clear_basic_caches()
        self._emit("stock_list", f"股票列表完成，共 {len(frame)} 条", 1, 1)
        return stored

    def update_trade_calendar(
        self,
        start_date: str = "2000-01-01",
        end_date: str = None,
    ) -> bool:
        end_date = end_date or (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
        self._emit("trade_calendar", f"正在更新交易日历 {start_date} ~ {end_date}")
        frame = self.provider.fetch_trade_calendar(start_date, end_date)
        if frame.empty:
            return False
        stored = storage.save(
            frame,
            "basic",
            "",
            "trade_calendar",
            provider=self.provider_name,
        )
        if stored:
            from .api import clear_basic_caches

            clear_basic_caches()
        self._emit("trade_calendar", f"交易日历完成，共 {len(frame)} 条", 1, 1)
        return stored

    def _stock_codes(self, requested: Optional[List[str]] = None) -> List[str]:
        if requested:
            return sorted(set(code.upper() for code in requested))
        frame = storage.load_one(
            "basic",
            "",
            "stock_list",
            provider=self.provider_name,
        )
        if frame.empty:
            if not self.update_stock_list():
                return []
            frame = storage.load_one(
                "basic",
                "",
                "stock_list",
                provider=self.provider_name,
            )
        # Historical downloads must retain delisted stocks; filtering to the
        # current listed universe would introduce survivorship bias.
        return sorted(frame["ts_code"].dropna().astype(str).unique().tolist())

    def _stock_download_tasks(
        self,
        codes: List[str],
        ranges: List[Tuple[str, str]],
    ) -> Tuple[List[Tuple[str, str, str, str]], int]:
        """Clip stock ranges to their actual listed lifetime.

        Returns ``(tasks, skipped)`` where each task is
        ``(code, effective_start, effective_end, list_status)``.  Delisted
        stocks are retained whenever their lifetime overlaps the requested
        history, avoiding survivorship bias without querying impossible dates.
        """
        frame = storage.load_one(
            "basic",
            "",
            "stock_list",
            provider=self.provider_name,
        )
        metadata: Dict[str, Dict[str, str]] = {}
        if not frame.empty and "ts_code" in frame.columns:
            wanted = frame[frame["ts_code"].astype(str).isin(codes)].copy()

            def clean_text(value: object) -> str:
                if value is None or pd.isna(value):
                    return ""
                return str(value)

            for row in wanted.to_dict("records"):
                metadata[clean_text(row.get("ts_code"))] = {
                    "list_date": clean_text(row.get("list_date")),
                    "delist_date": clean_text(row.get("delist_date")),
                    "list_status": clean_text(row.get("list_status")),
                }

        def valid_date(value: str) -> Optional[str]:
            value = str(value or "").strip()
            if len(value) >= 10 and value[:10] not in {"1900-01-01", "0000-00-00"}:
                try:
                    return pd.to_datetime(value[:10]).strftime("%Y-%m-%d")
                except (TypeError, ValueError):
                    return None
            return None

        tasks: List[Tuple[str, str, str, str]] = []
        skipped = 0
        for range_start, range_end in ranges:
            for code in codes:
                item = metadata.get(code, {})
                list_date = valid_date(item.get("list_date", ""))
                delist_date = valid_date(item.get("delist_date", ""))
                effective_start = max(range_start, list_date) if list_date else range_start
                effective_end = min(range_end, delist_date) if delist_date else range_end
                if effective_start > effective_end:
                    skipped += 1
                    continue
                tasks.append(
                    (code, effective_start, effective_end, item.get("list_status", ""))
                )
        return tasks, skipped

    def _stock_codes_in_range(
        self,
        codes: List[str],
        start_date: str,
        end_date: str,
    ) -> List[str]:
        tasks, _ = self._stock_download_tasks(codes, [(start_date, end_date)])
        return sorted({code for code, _start, _end, _status in tasks})

    def _trade_dates(self, start_date: str, end_date: str) -> List[str]:
        frame = storage.load_one(
            "basic",
            "",
            "trade_calendar",
            provider=self.provider_name,
        )
        if frame.empty:
            self.update_trade_calendar(start_date, end_date)
            frame = storage.load_one(
                "basic",
                "",
                "trade_calendar",
                provider=self.provider_name,
            )
        if frame.empty:
            return []
        frame = frame[(frame["cal_date"] >= start_date) & (frame["cal_date"] <= end_date)]
        frame = frame[frame["is_open"] == 1]
        return frame["cal_date"].sort_values().astype(str).tolist()

    # ---------- Daily market data ----------

    def _get_date_ranges(
        self,
        category_sub: str,
        start_date: str = None,
        end_date: str = None,
    ) -> List[Tuple[str, str]]:
        end_date = end_date or datetime.now().strftime("%Y-%m-%d")
        if start_date:
            return [(start_date, end_date)]

        configured_start = get_data_start_date()
        category, sub = category_sub.split("/")
        partitions = storage.list_partitions(category, sub, provider=self.provider_name)
        if not partitions:
            return [(configured_start, end_date)]

        ranges: List[Tuple[str, str]] = []
        earliest_first_day = f"{partitions[0]}-01"
        if configured_start < earliest_first_day:
            before = (pd.to_datetime(earliest_first_day) - timedelta(days=1)).strftime("%Y-%m-%d")
            ranges.append((configured_start, before))
        latest = storage.get_latest_date(category, sub, provider=self.provider_name)
        if latest and latest < end_date:
            after = (pd.to_datetime(latest) + timedelta(days=1)).strftime("%Y-%m-%d")
            ranges.append((after, end_date))
        return ranges

    @staticmethod
    def _merge_date_ranges(ranges: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
        if not ranges:
            return []
        merged: List[Tuple[str, str]] = []
        for start_date, end_date in sorted(set(ranges)):
            if not merged:
                merged.append((start_date, end_date))
                continue
            previous_start, previous_end = merged[-1]
            adjacent = (pd.to_datetime(previous_end) + timedelta(days=1)).strftime("%Y-%m-%d")
            if start_date <= adjacent:
                merged[-1] = (previous_start, max(previous_end, end_date))
            else:
                merged.append((start_date, end_date))
        return merged

    def _latest_complete_daily_date(self) -> Optional[str]:
        latest_dates = [
            storage.get_latest_date("daily", sub, provider=self.provider_name)
            for sub in ("raw", "adj_factor", "indicator")
        ]
        return min(latest_dates) if all(latest_dates) else None

    def _update_baostock_daily(
        self,
        ranges: List[Tuple[str, str]],
        ts_codes: Optional[List[str]],
    ) -> bool:
        codes = self._stock_codes(ts_codes)
        if not codes:
            raise RuntimeError("没有可下载的股票代码")
        tasks, lifecycle_skipped = self._stock_download_tasks(codes, ranges)
        total = len(tasks)
        current = 0
        successful = 0
        failed = 0
        empty_delisted = 0
        buffers: Dict[str, Dict[str, List[pd.DataFrame]]] = {
            "raw": {},
            "adj_factor": {},
            "indicator": {},
        }

        def buffer_frame(sub: str, frame: pd.DataFrame) -> None:
            if frame.empty:
                return
            for month, group in frame.groupby(frame["trade_date"].astype(str).str[:7]):
                buffers[sub].setdefault(str(month), []).append(group)

        def flush_buffers() -> None:
            months = sorted({month for monthly in buffers.values() for month in monthly})
            partitions = {
                month: {
                    sub: pd.concat(monthly[month], ignore_index=True)
                    for sub, monthly in buffers.items()
                    if month in monthly
                }
                for month in months
            }
            if partitions and not storage.save_daily_partitions_atomic(
                partitions,
                provider=self.provider_name,
            ):
                raise RuntimeError("历史行情、复权与估值批次原子写入失败")
            for monthly in buffers.values():
                monthly.clear()

        if lifecycle_skipped:
            logger.info(
                "跳过 %s 个与请求区间无交集的退市/未上市股票区间",
                lifecycle_skipped,
            )

        for code, start_date, end_date, list_status in tasks:
            self._check_cancelled()
            current += 1
            self._emit(
                "market",
                f"正在下载 {code}：{start_date} ~ {end_date}",
                current,
                total,
            )
            try:
                bundle = self.provider.fetch_daily_bundle(code, start_date, end_date)
                if not bundle["raw"].empty:
                    successful += 1
                else:
                    if list_status == "D":
                        empty_delisted += 1
                        logger.info(
                            "BaoStock 退市股票行情为空，记录为无数据 %s: %s ~ %s",
                            code,
                            start_date,
                            end_date,
                        )
                        storage.save_ingestion_commit(
                            "daily_stock_checkpoint",
                            code,
                            {
                                "from_date": start_date,
                                "through_date": end_date,
                                "status": "no_data",
                                "terminal": True,
                            },
                            provider=self.provider_name,
                        )
                    else:
                        failed += 1
                        logger.warning(
                            "BaoStock 行情为空 %s: %s ~ %s",
                            code,
                            start_date,
                            end_date,
                        )
                buffer_frame("raw", bundle["raw"])
                buffer_frame("adj_factor", bundle["adj_factor"])
                buffer_frame("indicator", bundle["indicator"])
            except Exception as exc:
                failed += 1
                logger.warning("BaoStock 行情下载失败 %s: %s", code, exc)
            if current % 25 == 0:
                flush_buffers()
        flush_buffers()
        message = "行情、复权与估值数据更新完成"
        if lifecycle_skipped or empty_delisted:
            message += f"（跳过 {lifecycle_skipped + empty_delisted} 个无有效行情区间）"
        self._emit("market", message, total, total)
        return failed == 0 and (successful > 0 or empty_delisted > 0 or total == 0)

    def _update_bulk_daily(self, ranges: List[Tuple[str, str]]) -> bool:
        all_dates: List[str] = []
        for start_date, end_date in ranges:
            all_dates.extend(self._trade_dates(start_date, end_date))
        all_dates = sorted(set(all_dates))
        if all_dates:
            committed = set(
                storage.list_daily_snapshot_commits(
                    all_dates[0],
                    all_dates[-1],
                    provider=self.provider_name,
                )
            )
            all_dates = [trade_date for trade_date in all_dates if trade_date not in committed]
        total = len(all_dates)
        pending_dates: List[str] = []
        today = datetime.now().strftime("%Y-%m-%d")
        for index, trade_date in enumerate(all_dates, 1):
            self._check_cancelled()
            self._emit("market", f"正在下载 {trade_date} 全市场行情", index, total)
            snapshot_fetch = getattr(self.provider, "fetch_daily_snapshot", None)
            if callable(snapshot_fetch):
                snapshot = snapshot_fetch(trade_date)
                frames = {
                    "raw": snapshot.get("raw", pd.DataFrame()),
                    "adj_factor": snapshot.get("adj_factor", pd.DataFrame()),
                    "indicator": snapshot.get("indicator", pd.DataFrame()),
                }
                empty = [name for name, frame in frames.items() if frame.empty]
                if empty:
                    if len(empty) == len(frames) and trade_date == today:
                        pending_dates.append(trade_date)
                        logger.info(
                            "%s 当日全市场数据尚未发布，本次增量暂不写入",
                            trade_date,
                        )
                        self._emit(
                            "market",
                            f"{trade_date} 当日数据尚未发布，将在下次增量更新时重试",
                            index,
                            total,
                        )
                        continue
                    raise RuntimeError(
                        f"{trade_date} 全市场快照不完整，缺少：{', '.join(empty)}"
                    )
                if not storage.save_daily_frames_atomic(
                    frames,
                    storage.get_month(trade_date),
                    provider=self.provider_name,
                    commit_date=trade_date,
                ):
                    raise RuntimeError(f"{trade_date} 全市场快照原子写入 SQLite 失败")
            else:
                raw = self.provider.fetch_daily_bulk(trade_date)
                if not raw.empty:
                    month = storage.get_month(trade_date)
                    storage.save(
                        raw,
                        "daily",
                        "raw",
                        month,
                        mode="merge",
                        merge_on=["ts_code", "trade_date"],
                        provider=self.provider_name,
                    )
                factors = self.provider.fetch_adj_factor_bulk(trade_date)
                if not factors.empty:
                    storage.save(
                        factors,
                        "daily",
                        "adj_factor",
                        storage.get_month(trade_date),
                        mode="merge",
                        merge_on=["ts_code", "trade_date"],
                        provider=self.provider_name,
                    )
            time.sleep(_API_SLEEP)
        message = "日线行情与复权因子更新完成"
        if pending_dates:
            message = (
                "行情已更新至最近可用交易日；"
                f"{', '.join(pending_dates)} 数据待发布"
            )
        self._emit("market", message, total, total)
        return True

    def update_daily(
        self,
        start_date: str = None,
        end_date: str = None,
        ts_codes: Optional[List[str]] = None,
    ) -> bool:
        supports_bundle = callable(getattr(self.provider, "fetch_daily_bundle", None))
        supports_snapshot = callable(getattr(self.provider, "fetch_daily_snapshot", None))

        # BaoStock's first historical load is much faster by stock range.  On a
        # retry, only stocks that have never been persisted are bootstrapped;
        # this prevents a partial first run from looking complete merely because
        # one stock already reached the latest date.
        if supports_bundle and supports_snapshot and start_date is None and ts_codes is None:
            baseline_start = get_data_start_date()
            baseline_end = end_date or datetime.now().strftime("%Y-%m-%d")
            all_codes = self._stock_codes_in_range(
                self._stock_codes(),
                baseline_start,
                baseline_end,
            )
            coverage_sets = [
                set(
                    storage.list_distinct_values(
                        "daily",
                        sub,
                        "ts_code",
                        provider=self.provider_name,
                    )
                )
                for sub in ("raw", "adj_factor", "indicator")
            ]
            existing_codes = set.intersection(*coverage_sets) if coverage_sets else set()
            for code in storage.list_ingestion_commits(
                "daily_stock_checkpoint",
                provider=self.provider_name,
            ):
                checkpoint = storage.get_ingestion_commit(
                    "daily_stock_checkpoint",
                    code,
                    provider=self.provider_name,
                )
                if (
                    checkpoint
                    and str(checkpoint.get("from_date", "")) <= baseline_start
                    and (
                        checkpoint.get("terminal") is True
                        or str(checkpoint.get("through_date", "")) >= baseline_end
                    )
                ):
                    existing_codes.add(code)
            missing_codes = [code for code in all_codes if code not in existing_codes]
            if missing_codes:
                self._emit(
                    "market",
                    f"继续历史基线：尚缺 {len(missing_codes)} 只股票",
                    0,
                    len(missing_codes),
                )
                if not self._update_baostock_daily(
                    [(baseline_start, baseline_end)],
                    missing_codes,
                ):
                    return False

        ranges = self._get_date_ranges("daily/raw", start_date, end_date)
        if supports_bundle and supports_snapshot and start_date is None and ts_codes is None:
            complete_latest = self._latest_complete_daily_date()
            raw_latest = storage.get_latest_date("daily", "raw", provider=self.provider_name)
            target_end = end_date or datetime.now().strftime("%Y-%m-%d")
            if complete_latest and raw_latest and complete_latest < raw_latest:
                repair_start = (pd.to_datetime(complete_latest) + timedelta(days=1)).strftime(
                    "%Y-%m-%d"
                )
                if repair_start <= target_end:
                    ranges.append((repair_start, target_end))
            ranges = self._merge_date_ranges(ranges)
        if not ranges:
            self._emit("market", "日线行情已是最新", 1, 1)
            return True

        if supports_bundle and (start_date is not None or ts_codes is not None):
            return self._update_baostock_daily(ranges, ts_codes)
        if supports_bundle and supports_snapshot:
            latest = storage.get_latest_date("daily", "raw", provider=self.provider_name)
            historical = [item for item in ranges if latest and item[1] < latest]
            incremental = [item for item in ranges if item not in historical]
            if historical and not self._update_baostock_daily(historical, None):
                return False
            if incremental:
                return self._update_bulk_daily(incremental)
            return True
        if supports_bundle:
            return self._update_baostock_daily(ranges, ts_codes)
        return self._update_bulk_daily(ranges)

    def update_daily_indicator(self, start_date: str = None, end_date: str = None) -> bool:
        has_atomic_daily = callable(getattr(self.provider, "fetch_daily_snapshot", None))
        if callable(getattr(self.provider, "fetch_daily_bundle", None)) or has_atomic_daily:
            # Snapshot-capable providers persist indicators together with quotes
            # and factors, so a second pass would duplicate remote API requests.
            self._emit("indicator", "每日指标已随行情同步", 1, 1)
            return True
        ranges = self._get_date_ranges("daily/indicator", start_date, end_date)
        if not ranges:
            self._emit("indicator", "每日指标已是最新", 1, 1)
            return True
        dates: List[str] = []
        for range_start, range_end in ranges:
            dates.extend(self._trade_dates(range_start, range_end))
        total = len(dates)
        for index, trade_date in enumerate(dates, 1):
            self._check_cancelled()
            self._emit("indicator", f"正在下载 {trade_date} 每日指标", index, total)
            frame = self.provider.fetch_daily_indicator_bulk(trade_date)
            if not frame.empty:
                storage.save(
                    frame,
                    "daily",
                    "indicator",
                    storage.get_month(trade_date),
                    mode="merge",
                    merge_on=["ts_code", "trade_date"],
                    provider=self.provider_name,
                )
            time.sleep(_API_SLEEP)
        self._emit("indicator", "每日指标更新完成", total, total)
        return True

    # ---------- Financial data ----------

    @staticmethod
    def _latest_quarter_end() -> str:
        periods = DataUpdater._all_quarter_periods()
        return periods[-1] if periods else get_data_start_date()

    def _classify_stocks_for_update(self, ts_codes: List[str]) -> Tuple[List[str], int]:
        cutoff = self._latest_quarter_end()
        configured_start = get_data_start_date()
        needed: List[str] = []
        fresh = 0
        for code in ts_codes:
            checkpoint = storage.get_ingestion_commit(
                "financial_stock_checkpoint",
                code,
                provider=self.provider_name,
            )
            terminal = bool(
                checkpoint
                and checkpoint.get("terminal") is True
                and str(checkpoint.get("from_date", "")) <= configured_start
            )
            if not terminal and (
                not checkpoint or str(checkpoint.get("through_date", "")) < cutoff
            ):
                needed.append(code)
            else:
                fresh += 1
        return needed, fresh

    def _update_one_stock_financials(
        self,
        ts_code: str,
        sleep: float = _API_SLEEP,
        incremental: bool = False,
    ) -> None:
        if hasattr(self.provider, "fetch_financial_bundle"):
            start_date = get_data_start_date()
            end_date = datetime.now().strftime("%Y-%m-%d")
            terminal = False
            basic = storage.load(
                "basic",
                "",
                ["stock_list"],
                ["ts_code", "list_date", "delist_date", "list_status"],
                filters=[("ts_code", "==", ts_code)],
                provider=self.provider_name,
            )
            if not basic.empty and basic["list_date"].notna().any():
                start_date = max(start_date, str(basic["list_date"].dropna().iloc[0]))
            if (
                not basic.empty
                and "delist_date" in basic.columns
                and basic["delist_date"].notna().any()
            ):
                delist_date = str(basic["delist_date"].dropna().iloc[0])
                end_date = min(end_date, delist_date)
                terminal = bool(
                    "list_status" in basic.columns
                    and basic["list_status"].astype(str).eq("D").any()
                )
            if incremental:
                existing = storage.load_financial(
                    "income",
                    [ts_code],
                    ["end_date"],
                    provider=self.provider_name,
                )
                if not existing.empty and existing["end_date"].notna().any():
                    latest = str(existing["end_date"].dropna().max())
                    start_date = max(start_date, f"{latest[:4]}-01-01")
            bundle = self.provider.fetch_financial_bundle(
                ts_code,
                start_date=start_date,
                end_date=end_date,
            )
            if not bundle or not any(
                frame is not None and not frame.empty for frame in bundle.values()
            ):
                raise NoDataAvailable(f"{ts_code} 财务接口返回空数据")
            if not storage.save_financial_bundle_atomic(
                bundle,
                ts_code,
                provider=self.provider_name,
                checkpoint_date=self._latest_quarter_end(),
                checkpoint_from_date=start_date,
                checkpoint_terminal=terminal,
            ):
                raise RuntimeError(f"{ts_code} 财务数据未完整写入")
            return

        tasks = [
            ("balancesheet", self.provider.fetch_balancesheet, ["ts_code", "end_date"]),
            ("income", self.provider.fetch_income, ["ts_code", "end_date"]),
            ("cashflow", self.provider.fetch_cashflow, ["ts_code", "end_date"]),
            ("fina_indicator", self.provider.fetch_financial_indicator, ["ts_code", "end_date"]),
            ("dividend", self.provider.fetch_dividend, None),
            ("top10_holders", self.provider.fetch_top10_holders, None),
            ("top10_floatholders", self.provider.fetch_top10_floatholders, None),
            ("pledge_stat", self.provider.fetch_pledge_stat, ["ts_code", "end_date"]),
            ("pledge_detail", self.provider.fetch_pledge_detail, None),
            ("fina_audit", self.provider.fetch_fina_audit, ["ts_code", "end_date"]),
            ("fina_mainbz", self.provider.fetch_fina_mainbz, None),
            ("stk_holdernumber", self.provider.fetch_stk_holdernumber, ["ts_code", "end_date"]),
            ("stk_holdertrade", self.provider.fetch_stk_holdertrade, None),
            ("share_float", self.provider.fetch_share_float, None),
            ("repurchase", self.provider.fetch_repurchase, None),
        ]
        bundle: Dict[str, pd.DataFrame] = {}
        failures: List[str] = []
        for sub, fetch, _keys in tasks:
            self._check_cancelled()
            try:
                frame = fetch(ts_code)
                if not frame.empty:
                    bundle[sub] = frame
            except Exception as exc:
                failures.append(sub)
                logger.warning("%s 财务数据 %s 下载失败: %s", ts_code, sub, exc)
            time.sleep(sleep)
        if failures:
            raise RuntimeError(f"{ts_code} 财务接口失败: {', '.join(failures)}")
        if not bundle:
            raise NoDataAvailable(f"{ts_code} 财务接口返回空数据")
        if not storage.save_financial_bundle_atomic(
            bundle,
            ts_code,
            provider=self.provider_name,
        ):
            raise RuntimeError(f"{ts_code} 财务数据未完整写入")

    def update_financials(
        self,
        ts_codes: Optional[List[str]] = None,
        sleep: float = _API_SLEEP,
        skip_existing: bool = False,
    ) -> bool:
        codes = self._stock_codes(ts_codes)
        update_start = get_data_start_date()
        update_end = datetime.now().strftime("%Y-%m-%d")
        lifecycle_tasks, lifecycle_skipped = self._stock_download_tasks(
            codes,
            [(update_start, update_end)],
        )
        codes = sorted({code for code, _start, _end, _status in lifecycle_tasks})
        statuses = {
            code: status for code, _start, _end, status in lifecycle_tasks
        }
        if skip_existing:
            codes, _ = self._classify_stocks_for_update(codes)
        total = len(codes)
        failed = 0
        no_data = 0
        if lifecycle_skipped:
            logger.info(
                "财务更新跳过 %s 只与配置区间无交集的股票",
                lifecycle_skipped,
            )
        for index, code in enumerate(codes, 1):
            self._check_cancelled()
            self._emit("financial", f"正在下载 {code} 财务数据", index, total)
            try:
                self._update_one_stock_financials(code, sleep, incremental=skip_existing)
            except NoDataAvailable as exc:
                if statuses.get(code) == "D":
                    no_data += 1
                    logger.info("退市股票无可用财务数据，记录为已检查: %s", code)
                    storage.save_ingestion_commit(
                        "financial_stock_checkpoint",
                        code,
                        {
                            "from_date": update_start,
                            "through_date": self._latest_quarter_end(),
                            "status": "no_data",
                            "terminal": True,
                        },
                        provider=self.provider_name,
                    )
                else:
                    failed += 1
                    logger.warning("%s 财务数据下载失败: %s", code, exc)
            except Exception as exc:
                failed += 1
                logger.warning("%s 财务数据下载失败: %s", code, exc)
        message = "财务数据更新完成"
        if lifecycle_skipped or no_data:
            message += f"（跳过 {lifecycle_skipped + no_data} 只无有效数据股票）"
        self._emit("financial", message, total, total)
        return failed == 0

    def update_dividends(
        self,
        ts_codes: Optional[List[str]] = None,
        sleep: float = 0.0,
        skip_existing: bool = True,
        fetch_workers: Optional[int] = None,
        batch_size: Optional[int] = None,
    ) -> bool:
        """Build the per-stock dividend history baseline.

        Core Tushare statements have full-market period endpoints, while the
        dividend history endpoint is stock-oriented.  Keep it as a separate,
        resumable stage so a failed or cancelled baseline continues from the
        unfinished stocks on the next financial job.
        """
        requested_codes = self._stock_codes(ts_codes)
        if not requested_codes:
            self._emit("dividend", "股票列表为空，无法建立分红历史基线", 0, 0)
            return False
        history_start = get_data_start_date()
        today = datetime.now().strftime("%Y-%m-%d")
        codes = self._stock_codes_in_range(requested_codes, history_start, today)
        lifecycle_skipped = len(requested_codes) - len(codes)
        if skip_existing:
            existing = set(
                storage.list_financial_partitions(
                    "dividend",
                    provider=self.provider_name,
                )
            )
            checked = set(
                storage.list_ingestion_commits(
                    "dividend_stock_checkpoint",
                    provider=self.provider_name,
                )
            )
            codes = [code for code in codes if code not in existing and code not in checked]

        total = len(codes)
        failed = 0
        worker_count = fetch_workers if fetch_workers is not None else (
            2 if self.provider_name == "tushare" else 1
        )
        worker_count = max(1, min(int(worker_count), 4))
        write_batch_size = max(worker_count, int(batch_size or worker_count * 8))

        def fetch_one(code: str) -> Tuple[str, pd.DataFrame, Optional[Exception]]:
            last_error: Optional[Exception] = None
            for attempt in range(3):
                try:
                    frame = self.provider.fetch_dividend(code)
                    if sleep:
                        time.sleep(sleep)
                    return code, frame, None
                except Exception as exc:
                    last_error = exc
                    if attempt < 2:
                        time.sleep(float(attempt + 1))
            return code, pd.DataFrame(), last_error

        if total:
            self._emit(
                "dividend",
                f"准备批量下载分红历史（{worker_count} 路并发，每批 {write_batch_size} 只）",
                0,
                total,
            )
        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="dividend-fetch",
        ) as executor:
            processed = 0
            for offset in range(0, total, write_batch_size):
                self._check_cancelled()
                code_batch = codes[offset : offset + write_batch_size]
                results = list(executor.map(fetch_one, code_batch))
                self._check_cancelled()

                fetched = {
                    code: frame
                    for code, frame, error in results
                    if error is None
                }
                fetch_errors = [
                    (code, error)
                    for code, _frame, error in results
                    if error is not None
                ]
                for code, error in fetch_errors:
                    logger.warning("%s 分红数据下载失败: %s", code, error)
                failed += len(fetch_errors)

                saved_codes = set()
                if fetched:
                    saved = storage.save_dividend_batch_atomic(
                        fetched,
                        checkpoint_date=today,
                        provider=self.provider_name,
                    )
                    if saved:
                        saved_codes.update(fetched)
                    else:
                        # A malformed stock must not force the whole fetched batch
                        # to be downloaded again. Isolate it only on the error path.
                        for code, frame in fetched.items():
                            if storage.save_dividend_batch_atomic(
                                {code: frame},
                                checkpoint_date=today,
                                provider=self.provider_name,
                            ):
                                saved_codes.add(code)
                            else:
                                failed += 1
                                logger.warning("%s 分红数据写入失败", code)

                for code, _frame, error in results:
                    processed += 1
                    if error is not None:
                        state = "下载失败，可重试"
                    elif code not in saved_codes:
                        state = "写入失败，可重试"
                    else:
                        state = "已写入"
                    self._emit(
                        "dividend",
                        f"批量下载分红历史：{code} {state}",
                        processed,
                        total,
                    )

        if failed:
            self._emit("dividend", f"分红基线未完整完成，失败 {failed} 只", total - failed, total)
            return False
        if not storage.save_ingestion_commit(
            "dividend_incremental_checkpoint",
            "all",
            {
                "from_date": history_start,
                "through_date": today,
                "status": "ready",
                "stock_count": len(requested_codes) - lifecycle_skipped,
            },
            provider=self.provider_name,
        ):
            return False
        message = "分红历史基线更新完成"
        if lifecycle_skipped:
            message += f"（跳过 {lifecycle_skipped} 只与研究区间无交集的股票）"
        self._emit("dividend", message, total, total)
        return True

    def update_dividends_incremental(
        self,
        end_date: Optional[str] = None,
        sleep: float = _API_SLEEP,
    ) -> bool:
        """Append newly announced Tushare dividends after a completed baseline."""
        if self.provider_name != "tushare" or not hasattr(
            self.provider,
            "fetch_dividends_by_announcement",
        ):
            return True
        checkpoint = storage.get_ingestion_commit(
            "dividend_incremental_checkpoint",
            "all",
            provider=self.provider_name,
        )
        through_date = str((checkpoint or {}).get("through_date", ""))
        if not through_date:
            self._emit(
                "dividend",
                "分红基线尚未初始化；请先运行一次财务数据下载",
                1,
                1,
            )
            return True

        start = pd.Timestamp(through_date) + pd.Timedelta(days=1)
        end = pd.Timestamp(end_date or datetime.now().strftime("%Y-%m-%d"))
        dates = pd.date_range(start, end, freq="D") if start <= end else []
        merge_keys = ["ts_code", "end_date", "ann_date", "div_proc"]
        for index, current in enumerate(dates, 1):
            self._check_cancelled()
            ann_date = current.strftime("%Y-%m-%d")
            self._emit(
                "dividend",
                f"正在更新 {ann_date} 分红公告",
                index,
                len(dates),
            )
            frame = self.provider.fetch_dividends_by_announcement(ann_date)
            if not frame.empty:
                for code, group in frame.groupby("ts_code", sort=False):
                    if not storage.save_financial(
                        group.reset_index(drop=True),
                        "dividend",
                        str(code),
                        mode="merge",
                        merge_on=merge_keys,
                        provider=self.provider_name,
                    ):
                        return False
            if not storage.save_ingestion_commit(
                "dividend_incremental_checkpoint",
                "all",
                {"through_date": ann_date, "status": "ready"},
                provider=self.provider_name,
            ):
                return False
            time.sleep(sleep)
        return True

    @staticmethod
    def _all_quarter_periods(start_date: str = None) -> List[str]:
        start = start_date or get_data_start_date()
        now = datetime.now()
        periods = []
        for year in range(int(start[:4]), now.year + 1):
            definitions = (
                (3, 31, datetime(year, 4, 30)),
                (6, 30, datetime(year, 8, 31)),
                (9, 30, datetime(year, 10, 31)),
                (12, 31, datetime(year + 1, 4, 30)),
            )
            for month, day, disclosure_deadline in definitions:
                period = f"{year}-{month:02d}-{day:02d}"
                if period >= start and disclosure_deadline <= now:
                    periods.append(period)
        return periods

    def _find_missing_periods(self, periods: List[str]) -> List[str]:
        committed = set(
            storage.list_ingestion_commits(
                "financial_core_period",
                provider=self.provider_name,
            )
        )
        return [period for period in periods if period not in committed]

    def update_financials_by_period(self, start_date: str = None, sleep: float = _API_SLEEP) -> bool:
        if self.provider_name == "baostock":
            return self.update_financials(sleep=sleep, skip_existing=True)

        periods = self._find_missing_periods(self._all_quarter_periods(start_date))
        tables = [
            ("income", self.provider.fetch_income_by_period),
            ("balancesheet", self.provider.fetch_balancesheet_by_period),
            ("cashflow", self.provider.fetch_cashflow_by_period),
            ("fina_indicator", self.provider.fetch_fina_indicator_by_period),
        ]
        total = len(periods) * len(tables)
        current = 0
        for period in periods:
            frames: Dict[str, pd.DataFrame] = {}
            for sub, fetch in tables:
                self._check_cancelled()
                current += 1
                self._emit("financial", f"正在下载 {period} {sub}", current, total)
                frame = fetch(period)
                if frame.empty:
                    raise RuntimeError(f"{period} {sub} 返回空数据，不能标记完整")
                frames[sub] = frame
                time.sleep(sleep)
            self._check_cancelled()
            self._emit("financial_write", f"正在原子写入 {period} 财务截面", 1, 1)
            if not storage.save_financial_period_atomic(
                frames,
                period,
                provider=self.provider_name,
            ):
                raise RuntimeError(f"{period} 财务截面写入失败")
        self._emit("financial", "核心财报截面更新完成", total, total)
        return True

    def update_disclosure_date(self, end_date: Optional[str] = None) -> bool:
        periods = [end_date] if end_date else self._all_quarter_periods()
        existing = set(storage.list_financial_partitions("disclosure_date", self.provider_name))
        periods = [period for period in periods if period.replace("-", "") not in existing]
        for index, period in enumerate(periods, 1):
            self._check_cancelled()
            self._emit("disclosure", f"正在下载 {period} 披露日期", index, len(periods))
            frame = self.provider.fetch_disclosure_date(period)
            if frame.empty:
                return False
            if not storage.save_financial(
                frame,
                "disclosure_date",
                period.replace("-", ""),
                provider=self.provider_name,
            ):
                return False
        return True

    # ---------- Factors and workflows ----------

    def update_factors(
        self,
        start_date: str = None,
        end_date: str = None,
        strategy_dir: Path = None,
    ) -> bool:
        from .factor_store import compute_and_store_factors

        return compute_and_store_factors(start_date, end_date, strategy_dir)

    def update_ts_factors(self, ts_codes: List[str] = None, strategy_dir: Path = None) -> bool:
        from .factor_store import compute_and_store_ts_factors

        return compute_and_store_ts_factors(ts_codes, strategy_dir)

    def init_basic(self) -> bool:
        return self.update_stock_list() and self.update_trade_calendar()

    def init_market_data(self, start_date: str = None, ts_codes: Optional[List[str]] = None) -> bool:
        start = start_date or get_data_start_date()
        return (
            self.update_daily(start, ts_codes=ts_codes)
            and self.update_daily_indicator(start)
            and self.update_factors(start_date=start)
        )

    def daily_update(self, include_financials: bool = False) -> bool:
        results: Dict[str, bool] = {}

        def run_stage(name: str, function: Callable[[], bool]) -> bool:
            try:
                result = bool(function())
            except UpdateCancelled:
                raise
            except Exception as exc:
                logger.warning("增量更新阶段失败 %s: %s", name, exc)
                result = False
            results[name] = result
            return result

        # These stages have different outputs.  A partial market failure must
        # not prevent the independent financial stage from advancing.
        run_stage("stock_list", self.update_stock_list)
        run_stage("trade_calendar", self.update_trade_calendar)
        run_stage("market", self.update_daily)
        run_stage("indicator", self.update_daily_indicator)
        run_stage("factors", self.update_factors)
        if include_financials:
            initialized = bool(
                storage.list_financial_partitions("income", provider=self.provider_name)
            )
            if not initialized:
                self._emit(
                    "financial",
                    "财务基线尚未初始化，增量任务不会隐式启动全量财务下载",
                    1,
                    1,
                )
            elif self.provider_name == "tushare":
                run_stage("financial", self.update_financials_by_period)
                run_stage("dividend", self.update_dividends_incremental)
            else:
                run_stage("financial", lambda: self.update_financials(skip_existing=True))
        failed_stages = [name for name, result in results.items() if not result]
        if failed_stages:
            self._emit(
                "summary",
                f"增量更新部分阶段失败：{', '.join(failed_stages)}",
                len(results) - len(failed_stages),
                len(results),
            )
            return False
        return True

    def full_update(
        self,
        market_start: str = None,
        financial_codes: List[str] = None,
    ) -> bool:
        start = market_start or get_data_start_date()
        if not self.init_basic():
            return False
        if not self.update_daily(start) or not self.update_daily_indicator(start):
            return False
        if financial_codes:
            if not self.update_financials(financial_codes):
                return False
            if not self.update_ts_factors(financial_codes):
                return False
        elif self.provider_name == "tushare":
            if not self.update_financials_by_period(start):
                return False
            if not self.update_disclosure_date():
                return False
        elif not self.update_financials(skip_existing=False):
            return False
        return self.update_factors(start)


def _get_updater() -> DataUpdater:
    return DataUpdater()


def update_stock_list():
    return _get_updater().update_stock_list()


def update_trade_calendar(start_date="2000-01-01", end_date=None):
    return _get_updater().update_trade_calendar(start_date, end_date)


def update_daily(start_date=None, end_date=None):
    return _get_updater().update_daily(start_date, end_date)


def update_daily_indicator(start_date=None, end_date=None):
    return _get_updater().update_daily_indicator(start_date, end_date)


def update_financial_statements(ts_code: str, force: bool = False):
    return _get_updater()._update_one_stock_financials(ts_code, incremental=not force)


def update_dividend(ts_code: str):
    updater = _get_updater()
    frame = updater.provider.fetch_dividend(ts_code)
    if not frame.empty:
        storage.save_financial(
            frame,
            "dividend",
            ts_code,
            provider=updater.provider_name,
        )
    return True
