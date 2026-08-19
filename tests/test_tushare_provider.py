from unittest.mock import Mock

import pandas as pd

from src.data.tushare import provider as provider_module
from src.data.tushare.provider import TushareProvider, _align_indicator_to_quotes


def test_tushare_provider_does_not_persist_token_to_user_home(monkeypatch):
    api = Mock()
    set_token = Mock(side_effect=AssertionError("must not write tk.csv"))
    pro_api = Mock(return_value=api)
    monkeypatch.setattr(provider_module.ts, "set_token", set_token)
    monkeypatch.setattr(provider_module.ts, "pro_api", pro_api)

    provider = TushareProvider("secret")

    assert provider._pro is api
    pro_api.assert_called_once_with("secret")
    set_token.assert_not_called()


def test_tushare_daily_snapshot_collects_all_atomic_datasets():
    provider = TushareProvider.__new__(TushareProvider)
    provider._pro = Mock()
    provider._pro.daily.return_value = pd.DataFrame(
        [{"ts_code": "600000.SH", "trade_date": "20240102", "vol": 1000}]
    )
    provider._pro.adj_factor.return_value = pd.DataFrame(
        [{"ts_code": "600000.SH", "trade_date": "20240102", "adj_factor": 1.5}]
    )
    provider._pro.daily_basic.return_value = pd.DataFrame(
        [{"ts_code": "600000.SH", "trade_date": "20240102", "pe_ttm": 8.0}]
    )

    snapshot = provider.fetch_daily_snapshot("2024-01-02")

    assert set(snapshot) == {"raw", "adj_factor", "indicator"}
    assert snapshot["raw"].iloc[0]["trade_date"] == "2024-01-02"
    assert snapshot["raw"].iloc[0]["volume"] == 1000
    assert snapshot["adj_factor"].iloc[0]["adj_factor"] == 1.5
    assert snapshot["indicator"].iloc[0]["pe_ttm"] == 8.0
    expected = {"limit": 5000, "offset": 0, "trade_date": "20240102"}
    provider._pro.daily.assert_called_once_with(**expected)
    provider._pro.adj_factor.assert_called_once_with(**expected)
    provider._pro.daily_basic.assert_called_once_with(**expected)


def test_tushare_pagination_fetches_until_a_short_page():
    provider = TushareProvider.__new__(TushareProvider)
    provider._pro = Mock()
    provider._pro.daily.side_effect = [
        pd.DataFrame([{"ts_code": "A"}, {"ts_code": "B"}]),
        pd.DataFrame([{"ts_code": "C"}]),
    ]

    result = provider._fetch_paged("daily", page_size=2, trade_date="20240102")

    assert result["ts_code"].tolist() == ["A", "B", "C"]
    assert provider._pro.daily.call_args_list[0].kwargs["offset"] == 0
    assert provider._pro.daily.call_args_list[1].kwargs["offset"] == 2


def test_tushare_indicator_is_aligned_to_quote_universe():
    raw = pd.DataFrame(
        [
            {"ts_code": "600000.SH", "trade_date": "2024-01-02", "close": 10.0},
            {"ts_code": "000001.SZ", "trade_date": "2024-01-02", "close": 9.0},
        ]
    )
    indicator = pd.DataFrame(
        [
            {"ts_code": "600000.SH", "trade_date": "2024-01-02", "pe_ttm": 8.0},
            {"ts_code": "600001.SH", "trade_date": "2024-01-02", "pe_ttm": 9.0},
        ]
    )

    aligned = _align_indicator_to_quotes(raw, indicator)

    assert aligned["ts_code"].tolist() == ["600000.SH", "000001.SZ"]
    assert aligned.loc[aligned["ts_code"] == "600000.SH", "pe_ttm"].iloc[0] == 8.0
    assert pd.isna(aligned.loc[aligned["ts_code"] == "000001.SZ", "pe_ttm"].iloc[0])
    assert "600001.SH" not in set(aligned["ts_code"])
