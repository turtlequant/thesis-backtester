import pandas as pd

from src.data import storage


def _isolate_databases(tmp_path, monkeypatch):
    monkeypatch.setattr(
        storage,
        "get_provider_db_path",
        lambda provider: tmp_path / provider / "market.db",
    )


def _daily_frames(close=10.0):
    keys = {"ts_code": "600000.SH", "trade_date": "2024-01-02"}
    return {
        "raw": pd.DataFrame([{**keys, "close": close}]),
        "adj_factor": pd.DataFrame([{**keys, "adj_factor": 1.5}]),
        "indicator": pd.DataFrame([{**keys, "pe_ttm": 8.0}]),
    }


def _financial_frames(period="2024-03-31"):
    base = {
        "ts_code": "600000.SH",
        "end_date": period,
        "ann_date": "2024-04-20",
        "report_type": "1",
    }
    return {
        "income": pd.DataFrame([{**base, "revenue": 100.0}]),
        "balancesheet": pd.DataFrame([{**base, "total_assets": 200.0}]),
        "cashflow": pd.DataFrame([{**base, "n_cashflow_act": 30.0}]),
        "fina_indicator": pd.DataFrame([{**base, "roe": 8.0}]),
    }


def test_sqlite_merge_filter_and_status(tmp_path, monkeypatch):
    _isolate_databases(tmp_path, monkeypatch)
    initial = pd.DataFrame(
        [
            {"ts_code": "600000.SH", "trade_date": "2024-01-02", "close": 10.0},
            {"ts_code": "000001.SZ", "trade_date": "2024-01-02", "close": 9.0},
        ]
    )
    assert storage.save(
        initial,
        "daily",
        "raw",
        "2024-01",
        mode="merge",
        merge_on=["ts_code", "trade_date"],
        provider="baostock",
    )

    changed = pd.DataFrame(
        [
            {"ts_code": "600000.SH", "trade_date": "2024-01-02", "close": 11.0},
            {"ts_code": "600000.SH", "trade_date": "2024-01-03", "close": 11.5},
        ]
    )
    assert storage.save(
        changed,
        "daily",
        "raw",
        "2024-01",
        mode="merge",
        merge_on=["ts_code", "trade_date"],
        provider="baostock",
    )

    loaded = storage.load(
        "daily",
        "raw",
        ["2024-01"],
        filters=[("ts_code", "==", "600000.SH")],
        provider="baostock",
    ).sort_values("trade_date")
    assert loaded["close"].tolist() == [11.0, 11.5]

    status = storage.get_database_status("baostock")
    assert status["exists"] is True
    assert status["datasets"][0]["row_count"] == 3
    assert status["datasets"][0]["latest_date"] == "2024-01-03"
    assert storage.list_distinct_values(
        "daily", "raw", "ts_code", provider="baostock"
    ) == ["000001.SZ", "600000.SH"]


def test_hfq_window_loader_merges_overlaps_and_joins_inside_sqlite(
    tmp_path,
    monkeypatch,
):
    _isolate_databases(tmp_path, monkeypatch)
    raw = pd.DataFrame(
        [
            {"ts_code": "600000.SH", "trade_date": "2024-01-02", "close": 10.0},
            {"ts_code": "600000.SH", "trade_date": "2024-01-03", "close": 6.0},
            {"ts_code": "000001.SZ", "trade_date": "2024-01-03", "close": 20.0},
        ]
    )
    factors = pd.DataFrame(
        [
            {"ts_code": "600000.SH", "trade_date": "2024-01-02", "adj_factor": 1.0},
            {"ts_code": "600000.SH", "trade_date": "2024-01-03", "adj_factor": 2.0},
            {"ts_code": "000001.SZ", "trade_date": "2024-01-03", "adj_factor": 1.5},
        ]
    )
    assert storage.save(
        raw,
        "daily",
        "raw",
        "2024-01",
        mode="merge",
        merge_on=["ts_code", "trade_date"],
        provider="baostock",
    )
    assert storage.save(
        factors,
        "daily",
        "adj_factor",
        "2024-01",
        mode="merge",
        merge_on=["ts_code", "trade_date"],
        provider="baostock",
    )

    result = storage.load_hfq_close_windows(
        [
            ("600000.SH", "2024-01-01", "2024-01-02"),
            ("600000.SH", "2024-01-02", "2024-01-03"),
            ("000001.SZ", "2024-01-03", "2024-01-03"),
        ],
        provider="baostock",
    )

    assert len(result) == 3
    assert result[result["ts_code"] == "600000.SH"]["close"].tolist() == [10.0, 12.0]
    assert result[result["ts_code"] == "000001.SZ"]["close"].tolist() == [30.0]


