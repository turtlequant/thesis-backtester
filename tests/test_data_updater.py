import threading
from unittest.mock import Mock

import pandas as pd
import pytest

from src.data import updater as updater_module
from src.data.updater import DataUpdater, NoDataAvailable


class _BaoStockLikeProvider:
    name = "baostock"

    def fetch_daily_bundle(self, ts_code, start_date, end_date):
        raise AssertionError("test should replace the updater download method")

    def fetch_daily_snapshot(self, trade_date):
        raise AssertionError("test should replace the updater download method")


class _TushareLikeProvider:
    name = "tushare"

    def fetch_daily_snapshot(self, trade_date):
        raise AssertionError("test should replace the provider snapshot method")


def _updater():
    instance = DataUpdater.__new__(DataUpdater)
    instance.provider = _BaoStockLikeProvider()
    instance.provider_name = "baostock"
    instance.progress = None
    instance.cancel_event = None
    return instance


def test_baostock_incremental_resumes_missing_baseline_stocks(monkeypatch):
    instance = _updater()
    monkeypatch.setattr(instance, "_stock_codes", Mock(return_value=["000001.SZ", "600000.SH"]))
    monkeypatch.setattr(
        updater_module.storage,
        "list_distinct_values",
        Mock(return_value=["000001.SZ"]),
    )
    history_update = Mock(return_value=True)
    monkeypatch.setattr(instance, "_update_baostock_daily", history_update)
    monkeypatch.setattr(instance, "_get_date_ranges", Mock(return_value=[]))
    monkeypatch.setattr(updater_module.storage, "get_latest_date", Mock(return_value=None))

    assert instance.update_daily() is True
    assert history_update.call_args.args[1] == ["600000.SH"]


def test_baostock_complete_baseline_uses_daily_market_snapshot(monkeypatch):
    instance = _updater()
    codes = ["000001.SZ", "600000.SH"]
    monkeypatch.setattr(instance, "_stock_codes", Mock(return_value=codes))
    monkeypatch.setattr(
        updater_module.storage,
        "list_distinct_values",
        Mock(return_value=codes),
    )
    monkeypatch.setattr(
        instance,
        "_get_date_ranges",
        Mock(return_value=[("2024-01-03", "2024-01-03")]),
    )
    monkeypatch.setattr(
        updater_module.storage,
        "get_latest_date",
        Mock(return_value="2024-01-02"),
    )
    snapshot_update = Mock(return_value=True)
    monkeypatch.setattr(instance, "_update_bulk_daily", snapshot_update)

    assert instance.update_daily() is True
    snapshot_update.assert_called_once_with([("2024-01-03", "2024-01-03")])


def test_baostock_indicator_does_not_repeat_explicit_history_download(monkeypatch):
    instance = _updater()
    repeated = Mock()
    monkeypatch.setattr(instance, "update_daily", repeated)

    assert instance.update_daily_indicator("2024-01-01", "2024-01-31") is True
    repeated.assert_not_called()


def test_tushare_indicator_does_not_repeat_atomic_snapshot_download():
    instance = DataUpdater.__new__(DataUpdater)
    instance.provider = _TushareLikeProvider()
    instance.provider_name = "tushare"
    instance.progress = None
    instance.cancel_event = None

    assert instance.update_daily_indicator("2024-01-01", "2024-01-31") is True


def test_download_stock_universe_keeps_delisted_stocks(monkeypatch):
    instance = _updater()
    stock_list = pd.DataFrame(
        [
            {"ts_code": "600000.SH", "list_status": "L"},
            {"ts_code": "600001.SH", "list_status": "D"},
        ]
    )
    monkeypatch.setattr(updater_module.storage, "load_one", Mock(return_value=stock_list))

    assert instance._stock_codes() == ["600000.SH", "600001.SH"]


def test_baostock_skips_delisted_stock_before_configured_history(monkeypatch):
    instance = _updater()
    stock_list = pd.DataFrame(
        [
            {
                "ts_code": "600840.SH",
                "list_status": "D",
                "list_date": "1994-03-11",
                "delist_date": "2009-08-27",
            }
        ]
    )
    monkeypatch.setattr(updater_module.storage, "load_one", Mock(return_value=stock_list))
    fetch = Mock()
    instance.provider.fetch_daily_bundle = fetch

    assert instance._update_baostock_daily(
        [("2015-01-01", "2026-08-17")], ["600840.SH"]
    ) is True
    fetch.assert_not_called()


