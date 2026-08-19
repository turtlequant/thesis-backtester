import warnings
from unittest.mock import Mock

import pandas as pd

from src.data.baostock.provider import (
    BaoStockProvider,
    _concat_frames_preserving_columns,
    _to_bs_code,
    _to_ts_code,
)
from src.data.provider import (
    clear_provider_cache,
    get_provider,
    get_provider_capabilities,
    register,
)


def test_code_conversion_and_declared_boundaries():
    assert _to_bs_code("600000.SH") == "sh.600000"
    assert _to_ts_code("sz.000001") == "000001.SZ"
    capability = get_provider_capabilities("baostock")
    assert capability.supports_history is True
    assert capability.supports_instant_analysis is False
    assert "完整三大报表" in capability.limitations[0]


def test_provider_limitations_are_always_sequences():
    for provider_name in ("baostock", "tushare", "akshare"):
        capability = get_provider_capabilities(provider_name)
        assert isinstance(capability.limitations, tuple)


def test_provider_registry_reuses_and_closes_only_evicted_instance():
    class FakeProvider:
        def __init__(self, name):
            self.name = name
            self.close_count = 0

        def close(self):
            self.close_count += 1

    baostock = FakeProvider("baostock")
    tushare = FakeProvider("tushare")
    clear_provider_cache()
    try:
        register("baostock", baostock)
        register("tushare", tushare)

        assert get_provider("baostock") is baostock
        assert get_provider("baostock") is baostock

        clear_provider_cache("tushare")
        assert tushare.close_count == 1
        assert baostock.close_count == 0
        assert get_provider("baostock") is baostock
    finally:
        clear_provider_cache()

    assert baostock.close_count == 1


def test_financial_frame_concat_preserves_schema_without_future_warning():
    frames = [
        pd.DataFrame(
            {
                "code": ["sh.600000"],
                "metric": pd.Series([pd.NA], dtype="object"),
                "always_empty": pd.Series([pd.NA], dtype="object"),
            }
        ),
        pd.DataFrame(
            {
                "code": ["sh.600000"],
                "metric": [1.5],
                "always_empty": pd.Series([pd.NA], dtype="object"),
            }
        ),
    ]

    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        result = _concat_frames_preserving_columns(frames)

    assert result.columns.tolist() == ["code", "metric", "always_empty"]
    assert result["metric"].tolist()[1] == 1.5
    assert result["always_empty"].isna().all()


def test_financial_quarters_are_clipped_to_stock_lifetime():
    assert list(BaoStockProvider._quarters("2020-07-15", "2021-05-01")) == [
        (2020, 3),
        (2020, 4),
        (2021, 1),
    ]


def test_daily_bundle_normalizes_columns_and_expands_adjustment_factor():
    provider = BaoStockProvider.__new__(BaoStockProvider)
    provider._bs = Mock()
    history = pd.DataFrame(
        [
            {
                "date": "2024-01-02", "code": "sh.600000", "open": 10.0,
                "high": 11.0, "low": 9.5, "close": 10.5, "preclose": 10.0,
                "volume": 1000, "amount": 10000, "adjustflag": "3", "turn": 1.2,
                "tradestatus": "1", "pctChg": 5.0, "peTTM": 8.0, "pbMRQ": 1.0,
                "psTTM": 2.0, "pcfNcfTTM": 3.0, "isST": "0",
            },
            {
                "date": "2024-01-03", "code": "sh.600000", "open": 10.5,
                "high": 11.2, "low": 10.2, "close": 11.0, "preclose": 10.5,
                "volume": 1200, "amount": 13000, "adjustflag": "3", "turn": 1.3,
                "tradestatus": "1", "pctChg": 4.76, "peTTM": 8.2, "pbMRQ": 1.1,
                "psTTM": 2.1, "pcfNcfTTM": 3.1, "isST": "0",
            },
        ]
    )
    factors = pd.DataFrame(
        [{"code": "sh.600000", "dividOperateDate": "2024-01-02", "adjustFactor": 1.5}]
    )
    provider._collect = Mock(side_effect=[history, factors])

    bundle = provider.fetch_daily_bundle("600000.SH", "2024-01-02", "2024-01-03")

    assert bundle["raw"]["ts_code"].unique().tolist() == ["600000.SH"]
    assert bundle["indicator"]["pe_ttm"].tolist() == [8.0, 8.2]
    assert bundle["adj_factor"]["adj_factor"].tolist() == [1.5, 1.5]


def test_daily_snapshot_normalizes_full_market_and_factor_data():
    provider = BaoStockProvider.__new__(BaoStockProvider)
    provider._bs = Mock()
    history = pd.DataFrame(
        [
            {
                "date": "2024-01-02", "code": "sh.600000", "open": 10.0,
                "high": 11.0, "low": 9.5, "close": 10.5, "preclose": 10.0,
                "volume": 1000, "amount": 10000, "adjustflag": "3", "turn": 1.2,
                "tradestatus": "1", "pctChg": 5.0, "peTTM": 8.0, "pbMRQ": 1.0,
                "psTTM": 2.0, "pcfNcfTTM": 3.0, "isST": "0",
            },
            {
                "date": "2024-01-02", "code": "sz.000001", "open": 9.0,
                "high": 9.5, "low": 8.8, "close": 9.2, "preclose": 9.0,
                "volume": 2000, "amount": 18000, "adjustflag": "3", "turn": 2.2,
                "tradestatus": "1", "pctChg": 2.2, "peTTM": 7.0, "pbMRQ": 0.9,
                "psTTM": 1.8, "pcfNcfTTM": 2.8, "isST": "0",
            },
        ]
    )
    factors = pd.DataFrame(
        [
            {"code": "sh.600000", "adjustFactor": 1.5},
            {"code": "sz.000001", "adjustFactor": 2.0},
        ]
    )
    provider._collect = Mock(side_effect=[history, factors])

    snapshot = provider.fetch_daily_snapshot("2024-01-02")

    assert snapshot["raw"]["ts_code"].tolist() == ["600000.SH", "000001.SZ"]
    assert snapshot["raw"]["trade_date"].unique().tolist() == ["2024-01-02"]
    assert snapshot["indicator"]["pe_ttm"].tolist() == [8.0, 7.0]
    assert snapshot["adj_factor"]["adj_factor"].tolist() == [1.5, 2.0]
