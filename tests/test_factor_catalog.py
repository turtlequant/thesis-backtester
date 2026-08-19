import sqlite3
from types import SimpleNamespace

import pandas as pd
import polars as pl
import pytest

from src.data.field_catalog import SourceFieldCatalog
from src.engine.factor_catalog import (
    FactorCatalog,
    save_factor_definition,
    validate_factor_definition,
)
from src.engine.factor_dsl import FactorDslError, compile_expression
from src.engine.factor_temporal import align_events_to_daily, build_point_in_time_events
from src.engine.factors import FactorRegistry


def _dsl_payload(factor_id="test_ep"):
    return {
        "schema_version": 1,
        "id": factor_id,
        "name": "测试盈利收益率",
        "description": "用于验证受控表达式",
        "category": "valuation",
        "tags": ["test"],
        "type": "cross_section",
        "grain": "security_date",
        "engine": "polars",
        "inputs": {"pe": "valuation.pe_ttm"},
        "expression": 'round(safe_div(100.0, col("pe")), 2)',
        "output": {
            "dtype": "float64",
            "unit": "percent",
            "direction": "higher_better",
        },
        "policies": {"null": "propagate", "point_in_time": "strict", "enabled": True},
    }


def test_positive_streak_resets_across_missing_report_years():
    frame = pl.DataFrame(
        {
            "ts_code": ["600000.SH"] * 5,
            "end_date": [
                "2018-12-31",
                "2020-12-31",
                "2021-12-31",
                "2022-12-31",
                "2023-12-31",
            ],
            "value": [0.2, 0.3, 0.4, 0.0, 0.5],
        }
    )
    expression = compile_expression(
        'positive_streak(col("value"))',
        {"value": "value"},
        output_name="streak",
        window_by=("ts_code",),
    )

    result = frame.lazy().with_columns(expression).collect()

    assert result["streak"].to_list() == [1.0, 1.0, 2.0, 0.0, 1.0]


def test_native_catalog_exposes_explicit_provider_boundaries():
    catalog = SourceFieldCatalog()

    pe = catalog.require("valuation.pe_ttm")
    pcf = catalog.require("valuation.pcf_ncf_ttm")
    total_mv = catalog.require("size.total_market_value_wan")

    assert pe.binding_for("tushare").compatibility == "exact"
    assert pe.binding_for("baostock").compatibility == "exact"
    assert pcf.binding_for("tushare").compatibility == "unavailable"
    assert "daily_basic" in pcf.binding_for("tushare").note
    assert pcf.binding_for("baostock").compatibility == "exact"
    assert total_mv.binding_for("tushare").field == "total_mv"
    assert total_mv.binding_for("baostock") is None


def test_unsupported_native_field_remains_visible_but_not_executable(tmp_path):
    asset = FactorCatalog(
        provider="tushare",
        database_path=tmp_path / "missing.db",
    ).get_asset("pcf_ncf_ttm")

    assert asset["screening_catalogued"] is True
    assert asset["screening_eligible"] is False
    assert asset["capabilities"]["current_screen"] is False
    assert "daily_basic" in asset["materialization_blockers"][0]


def test_polars_dsl_factors_override_legacy_python_and_compute_together():
    registry = FactorRegistry()
    assert registry.get("ep").engine == "polars"
    assert registry.get("bp").point_in_time_safe is True

    frame = pd.DataFrame(
        {
            "pe_ttm": [10.0, 0.0, None],
            "pb": [2.0, 0.0, None],
            "dv_ttm": [4.5, None, 2.0],
            "total_mv": [10000.0, 25000.0, None],
            "circ_mv": [8000.0, 20000.0, None],
        }
    )
    result = registry.compute_all(frame)

    assert result["ep"].tolist()[0] == 10.0
    assert pd.isna(result["ep"].tolist()[1])
    assert result["bp"].tolist()[0] == 0.5
    assert result["dv"].tolist()[0] == 4.5
    assert result["market_cap_yi"].tolist()[1] == 2.5
    assert result["circ_mv_yi"].tolist()[0] == 0.8