def test_baostock_empty_delisted_history_is_a_terminal_soft_skip(monkeypatch):
    instance = _updater()
    stock_list = pd.DataFrame(
        [
            {
                "ts_code": "600001.SH",
                "list_status": "D",
                "list_date": "2010-01-01",
                "delist_date": "2016-06-30",
            }
        ]
    )
    monkeypatch.setattr(updater_module.storage, "load_one", Mock(return_value=stock_list))
    instance.provider.fetch_daily_bundle = Mock(
        return_value={
            "raw": pd.DataFrame(),
            "adj_factor": pd.DataFrame(),
            "indicator": pd.DataFrame(),
        }
    )
    checkpoint = Mock(return_value=True)
    monkeypatch.setattr(updater_module.storage, "save_ingestion_commit", checkpoint)

    assert instance._update_baostock_daily(
        [("2015-01-01", "2026-08-17")], ["600001.SH"]
    ) is True
    checkpoint.assert_called_once()
    assert checkpoint.call_args.args[2]["terminal"] is True


def test_terminal_empty_checkpoint_is_not_retried_on_baseline_resume(monkeypatch):
    instance = _updater()
    code = "600001.SH"
    monkeypatch.setattr(instance, "_stock_codes", Mock(return_value=[code]))
    monkeypatch.setattr(instance, "_stock_codes_in_range", Mock(return_value=[code]))
    monkeypatch.setattr(
        updater_module.storage,
        "list_distinct_values",
        Mock(return_value=[]),
    )
    monkeypatch.setattr(
        updater_module.storage,
        "list_ingestion_commits",
        Mock(return_value=[code]),
    )
    monkeypatch.setattr(
        updater_module.storage,
        "get_ingestion_commit",
        Mock(
            return_value={
                "from_date": "2015-01-01",
                "through_date": "2016-06-30",
                "status": "no_data",
                "terminal": True,
            }
        ),
    )
    history_update = Mock(return_value=True)
    monkeypatch.setattr(instance, "_update_baostock_daily", history_update)
    monkeypatch.setattr(instance, "_get_date_ranges", Mock(return_value=[]))
    monkeypatch.setattr(updater_module.storage, "get_latest_date", Mock(return_value=None))

    assert instance.update_daily() is True
    history_update.assert_not_called()


def test_terminal_checkpoint_is_rechecked_when_history_moves_earlier(monkeypatch):
    instance = _updater()
    code = "600001.SH"
    monkeypatch.setattr(updater_module, "get_data_start_date", Mock(return_value="2015-01-01"))
    monkeypatch.setattr(instance, "_stock_codes", Mock(return_value=[code]))
    monkeypatch.setattr(instance, "_stock_codes_in_range", Mock(return_value=[code]))
    monkeypatch.setattr(updater_module.storage, "list_distinct_values", Mock(return_value=[]))
    monkeypatch.setattr(
        updater_module.storage,
        "list_ingestion_commits",
        Mock(return_value=[code]),
    )
    monkeypatch.setattr(
        updater_module.storage,
        "get_ingestion_commit",
        Mock(
            return_value={
                "from_date": "2016-01-01",
                "through_date": "2016-06-30",
                "status": "no_data",
                "terminal": True,
            }
        ),
    )
    history_update = Mock(return_value=True)
    monkeypatch.setattr(instance, "_update_baostock_daily", history_update)
    monkeypatch.setattr(instance, "_get_date_ranges", Mock(return_value=[]))
    monkeypatch.setattr(updater_module.storage, "get_latest_date", Mock(return_value=None))

    assert instance.update_daily() is True
    history_update.assert_called_once()


def test_baostock_empty_active_history_remains_a_hard_failure(monkeypatch):
    instance = _updater()
    stock_list = pd.DataFrame(
        [
            {
                "ts_code": "600000.SH",
                "list_status": "L",
                "list_date": "1999-01-01",
                "delist_date": "",
            }
        ]
    )
    monkeypatch.setattr(updater_module.storage, "load_one", Mock(return_value=stock_list))
    instance.provider.fetch_daily_bundle = Mock(
        return_value={
            "raw": pd.DataFrame(),
            "adj_factor": pd.DataFrame(),
            "indicator": pd.DataFrame(),
        }
    )

    assert instance._update_baostock_daily(
        [("2015-01-01", "2026-08-17")], ["600000.SH"]
    ) is False


