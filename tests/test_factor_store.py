from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd

from src.data import factor_store


def test_factor_materialization_skips_all_null_provider_gaps(monkeypatch, capsys):
    indicator = pd.DataFrame(
        [
            {
                "ts_code": "600000.SH",
                "trade_date": "2024-01-02",
                "pe_ttm": 10.0,
                "ps_ttm": 1.2,
            }
        ]
    )

    class Registry:
        def list_cross_section(self):
            return [
                SimpleNamespace(id="bp"),
                SimpleNamespace(id="dv"),
                SimpleNamespace(id="ps_ttm"),
                SimpleNamespace(id="roe_avg_3y", execution_mode="point_in_time"),
            ]

        def compute_all(self, frame):
            result = frame.copy()
            result["bp"] = 0.1
            result["dv"] = float("nan")
            return result

    monkeypatch.setattr(
        factor_store.storage,
        "get_months_between",
        Mock(return_value=["2024-01"]),
    )
    monkeypatch.setattr(
        factor_store.storage,
        "load_one",
        Mock(return_value=indicator),
    )
    save = Mock(return_value=True)
    monkeypatch.setattr(factor_store.storage, "save", save)

    factor_store._compute_factors_range(
        Registry(),
        "2024-01-01",
        "2024-01-31",
    )

    saved = save.call_args.args[0]
    assert saved.columns.tolist() == ["ts_code", "trade_date", "bp"]
    output = capsys.readouterr().out
    assert "数据源原生字段: ps_ttm" in output
    assert "日频因子未产生有效结果，已跳过: dv" in output
    assert "财报时点因子由因子库物化任务续接: roe_avg_3y" in output
    assert "当前数据源不可计算" not in output


def test_definition_aware_materialization_recomputes_selected_factor(monkeypatch):
    from src.data import factor_materialization
    from src.engine import factor_catalog

    indicator = pd.DataFrame(
        {
            "ts_code": ["600000.SH", "600001.SH"],
            "trade_date": ["2024-01-02", "2024-01-02"],
            "pe_ttm": [10.0, 20.0],
        }
    )
    definition = SimpleNamespace(enabled=True, definition_hash="hash-v2")

    class Catalog:
        def __init__(self, provider):
            self.provider = provider

        def list_assets(self):
            return [
                {
                    "id": "ep",
                    "provider": {"compatibility": "exact"},
                }
            ]

        def get_definition(self, factor_id):
            return definition if factor_id == "ep" else None

    monkeypatch.setattr(factor_catalog, "FactorCatalog", Catalog)
    monkeypatch.setattr(factor_store.storage, "list_partitions", lambda *args, **kwargs: ["2024-01"])
    monkeypatch.setattr(factor_store.storage, "get_latest_date", lambda *args, **kwargs: "2024-01-31")
    monkeypatch.setattr(factor_store.storage, "get_months_between", lambda *args: ["2024-01"])
    monkeypatch.setattr(factor_store.storage, "load_one", lambda *args, **kwargs: indicator)
    save = Mock(return_value=True)
    monkeypatch.setattr(factor_store.storage, "save", save)
    states = []
    monkeypatch.setattr(
        factor_materialization,
        "set_factor_materialization",
        lambda provider, factor_id, definition_hash, status, **kwargs: states.append(
            (provider, factor_id, definition_hash, status, kwargs)
        ),
    )

    assert factor_store.materialize_factor_definitions(["ep"], provider="baostock") is True
    saved = save.call_args.args[0]
    assert saved["ep"].tolist() == [10.0, 5.0]
    assert states[0][3] == "computing"
    assert states[-1][3] == "ready"
    assert states[-1][4]["row_count"] == 2