def test_factor_catalog_downgrades_baostock_and_blocks_legacy_financial_factors(tmp_path):
    database = tmp_path / "market.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE _datasets (table_name TEXT, category TEXT, sub TEXT, "
            "row_count INTEGER, partition_count INTEGER, latest_date TEXT, updated_at TEXT)"
        )
        connection.execute(
            "CREATE TABLE dataset_daily_indicator (_partition TEXT, ts_code TEXT, "
            "trade_date TEXT, pe_ttm REAL, pb REAL, ps_ttm REAL, turnover_rate REAL)"
        )
        connection.execute(
            "INSERT INTO _datasets VALUES "
            "('dataset_daily_indicator', 'daily', 'indicator', 100, 1, '2024-01-31', 'now')"
        )

    catalog = FactorCatalog(provider="baostock", database_path=database)
    assets = {asset["id"]: asset for asset in catalog.list_assets()}

    assert assets["pe_ttm"]["provider"]["compatibility"] == "exact"
    assert assets["total_mv"]["provider"]["compatibility"] == "unavailable"
    assert assets["ep"]["screening_eligible"] is True
    assert assets["market_cap_yi"]["screening_eligible"] is False
    assert assets["roe_avg_3y"]["provider"]["compatibility"] == "unavailable"
    assert assets["roe_avg_3y"]["research_status"] == "unavailable"


def test_factor_catalog_rejects_stale_materialization_hash(tmp_path):
    database = tmp_path / "market.db"
    current = FactorCatalog(provider="tushare").get_definition("ep")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE _datasets (table_name TEXT, category TEXT, sub TEXT, "
            "row_count INTEGER, partition_count INTEGER, latest_date TEXT, updated_at TEXT)"
        )
        connection.execute(
            "CREATE TABLE dataset_daily_factors (_partition TEXT, ts_code TEXT, "
            "trade_date TEXT, ep REAL)"
        )
        connection.execute(
            "INSERT INTO _datasets VALUES "
            "('dataset_daily_factors', 'daily', 'factors', 100, 1, '2024-01-31', 'now')"
        )
        connection.execute(
            "CREATE TABLE _factor_materializations (factor_id TEXT PRIMARY KEY, "
            "definition_hash TEXT, status TEXT, start_date TEXT, end_date TEXT, "
            "row_count INTEGER, updated_at TEXT, error TEXT)"
        )
        connection.execute(
            "INSERT INTO _factor_materializations VALUES "
            "('ep', 'old-definition', 'ready', '2024-01-01', '2024-01-31', 100, 'now', NULL)"
        )

    stale = FactorCatalog(provider="tushare", database_path=database).get_asset("ep")
    assert stale["materialization"]["status"] == "stale"
    assert stale["materialization"]["usable"] is False

    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE _factor_materializations SET definition_hash=? WHERE factor_id='ep'",
            (current.definition_hash,),
        )
    ready = FactorCatalog(provider="tushare", database_path=database).get_asset("ep")
    assert ready["materialization"]["status"] == "ready"
    assert ready["materialization"]["definition_version_verified"] is True


def test_dividend_factors_wait_for_complete_tushare_baseline(tmp_path):
    database = tmp_path / "market.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE _datasets (table_name TEXT, category TEXT, sub TEXT, "
            "row_count INTEGER, partition_count INTEGER, latest_date TEXT, updated_at TEXT)"
        )
        connection.execute(
            "CREATE TABLE dataset_daily_indicator "
            "(_partition TEXT, ts_code TEXT, trade_date TEXT, pe_ttm REAL)"
        )
        connection.execute(
            "CREATE TABLE dataset_financial_dividend "
            "(_partition TEXT, ts_code TEXT, end_date TEXT, ann_date TEXT, cash_div REAL, cash_div_tax REAL)"
        )
        connection.executemany(
            "INSERT INTO _datasets VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("dataset_daily_indicator", "daily", "indicator", 100, 1, "2024-01-31", "now"),
                ("dataset_financial_dividend", "financial", "dividend", 96, 1, "2023-12-31", "now"),
            ],
        )
        connection.execute(
            "CREATE TABLE _ingestion_commits "
            "(dataset TEXT, commit_key TEXT, row_counts TEXT, committed_at TEXT)"
        )
        connection.execute(
            "INSERT INTO _ingestion_commits VALUES "
            "('dividend_stock_checkpoint', '000001.SZ', '{\"status\":\"ready\"}', 'now')"
        )

    incomplete = FactorCatalog(
        provider="tushare",
        database_path=database,
    ).get_asset("dividend_years")
    assert "分红历史基线尚未完整下载" in incomplete["materialization_blockers"]

    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO _ingestion_commits VALUES "
            "('dividend_incremental_checkpoint', 'all', '{\"status\":\"ready\"}', 'now')"
        )

    complete = FactorCatalog(
        provider="tushare",
        database_path=database,
    ).get_asset("dividend_years")
    assert "分红历史基线尚未完整下载" not in complete["materialization_blockers"]