def test_tushare_daily_update_routes_financials_by_period(monkeypatch):
    instance = DataUpdater.__new__(DataUpdater)
    instance.provider = _TushareLikeProvider()
    instance.provider_name = "tushare"
    instance.progress = None
    instance.cancel_event = None
    for name in (
        "update_stock_list",
        "update_trade_calendar",
        "update_daily",
        "update_daily_indicator",
        "update_factors",
    ):
        monkeypatch.setattr(instance, name, Mock(return_value=True))
    by_period = Mock(return_value=True)
    by_stock = Mock(return_value=True)
    monkeypatch.setattr(instance, "update_financials_by_period", by_period)
    monkeypatch.setattr(instance, "update_financials", by_stock)
    monkeypatch.setattr(
        updater_module.storage,
        "list_financial_partitions",
        Mock(return_value=["600000.SH"]),
    )

    assert instance.daily_update(include_financials=True) is True
    by_period.assert_called_once_with()
    by_stock.assert_not_called()


def test_tushare_dividend_baseline_is_resumable(monkeypatch):
    instance = DataUpdater.__new__(DataUpdater)
    instance.provider = _TushareLikeProvider()
    instance.provider_name = "tushare"
    instance.progress = None
    instance.cancel_event = None
    dividend = pd.DataFrame(
        [
            {
                "ts_code": "600000.SH",
                "end_date": "2023-12-31",
                "ann_date": "2024-03-20",
                "cash_div": 0.3,
            }
        ]
    )
    fetch = Mock(return_value=dividend)
    instance.provider.fetch_dividend = fetch
    monkeypatch.setattr(instance, "_stock_codes", Mock(return_value=["000001.SZ", "600000.SH"]))
    monkeypatch.setattr(
        instance,
        "_stock_codes_in_range",
        Mock(return_value=["000001.SZ", "600000.SH"]),
    )
    monkeypatch.setattr(
        updater_module.storage,
        "list_financial_partitions",
        Mock(return_value=["000001.SZ"]),
    )
    monkeypatch.setattr(
        updater_module.storage,
        "list_ingestion_commits",
        Mock(return_value=[]),
    )
    save_batch = Mock(return_value=True)
    checkpoint = Mock(return_value=True)
    monkeypatch.setattr(updater_module.storage, "save_dividend_batch_atomic", save_batch)
    monkeypatch.setattr(updater_module.storage, "save_ingestion_commit", checkpoint)
    monkeypatch.setattr(updater_module.time, "sleep", Mock())

    assert instance.update_dividends(skip_existing=True) is True
    fetch.assert_called_once_with("600000.SH")
    assert list(save_batch.call_args.args[0]) == ["600000.SH"]
    assert save_batch.call_args.kwargs["provider"] == "tushare"
    assert checkpoint.call_args.args[:2] == (
        "dividend_incremental_checkpoint",
        "all",
    )


def test_tushare_dividend_baseline_fetches_concurrently(monkeypatch):
    instance = DataUpdater.__new__(DataUpdater)
    instance.provider = _TushareLikeProvider()
    instance.provider_name = "tushare"
    instance.progress = None
    instance.cancel_event = None
    codes = [f"00000{index}.SZ" for index in range(4)]
    barrier = threading.Barrier(2)

    def fetch(code):
        barrier.wait(timeout=2)
        return pd.DataFrame([{"ts_code": code, "ann_date": "2024-03-20"}])

    instance.provider.fetch_dividend = fetch
    monkeypatch.setattr(instance, "_stock_codes", Mock(return_value=codes))
    monkeypatch.setattr(instance, "_stock_codes_in_range", Mock(return_value=codes))
    monkeypatch.setattr(
        updater_module.storage,
        "list_financial_partitions",
        Mock(return_value=[]),
    )
    monkeypatch.setattr(
        updater_module.storage,
        "list_ingestion_commits",
        Mock(return_value=[]),
    )
    save_batch = Mock(return_value=True)
    monkeypatch.setattr(updater_module.storage, "save_dividend_batch_atomic", save_batch)
    monkeypatch.setattr(
        updater_module.storage,
        "save_ingestion_commit",
        Mock(return_value=True),
    )

    assert instance.update_dividends(fetch_workers=2, batch_size=4) is True
    assert set(save_batch.call_args.args[0]) == set(codes)