def test_sqlite_upsert_preserves_columns_not_present_in_increment(monkeypatch, tmp_path):
    _isolate_databases(tmp_path, monkeypatch)
    keys = {"ts_code": "600000.SH", "trade_date": "2024-01-02"}
    assert storage.save(
        pd.DataFrame([{**keys, "bp": 0.1, "custom_factor": 2.0}]),
        "daily",
        "factors",
        "2024-01",
        mode="merge",
        merge_on=["ts_code", "trade_date"],
        provider="baostock",
    )
    assert storage.save(
        pd.DataFrame([{**keys, "bp": 0.2}]),
        "daily",
        "factors",
        "2024-01",
        mode="merge",
        merge_on=["ts_code", "trade_date"],
        provider="baostock",
    )

    loaded = storage.load_one(
        "daily", "factors", "2024-01", provider="baostock"
    )
    assert len(loaded) == 1
    assert loaded.iloc[0]["bp"] == 0.2
    assert loaded.iloc[0]["custom_factor"] == 2.0
    assert storage.get_database_status("baostock")["datasets"][0]["row_count"] == 1


def test_provider_databases_are_physically_isolated(tmp_path, monkeypatch):
    _isolate_databases(tmp_path, monkeypatch)
    frame = pd.DataFrame(
        [{"ts_code": "600000.SH", "end_date": "2024-12-31", "roe": 10.0}]
    )
    storage.save_financial(frame, "fina_indicator", "600000.SH", provider="baostock")

    assert not storage.load_financial(
        "fina_indicator",
        ["600000.SH"],
        provider="baostock",
    ).empty
    assert storage.load_financial(
        "fina_indicator",
        ["600000.SH"],
        provider="tushare",
    ).empty
    assert storage.get_database_path("baostock") != storage.get_database_path("tushare")


def test_daily_snapshot_commits_three_tables_and_marker_atomically(tmp_path, monkeypatch):
    _isolate_databases(tmp_path, monkeypatch)

    assert storage.save_daily_frames_atomic(
        _daily_frames(),
        "2024-01",
        provider="baostock",
        commit_date="2024-01-02",
    )
    assert storage.list_daily_snapshot_commits(provider="baostock") == ["2024-01-02"]

    for sub in ("raw", "adj_factor", "indicator"):
        loaded = storage.load("daily", sub, ["2024-01"], provider="baostock")
        assert len(loaded) == 1

    # The database-level unique key plus merge semantics replaces the row.
    assert storage.save_daily_frames_atomic(
        _daily_frames(close=11.0),
        "2024-01",
        provider="baostock",
        commit_date="2024-01-02",
    )
    raw = storage.load("daily", "raw", ["2024-01"], provider="baostock")
    assert len(raw) == 1
    assert raw.iloc[0]["close"] == 11.0
    with storage.connect("baostock") as connection:
        indexes = connection.execute("PRAGMA index_list(dataset_daily_raw)").fetchall()
    assert any(str(row[1]).startswith("uidx_") and int(row[2]) == 1 for row in indexes)


def test_daily_snapshot_failure_rolls_back_every_table_and_marker(tmp_path, monkeypatch):
    _isolate_databases(tmp_path, monkeypatch)
    original = storage._save_frame

    def fail_on_factor(connection, df, category, sub, partition, mode="overwrite", merge_on=None):
        if sub == "adj_factor":
            raise RuntimeError("injected write failure")
        return original(connection, df, category, sub, partition, mode, merge_on)

    monkeypatch.setattr(storage, "_save_frame", fail_on_factor)

    assert not storage.save_daily_frames_atomic(
        _daily_frames(),
        "2024-01",
        provider="baostock",
        commit_date="2024-01-02",
    )
    assert storage.load("daily", "raw", ["2024-01"], provider="baostock").empty
    assert storage.load("daily", "adj_factor", ["2024-01"], provider="baostock").empty
    assert storage.load("daily", "indicator", ["2024-01"], provider="baostock").empty
    assert storage.list_daily_snapshot_commits(provider="baostock") == []