def test_report_dsl_replays_from_announcement_date(tmp_path, monkeypatch):
    database = tmp_path / "market.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE dataset_financial_fina_indicator "
            "(_partition TEXT, ts_code TEXT, end_date TEXT, ann_date TEXT, roe REAL)"
        )
        connection.executemany(
            "INSERT INTO dataset_financial_fina_indicator VALUES (?, ?, ?, ?, ?)",
            [
                ("000001.SZ", "000001.SZ", "2019-12-31", "2020-03-10", 10.0),
                ("000001.SZ", "000001.SZ", "2020-12-31", "2021-03-10", 20.0),
                ("000001.SZ", "000001.SZ", "2021-12-31", "2022-03-10", 30.0),
            ],
        )

    from src.engine import factor_temporal

    monkeypatch.setattr(
        factor_temporal.storage,
        "connect",
        lambda provider=None: sqlite3.connect(database),
    )
    catalog = FactorCatalog(provider="tushare")
    definition = catalog.get_definition("roe_avg_3y")
    events = build_point_in_time_events(definition, "tushare", catalog.fields)

    assert events["available_date"].tolist() == ["2021-03-10", "2022-03-10"]
    assert events["roe_avg_3y"].tolist() == [15.0, 20.0]

    daily = pd.DataFrame(
        {
            "ts_code": ["000001.SZ"] * 3,
            "trade_date": ["2021-03-01", "2021-03-11", "2022-03-11"],
        }
    )
    aligned = align_events_to_daily(daily, events, "roe_avg_3y")
    assert pd.isna(aligned.iloc[0])
    assert aligned.iloc[1:].tolist() == [15.0, 20.0]


def test_temporal_definition_materializes_to_daily_factor_store(tmp_path, monkeypatch):
    from src.data import storage
    from src.data.factor_store import materialize_factor_definitions
    from src.engine import factor_catalog

    database = tmp_path / "market.db"
    monkeypatch.setattr(storage, "get_database_path", lambda provider=None: database)
    monkeypatch.setattr(
        factor_catalog,
        "get_provider_db_path",
        lambda provider: database,
    )

    indicator = pd.DataFrame(
        {
            "ts_code": ["000001.SZ"] * 3,
            "trade_date": ["2021-03-01", "2021-03-11", "2022-03-11"],
            "pe_ttm": [10.0, 10.0, 10.0],
        }
    )
    financial = pd.DataFrame(
        {
            "ts_code": ["000001.SZ"] * 3,
            "end_date": ["2019-12-31", "2020-12-31", "2021-12-31"],
            "ann_date": ["2020-03-10", "2021-03-10", "2022-03-10"],
            "roe": [10.0, 20.0, 30.0],
        }
    )
    assert storage.save(
        indicator.iloc[:2],
        "daily",
        "indicator",
        "2021-03",
        provider="tushare",
    )
    assert storage.save(
        indicator.iloc[[2]],
        "daily",
        "indicator",
        "2022-03",
        provider="tushare",
    )
    assert storage.save(
        financial,
        "financial",
        "fina_indicator",
        "000001.SZ",
        provider="tushare",
    )

    assert materialize_factor_definitions(
        ["roe_avg_3y"],
        provider="tushare",
        start_date="2021-03-01",
        end_date="2022-03-11",
    )
    materialized = storage.load(
        "daily",
        "factors",
        ["2021-03", "2022-03"],
        provider="tushare",
    ).sort_values("trade_date")
    values = materialized["roe_avg_3y"].tolist()
    assert pd.isna(values[0])
    assert values[1:] == [15.0, 20.0]

    asset = FactorCatalog(provider="tushare", database_path=database).get_asset("roe_avg_3y")
    assert asset["materialization"]["status"] == "ready"
    assert asset["materialization"]["start_date"] == "2021-03-01"
    assert asset["materialization"]["latest_date"] == "2022-03-11"