def test_tushare_dividend_incremental_merges_by_stock(monkeypatch):
    instance = DataUpdater.__new__(DataUpdater)
    instance.provider = _TushareLikeProvider()
    instance.provider_name = "tushare"
    instance.progress = None
    instance.cancel_event = None
    fetch = Mock(
        return_value=pd.DataFrame(
            [
                {
                    "ts_code": "600000.SH",
                    "end_date": "2023-12-31",
                    "ann_date": "2024-01-03",
                    "div_proc": "预案",
                    "cash_div": 0.3,
                }
            ]
        )
    )
    instance.provider.fetch_dividends_by_announcement = fetch
    monkeypatch.setattr(
        updater_module.storage,
        "get_ingestion_commit",
        Mock(return_value={"through_date": "2024-01-02"}),
    )
    save = Mock(return_value=True)
    checkpoint = Mock(return_value=True)
    monkeypatch.setattr(updater_module.storage, "save_financial", save)
    monkeypatch.setattr(updater_module.storage, "save_ingestion_commit", checkpoint)
    monkeypatch.setattr(updater_module.time, "sleep", Mock())

    assert instance.update_dividends_incremental(end_date="2024-01-03") is True
    fetch.assert_called_once_with("2024-01-03")
    assert save.call_args.args[1:3] == ("dividend", "600000.SH")
    assert save.call_args.kwargs["mode"] == "merge"
    assert checkpoint.call_args.args[2]["through_date"] == "2024-01-03"


def test_incremental_does_not_implicitly_bootstrap_all_financials(monkeypatch):
    instance = DataUpdater.__new__(DataUpdater)
    instance.provider = _TushareLikeProvider()
    instance.provider_name = "tushare"
    instance.progress = None
    instance.cancel_event = None
    for name in (
        "update_stock_list",
        "update_trade_calendar",
        "update_daily",
        "update_daily_indicator",
        "update_factors",
    ):
        monkeypatch.setattr(instance, name, Mock(return_value=True))
    by_period = Mock(return_value=True)
    monkeypatch.setattr(instance, "update_financials_by_period", by_period)
    monkeypatch.setattr(
        updater_module.storage,
        "list_financial_partitions",
        Mock(return_value=[]),
    )

    assert instance.daily_update(include_financials=True) is True
    by_period.assert_not_called()


def test_incremental_financial_stage_runs_after_market_failure(monkeypatch):
    instance = _updater()
    monkeypatch.setattr(instance, "update_stock_list", Mock(return_value=True))
    monkeypatch.setattr(instance, "update_trade_calendar", Mock(return_value=True))
    monkeypatch.setattr(instance, "update_daily", Mock(return_value=False))
    monkeypatch.setattr(instance, "update_daily_indicator", Mock(return_value=True))
    monkeypatch.setattr(instance, "update_factors", Mock(return_value=True))
    financials = Mock(return_value=True)
    monkeypatch.setattr(instance, "update_financials", financials)
    monkeypatch.setattr(
        updater_module.storage,
        "list_financial_partitions",
        Mock(return_value=["600000.SH"]),
    )

    assert instance.daily_update(include_financials=True) is False
    financials.assert_called_once_with(skip_existing=True)


def test_empty_delisted_financials_are_a_terminal_soft_skip(monkeypatch):
    instance = _updater()
    code = "600001.SH"
    monkeypatch.setattr(instance, "_stock_codes", Mock(return_value=[code]))
    monkeypatch.setattr(
        instance,
        "_stock_download_tasks",
        Mock(return_value=([(code, "2015-01-01", "2016-06-30", "D")], 0)),
    )
    monkeypatch.setattr(
        instance,
        "_update_one_stock_financials",
        Mock(side_effect=NoDataAvailable("empty")),
    )
    checkpoint = Mock(return_value=True)
    monkeypatch.setattr(updater_module.storage, "save_ingestion_commit", checkpoint)

    assert instance.update_financials(skip_existing=False) is True
    checkpoint.assert_called_once()
    assert checkpoint.call_args.args[:2] == ("financial_stock_checkpoint", code)
    assert checkpoint.call_args.args[2]["terminal"] is True


