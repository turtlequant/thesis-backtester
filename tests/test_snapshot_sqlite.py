import pandas as pd

from src.data import api, config, storage
from src.data.snapshot import create_snapshot


def test_snapshot_reads_one_provider_sqlite_with_announcement_cutoff(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_CONFIG_PATH", tmp_path / "data_config.json")
    monkeypatch.setattr(
        storage,
        "get_provider_db_path",
        lambda provider: tmp_path / provider / "market.db",
    )
    for key in ("DATA_PROVIDER", "TUSHARE_TOKEN", "DATA_START_DATE"):
        monkeypatch.delenv(key, raising=False)
    api.clear_basic_caches()
    storage.save(
        pd.DataFrame(
            [
                {
                    "ts_code": "600000.SH",
                    "name": "浦发银行",
                    "industry": "银行",
                    "area": "上海",
                    "list_status": "L",
                    "list_date": "1999-11-10",
                }
            ]
        ),
        "basic",
        "",
        "stock_list",
        provider="baostock",
    )
    storage.save(
        pd.DataFrame(
            [
                {
                    "ts_code": "600000.SH",
                    "trade_date": "2024-06-28",
                    "open": 8.0,
                    "high": 8.2,
                    "low": 7.9,
                    "close": 8.1,
                    "volume": 1000,
                    "amount": 8100,
                }
            ]
        ),
        "daily",
        "raw",
        "2024-06",
        provider="baostock",
    )
    storage.save(
        pd.DataFrame(
            [
                {
                    "ts_code": "600000.SH",
                    "trade_date": "2024-06-28",
                    "pe_ttm": 6.0,
                    "pb": 0.6,
                }
            ]
        ),
        "daily",
        "indicator",
        "2024-06",
        provider="baostock",
    )

    visible = pd.DataFrame(
        [
            {
                "ts_code": "600000.SH",
                "ann_date": "2024-04-30",
                "end_date": "2023-12-31",
                "report_type": "1",
                "roe": 10.0,
            },
            {
                "ts_code": "600000.SH",
                "ann_date": "2024-08-30",
                "end_date": "2024-06-30",
                "report_type": "1",
                "roe": 11.0,
            },
        ]
    )
    for sub in ("balancesheet", "income", "cashflow", "fina_indicator"):
        storage.save_financial(visible, sub, "600000.SH", provider="baostock")

    snapshot = create_snapshot("600000.SH", "2024-06-30", price_lookback_days=30)

    assert snapshot.stock_name == "浦发银行"
    assert snapshot.price_history["trade_date"].tolist() == ["2024-06-28"]
    assert snapshot.income["end_date"].tolist() == ["2023-12-31"]
    assert snapshot.latest_report_period == "2023-12-31"
    api.clear_basic_caches()