def test_factor_definition_validation_rejects_arbitrary_python():
    payload = _dsl_payload()
    payload["expression"] = '__import__("os").system("whoami")'

    with pytest.raises((FactorDslError, ValueError), match="白名单|不允许|表达式"):
        validate_factor_definition(payload)


def test_factor_definition_validation_rejects_unsupported_execution_options():
    payload = _dsl_payload()
    payload["output"]["dtype"] = "object"

    with pytest.raises((FactorDslError, ValueError), match="输出类型"):
        validate_factor_definition(payload)

    payload = _dsl_payload()
    payload["type"] = "point_in_time"
    with pytest.raises(ValueError, match="因子类型"):
        validate_factor_definition(payload)


def test_factor_definition_can_be_created_and_updated_as_yaml(tmp_path):
    created = save_factor_definition(_dsl_payload(), factors_dir=tmp_path)
    assert created.id == "test_ep"
    assert created.source_path.is_relative_to(tmp_path)
    assert created.source_path.suffixes[-2:] == [".factor", ".yaml"]

    updated_payload = _dsl_payload()
    updated_payload["name"] = "修改后的名称"
    updated = save_factor_definition(
        updated_payload,
        factors_dir=tmp_path,
        existing_id="test_ep",
    )
    assert updated.name == "修改后的名称"
    assert len(list(tmp_path.rglob("*.factor.yaml"))) == 1


def test_saved_factor_is_invalidated_and_queued_for_materialization(monkeypatch):
    from src.desktop.api.routers import factors as factor_router

    events = []

    class Catalog:
        def __init__(self, provider):
            self.snapshot = SimpleNamespace(
                datasets={"daily/indicator": {"row_count": 100}}
            )

        def get_asset(self, factor_id):
            return {"provider": {"compatibility": "exact"}}

    monkeypatch.setattr(factor_router, "get_active_provider_name", lambda: "tushare")
    monkeypatch.setattr(factor_router, "FactorCatalog", Catalog)
    monkeypatch.setattr(
        factor_router,
        "invalidate_factor_materializations",
        lambda factor_id, definition_hash: events.append(
            ("invalidate", factor_id, definition_hash)
        ),
    )
    monkeypatch.setattr(
        factor_router,
        "set_factor_materialization",
        lambda provider, factor_id, definition_hash, status, **kwargs: events.append(
            (status, provider, factor_id, definition_hash)
        ),
    )
    monkeypatch.setattr(
        factor_router.job_manager,
        "start_job",
        lambda provider, job_type, codes: {
            "id": "job-1",
            "provider": provider,
            "job_type": job_type,
            "codes": codes,
            "status": "queued",
        },
    )

    definition = SimpleNamespace(id="ep", definition_hash="hash-v2")
    job = factor_router._schedule_materialization(
        definition,
        invalidate_existing=True,
    )

    assert events[0] == ("invalidate", "ep", "hash-v2")
    assert events[1] == ("pending", "tushare", "ep", "hash-v2")
    assert job["job_type"] == "factors"
    assert job["codes"] == ["ep"]


def test_prepare_factor_queues_financial_dependency(monkeypatch):
    import asyncio

    from src.desktop.api.routers import factors as factor_router

    definition = SimpleNamespace(
        id="dividend_years",
        editable=True,
        inputs={"value": "financial.dividend.cash_div"},
    )
    binding = SimpleNamespace(dataset="financial/dividend")
    source = SimpleNamespace(binding_for=lambda provider: binding)

    class Catalog:
        def __init__(self, provider):
            self.fields = SimpleNamespace(require=lambda semantic_id: source)

        def get_definition(self, factor_id):
            return definition

        def get_asset(self, factor_id):
            return {
                "provider": {"compatibility": "exact"},
                "materialization_blockers": ["缺少输入数据 financial.dividend.cash_div"],
            }

    calls = []
    monkeypatch.setattr(factor_router, "get_active_provider_name", lambda: "tushare")
    monkeypatch.setattr(factor_router, "FactorCatalog", Catalog)
    monkeypatch.setattr(
        factor_router.job_manager,
        "start_job",
        lambda provider, job_type: calls.append((provider, job_type))
        or {"id": "job-data", "status": "queued"},
    )

    result = asyncio.run(factor_router.prepare_factor("dividend_years"))

    assert calls == [("tushare", "financials")]
    assert result["continuation"] == {
        "factor_id": "dividend_years",
        "next": "materialize",
    }
