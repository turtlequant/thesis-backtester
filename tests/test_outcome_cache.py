from datetime import datetime

import pandas as pd

from src.backtest import outcome_cache, outcome_collector, pipeline
from src.data import config as data_config
from src.desktop.api.services import screening_strategies


def test_shared_outcome_cache_is_provider_scoped_and_upserts(tmp_path, monkeypatch):
    monkeypatch.setattr(outcome_cache, "CACHE_DB_PATH", tmp_path / "cache" / "outcomes.db")
    first = {"_schema_version": 3, "return_6m": 0.1}
    updated = {"_schema_version": 3, "return_6m": 0.2}

    outcome_cache.save_cutoff("tushare", "2024-01-31", {"600000.SH": first})
    outcome_cache.save_cutoff("tushare", "2024-01-31", {"600000.SH": updated})
    outcome_cache.save_cutoff("baostock", "2024-01-31", {"000001.SZ": first})

    assert outcome_cache.load_cutoff("tushare", "2024-01-31") == {
        "600000.SH": updated
    }
    assert outcome_cache.load_cutoff("baostock", "2024-01-31") == {
        "000001.SZ": first
    }
    assert outcome_cache.load_cutoff("tushare", "2024-07-31") == {}


def test_step_eval_batches_cutoffs_once_and_reuses_cache_across_runs(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(outcome_cache, "CACHE_DB_PATH", tmp_path / "cache" / "outcomes.db")
    monkeypatch.setattr(data_config, "get_active_provider_name", lambda: "tushare")
    calls = []

    def fake_collect(requests):
        calls.append(requests)
        return {
            cutoff: {
                code: outcome_collector.ForwardOutcome(
                    ts_code=code,
                    cutoff_date=cutoff,
                    return_6m=0.1,
                    collection_date=datetime.now().strftime("%Y-%m-%d"),
                )
                for code in codes
            }
            for cutoff, codes in requests.items()
        }

    def fake_performance(slices, config, numeric_only=False):
        stats = {item["label"]: {"count": 0} for item in config.get_forward_periods()}
        return {
            key: {"label": key, "desc": "", "stats": stats, "slices": []}
            for key in ("market", "screen_all", "screen_top")
        }

    monkeypatch.setattr(
        outcome_collector,
        "collect_forward_outcomes_by_cutoff",
        fake_collect,
    )
    monkeypatch.setattr(pipeline, "_evaluate_multi_baseline", fake_performance)
    monkeypatch.setattr(pipeline, "_generate_return_chart", lambda *args: None)

    strategy = {
        "id": "batch-cache",
        "name": "批量缓存测试",
        "updated_at": "1",
        "definition": {"filters": [], "ranking": []},
    }
    dates = ("2024-01-31", "2024-07-31")
    for run_name in ("run-one", "run-two"):
        run_dir = tmp_path / run_name
        config = screening_strategies.build_config(
            strategy,
            start_date=dates[0],
            end_date=dates[1],
            interval="6m",
            top_n=2,
            run_dir=run_dir,
        )
        for cutoff in dates:
            pipeline.save_screen_csv(
                pd.DataFrame({"ts_code": ["600000.SH", "000001.SZ"]}),
                cutoff,
                run_dir / "screen_results",
            )
        pipeline.step_eval(config, numeric_only=True)

    assert len(calls) == 1
    assert calls[0] == {
        "2024-01-31": ["600000.SH", "000001.SZ"],
        "2024-07-31": ["600000.SH", "000001.SZ"],
    }