def test_financial_period_stream_commit_is_atomic_and_resumable(tmp_path, monkeypatch):
    _isolate_databases(tmp_path, monkeypatch)
    frames = _financial_frames()

    assert storage.save_financial_period_atomic(
        frames,
        "2024-03-31",
        provider="tushare",
    )
    assert storage.list_ingestion_commits(
        "financial_core_period", provider="tushare"
    ) == ["2024-03-31"]
    income = storage.load_financial("income", ["600000.SH"], provider="tushare")
    assert income.iloc[0]["revenue"] == 100.0

    original = storage._save_partitioned_frame

    def fail_on_cashflow(connection, frame, category, sub, partition_column, merge_on):
        if sub == "cashflow":
            raise RuntimeError("injected financial failure")
        return original(connection, frame, category, sub, partition_column, merge_on)

    monkeypatch.setattr(storage, "_save_partitioned_frame", fail_on_cashflow)
    assert not storage.save_financial_period_atomic(
        _financial_frames("2024-06-30"),
        "2024-06-30",
        provider="tushare",
    )
    assert "2024-06-30" not in storage.list_ingestion_commits(
        "financial_core_period", provider="tushare"
    )


def test_stock_financial_checkpoint_commits_with_bundle(tmp_path, monkeypatch):
    _isolate_databases(tmp_path, monkeypatch)
    bundle = _financial_frames()

    assert storage.save_financial_bundle_atomic(
        bundle,
        "600000.SH",
        provider="baostock",
        checkpoint_date="2024-03-31",
        checkpoint_from_date="2015-01-01",
        checkpoint_terminal=True,
    )
    checkpoint = storage.get_ingestion_commit(
        "financial_stock_checkpoint",
        "600000.SH",
        provider="baostock",
    )
    assert checkpoint["through_date"] == "2024-03-31"
    assert checkpoint["from_date"] == "2015-01-01"
    assert checkpoint["terminal"] is True


def test_stock_financial_failure_rolls_back_bundle_and_checkpoint(tmp_path, monkeypatch):
    _isolate_databases(tmp_path, monkeypatch)
    original = storage._save_frame

    def fail_on_balance(connection, df, category, sub, partition, mode="overwrite", merge_on=None):
        if sub == "balancesheet":
            raise RuntimeError("injected stock financial failure")
        return original(connection, df, category, sub, partition, mode, merge_on)

    monkeypatch.setattr(storage, "_save_frame", fail_on_balance)
    assert not storage.save_financial_bundle_atomic(
        _financial_frames(),
        "600000.SH",
        provider="baostock",
        checkpoint_date="2024-03-31",
    )
    assert storage.load_financial("income", ["600000.SH"], provider="baostock").empty
    assert storage.get_ingestion_commit(
        "financial_stock_checkpoint",
        "600000.SH",
        provider="baostock",
    ) is None


def test_dividend_batch_commits_data_and_empty_checkpoints(tmp_path, monkeypatch):
    _isolate_databases(tmp_path, monkeypatch)
    frames = {
        "600000.SH": pd.DataFrame(
            [
                {
                    "ts_code": "600000.SH",
                    "end_date": "2023-12-31",
                    "ann_date": "2024-03-20",
                    "cash_div": 0.3,
                }
            ]
        ),
        "000001.SZ": pd.DataFrame(),
    }

    assert storage.save_dividend_batch_atomic(
        frames,
        checkpoint_date="2026-08-18",
        provider="tushare",
    )
    saved = storage.load_financial("dividend", ["600000.SH"], provider="tushare")
    assert len(saved) == 1
    ready = storage.get_ingestion_commit(
        "dividend_stock_checkpoint",
        "600000.SH",
        provider="tushare",
    )
    no_data = storage.get_ingestion_commit(
        "dividend_stock_checkpoint",
        "000001.SZ",
        provider="tushare",
    )
    assert ready["status"] == "ready"
    assert ready["row_count"] == 1
    assert no_data["status"] == "no_data"
    assert no_data["row_count"] == 0


def test_metadata_only_ingestion_checkpoint(tmp_path, monkeypatch):
    _isolate_databases(tmp_path, monkeypatch)

    assert storage.save_ingestion_commit(
        "daily_stock_checkpoint",
        "600840.SH",
        {
            "from_date": "2015-01-01",
            "through_date": "2026-08-17",
            "status": "no_data",
        },
        provider="baostock",
    )
    checkpoint = storage.get_ingestion_commit(
        "daily_stock_checkpoint",
        "600840.SH",
        provider="baostock",
    )
    assert checkpoint["status"] == "no_data"
    assert checkpoint["through_date"] == "2026-08-17"