def test_delisted_financial_download_is_clipped_and_terminal(monkeypatch):
    instance = _updater()
    code = "600001.SH"
    instance.provider.fetch_financial_bundle = Mock(
        return_value={
            "income": pd.DataFrame(
                [{"ts_code": code, "end_date": "2016-03-31", "revenue": 1.0}]
            )
        }
    )
    monkeypatch.setattr(
        updater_module.storage,
        "load",
        Mock(
            return_value=pd.DataFrame(
                [
                    {
                        "ts_code": code,
                        "list_date": "2015-06-01",
                        "delist_date": "2016-06-30",
                        "list_status": "D",
                    }
                ]
            )
        ),
    )
    save = Mock(return_value=True)
    monkeypatch.setattr(
        updater_module.storage,
        "save_financial_bundle_atomic",
        save,
    )

    instance._update_one_stock_financials(code)

    instance.provider.fetch_financial_bundle.assert_called_once_with(
        code,
        start_date="2015-06-01",
        end_date="2016-06-30",
    )
    assert save.call_args.kwargs["checkpoint_from_date"] == "2015-06-01"
    assert save.call_args.kwargs["checkpoint_terminal"] is True


def test_terminal_delisted_financial_checkpoint_is_not_retried(monkeypatch):
    instance = _updater()
    code = "600001.SH"
    monkeypatch.setattr(
        updater_module.storage,
        "get_ingestion_commit",
        Mock(
            return_value={
                "from_date": "2015-01-01",
                "through_date": "2016-06-30",
                "terminal": True,
            }
        ),
    )

    needed, fresh = instance._classify_stocks_for_update([code])

    assert needed == []
    assert fresh == 1


def test_daily_snapshot_commit_marker_skips_an_already_committed_date(monkeypatch):
    instance = _updater()
    monkeypatch.setattr(
        instance,
        "_trade_dates",
        Mock(return_value=["2024-01-02", "2024-01-03"]),
    )
    monkeypatch.setattr(
        updater_module.storage,
        "list_daily_snapshot_commits",
        Mock(return_value=["2024-01-02", "2024-01-03"]),
    )
    fetch = Mock()
    instance.provider.fetch_daily_snapshot = fetch

    assert instance._update_bulk_daily([("2024-01-02", "2024-01-03")]) is True
    fetch.assert_not_called()


def test_empty_current_day_snapshot_is_pending_not_failed(monkeypatch):
    instance = _updater()
    today = updater_module.datetime.now().strftime("%Y-%m-%d")
    monkeypatch.setattr(instance, "_trade_dates", Mock(return_value=[today]))
    monkeypatch.setattr(
        updater_module.storage,
        "list_daily_snapshot_commits",
        Mock(return_value=[]),
    )
    instance.provider.fetch_daily_snapshot = Mock(
        return_value={
            "raw": pd.DataFrame(),
            "adj_factor": pd.DataFrame(),
            "indicator": pd.DataFrame(),
        }
    )
    save = Mock()
    monkeypatch.setattr(updater_module.storage, "save_daily_frames_atomic", save)
    events = []
    instance.progress = events.append

    assert instance._update_bulk_daily([(today, today)]) is True
    save.assert_not_called()
    assert "数据待发布" in events[-1]["message"]


def test_empty_historical_snapshot_remains_a_hard_failure(monkeypatch):
    instance = _updater()
    trade_date = "2024-01-02"
    monkeypatch.setattr(instance, "_trade_dates", Mock(return_value=[trade_date]))
    monkeypatch.setattr(
        updater_module.storage,
        "list_daily_snapshot_commits",
        Mock(return_value=[]),
    )
    instance.provider.fetch_daily_snapshot = Mock(
        return_value={
            "raw": pd.DataFrame(),
            "adj_factor": pd.DataFrame(),
            "indicator": pd.DataFrame(),
        }
    )

    with pytest.raises(RuntimeError, match="全市场快照不完整"):
        instance._update_bulk_daily([(trade_date, trade_date)])
