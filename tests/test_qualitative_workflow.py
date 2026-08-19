import asyncio
import json
import time

import pandas as pd

from src.agent.tools import ToolSandbox, get_tool_definitions
from src.agent.runtime import (
    _build_framework_content,
    _load_output_schemas,
    build_synthesis_prompt,
)
from src.data.snapshot import StockSnapshot
from src.desktop.api.routers import frameworks
from src.desktop.api.routers import qualitative
from src.desktop.api.services import qualitative_jobs, screening_strategies, validation_archive


def _strategy():
    return {
        "id": "demo",
        "name": "价值质量",
        "updated_at": "2026-08-18",
        "definition": {
            "exclude_st": True,
            "industry_cap": 2,
            "filters": [
                {"field": "pb", "enabled": True, "mode": "value", "max": 2.0}
            ],
            "ranking": [
                {
                    "field": "bp",
                    "weight": 1.0,
                    "direction": "desc",
                    "na_handling": "worst",
                }
            ],
        },
    }


def test_synthesis_contract_normalizes_framework_specific_aliases():
    normalized = qualitative_jobs.normalize_synthesis(
        {
            "synthesis": {
                "总体评分": "78 / 100",
                "投资建议": "建议买入",
                "一句话买入逻辑（强制）": "现金流改善可推动估值修复",
                "主要风险": ["需求下滑", "资本开支超预期"],
                "置信度": "中",
            }
        }
    )

    assert normalized == {
        "score": 78.0,
        "recommendation": "建议买入",
        "recommendation_bucket": "positive",
        "recommendation_label_bucket": "positive",
        "core_logic": "现金流改善可推动估值修复",
        "risks": "需求下滑；资本开支超预期",
        "confidence": "中",
        "contract_complete": True,
        "contract_warnings": [],
        "synthesis_fields": {
            "总体评分": "78 / 100",
            "投资建议": "建议买入",
            "一句话买入逻辑（强制）": "现金流改善可推动估值修复",
            "主要风险": ["需求下滑", "资本开支超预期"],
            "置信度": "中",
        },
    }


def test_synthesis_contract_uses_score_threshold_as_batch_bucket():
    normalized = qualitative_jobs.normalize_synthesis(
        {"synthesis": {"综合评分": 72, "最终建议": "观望"}},
        {"buy": 70, "avoid": 29},
    )

    assert normalized["recommendation_bucket"] == "positive"
    assert normalized["recommendation_label_bucket"] == "watch"
    assert normalized["contract_complete"] is False
    assert normalized["contract_warnings"]


def test_strict_history_tool_sandbox_excludes_realtime_context():
    snapshot = StockSnapshot(
        ts_code="600000.SH",
        stock_name="测试",
        cutoff_date="2020-06-30",
        generated_at="2020-06-30 00:00:00",
    )
    tool_names = {
        item["function"]["name"] for item in get_tool_definitions(blind_mode=True)
    }

    assert "query_market_context" not in tool_names
    result = ToolSandbox(snapshot, blind_mode=True).execute(
        "query_market_context", {"info_type": "news"}
    )
    assert "禁止" in result


def test_runtime_resolves_history_variant_without_desktop_materialization():
    from src.engine.config import StrategyConfig

    config = StrategyConfig.from_yaml("strategies/v6_enhanced/strategy.yaml")
    chapter = next(
        item for item in config.get_chapter_defs() if item["id"] == "ch07_market"
    )
    content = _build_framework_content(chapter, config, history_mode=True)

    assert "市场情绪与资金面分析" in content
    assert "新闻与公告信号分析" in content
    assert "query_market_context" not in content


def test_framework_history_preflight_resolves_current_only_operators():
    safe = qualitative_jobs.framework_snapshot("v6_value")
    adapted = qualitative_jobs.framework_snapshot("v6_enhanced")

    assert safe["history_blockers"] == []
    assert safe["integrity_blockers"] == []
    assert safe["identity"]
    assert len(safe["operator_catalog"]) == safe["operator_count"]
    assert safe["operator_catalog"]["data_source_grading"]["name"] == "数据源分级与可信度体系"
    assert safe["history_adaptations"] == []
    assert adapted["history_blockers"] == []
    assert len(adapted["history_adaptations"]) == 5
    assert adapted["operator_catalog"]["news_signal"]["history_adapted"] is True
    assert adapted["operator_catalog"]["news_signal"]["history_variant"] == "news_signal_history"

    bank = qualitative_jobs.framework_snapshot("bank_analysis")
    assert "bank_asset_quality" in bank["operator_catalog"]
    assert bank["integrity_blockers"] == []
    assert bank["history_blockers"] == []
    assert len(bank["history_adaptations"]) == 5


def test_all_frameworks_have_valid_structure_and_operator_references():
    snapshots = [
        qualitative_jobs.framework_snapshot(path.name)
        for path in qualitative_jobs.FRAMEWORKS_ROOT.iterdir()
        if (path / "strategy.yaml").exists()
    ]

    assert snapshots
    assert all(item["integrity_blockers"] == [] for item in snapshots)
    assert all(item["history_blockers"] == [] for item in snapshots)


def test_all_frameworks_build_a_valid_synthesis_prompt():
    snapshot = StockSnapshot(
        ts_code="TEST",
        stock_name="测试",
        cutoff_date="2026-08-19",
        generated_at="2026-08-19 00:00:00",
    )
    for path in qualitative_jobs.FRAMEWORKS_ROOT.iterdir():
        if not (path / "strategy.yaml").exists():
            continue
        config = qualitative_jobs.StrategyConfig.from_yaml(path / "strategy.yaml")
        prompt = build_synthesis_prompt(config, snapshot, {}, False, {})
        assert "综合评分" in prompt
        assert "最终建议" in prompt


def test_operator_library_versions_are_explicit_and_framework_bound():
    from src.desktop.api.routers import operators

    versions = asyncio.run(operators.list_operator_versions())
    v1 = asyncio.run(operators.list_operators(version="v1"))
    v2 = asyncio.run(operators.list_operators(version="v2"))
    value = frameworks._load_framework("v6_value")

    assert [item["id"] for item in versions["versions"]][:2] == ["v2", "v1"]
    assert v1["operators_dir"] == "operators/v1"
    assert v2["operators_dir"] == "operators/v2"
    assert v2["total"] > v1["total"]
    assert value["operators_dir"] == "operators/v1"
    assert value["chapters"][0]["operators"][0]["outputs"]


def test_framework_create_allows_an_empty_draft(tmp_path, monkeypatch):
    monkeypatch.setattr(frameworks, "STRATEGIES_DIR", tmp_path)
    created = asyncio.run(
        frameworks.create_framework(
            frameworks.FrameworkCreate(
                name="draft",
                display_name="草稿框架",
                operators_dir="operators/v2",
            )
        )
    )

    assert created["name"] == "draft"
    assert created["chapters"] == []
    assert (tmp_path / "draft" / "strategy.yaml").exists()


def test_industry_routing_keeps_prompt_and_output_schema_aligned():
    config = qualitative_jobs.StrategyConfig.from_yaml(
        qualitative_jobs.FRAMEWORKS_ROOT / "v6_enhanced" / "strategy.yaml"
    )
    chapter = next(item for item in config.get_chapter_defs() if item["id"] == "ch03_cashflow")
    registry = config.get_operator_registry()
    expected_fields = {
        output.field
        for operator in registry.resolve(chapter["operators"], industry="银行")
        for output in operator.outputs
    }
    schema = _load_output_schemas(config, industry="银行")[chapter["id"]]

    assert "cash_trend_5y" not in [item.id for item in registry.resolve(chapter["operators"], industry="银行")]
    assert all(field in schema for field in expected_fields)
    excluded_fields = {
        output.field
        for operator in registry.resolve(chapter["operators"])
        if operator.id in {"cash_trend_5y", "owner_earnings"}
        for output in operator.outputs
    }
    assert all(field not in schema for field in excluded_fields - expected_fields)


def test_framework_write_validation_rejects_missing_operator():
    chapters = [
        frameworks.ChapterDef(
            id="ch01",
            chapter=1,
            title="错误章节",
            operators=["operator_does_not_exist"],
            dependencies=[],
        )
    ]

    try:
        frameworks._assert_framework_valid(chapters, "operators/v2")
    except qualitative.HTTPException as exc:
        assert exc.status_code == 422
        assert exc.detail["issues"][0]["kind"] == "missing_operator"
    else:
        raise AssertionError("无效算子引用应当在保存前被拒绝")


def test_framework_write_validation_rejects_invalid_synthesis_contract():
    try:
        frameworks._assert_synthesis_valid(
            {
                "thinking_steps": [{"step": "", "instruction": ""}],
                "scoring_rubric": [{"description": "缺少区间或维度"}],
                "decision_thresholds": {"buy": 20, "avoid": 30},
            },
            [{"field": "综合评分", "type": "decimal", "desc": ""}],
            [],
        )
    except qualitative.HTTPException as exc:
        assert exc.status_code == 422
        assert len(exc.detail["issues"]) >= 3
    else:
        raise AssertionError("无效综合研判配置应当在保存前被拒绝")


def test_runtime_composition_keeps_framework_and_screening_independent(tmp_path):
    config = qualitative_jobs.build_composed_config(
        "v6_value",
        _strategy(),
        start_date="2020-01-01",
        end_date="2021-01-01",
        interval="6m",
        top_n=12,
        concurrency=3,
        run_dir=tmp_path / "run",
    )

    assert config.get_filters() == [{"field": "pb", "enabled": True, "max": 2.0}]
    assert config.get_scoring_factors()[0]["field"] == "bp"
    assert config.get_agent_batch_size(100) == 12
    assert config.get_agent_concurrency() == 3
    assert len(config.get_chapter_defs()) == 6
    assert config.get_backtest_dir() == (tmp_path / "run").resolve()
    assert (tmp_path / "run" / "runtime_strategy.yaml").exists()


def test_runtime_composition_materializes_history_operator_variants(tmp_path):
    config = qualitative_jobs.build_composed_config(
        "v6_enhanced",
        _strategy(),
        start_date="2020-01-01",
        end_date="2021-01-01",
        interval="6m",
        top_n=12,
        concurrency=3,
        run_dir=tmp_path / "adapted",
    )
    operator_ids = [
        operator_id
        for chapter in config.get_chapter_defs()
        for operator_id in chapter["operators"]
    ]

    assert "news_signal" not in operator_ids
    assert "news_signal_history" in operator_ids
    assert "valuation_dividend_history" in operator_ids
    assert len(config.raw["runtime"]["history_adaptations"]) == 5


def test_preflight_estimates_cost_and_adapts_realtime_framework(monkeypatch):
    monkeypatch.setattr(
        screening_strategies,
        "get_strategy",
        lambda strategy_id: _strategy(),
    )
    monkeypatch.setattr(
        qualitative.research,
        "screening_status",
        lambda: _async_value(
            {"provider": "baostock", "latest_date": "2026-08-18", "available": True}
        ),
    )
    monkeypatch.setattr(
        qualitative,
        "_llm_status",
        lambda: {"configured": True, "model": "test-model"},
    )

    latest = asyncio.run(
        qualitative._latest_preflight(
            qualitative.LatestRunRequest(
                screening_strategy_id="demo",
                framework_id="v6_value",
                top_n=8,
                concurrency=2,
            )
        )
    )
    adapted = asyncio.run(
        qualitative._validation_preflight(
            qualitative.ValidationRunRequest(
                screening_strategy_id="demo",
                framework_id="v6_enhanced",
                start_date="2020-01-01",
                end_date="2020-12-31",
                interval="6m",
                top_n=8,
                concurrency=2,
            )
        )
    )

    assert latest["ready"] is True
    assert latest["estimated"] == {"analyses": 8, "cost_yuan": 3.2, "minutes": 20}
    assert latest["screening_strategy"]["definition"] == _strategy()["definition"]
    assert latest["screening_strategy"]["filter_count"] == 1
    assert latest["screening_strategy"]["ranking_count"] == 1
    assert adapted["ready"] is True
    assert adapted["blockers"] == []
    assert len(adapted["framework"]["history_adaptations"]) == 5
    assert not any("历史实现" in item or "历史适配" in item for item in adapted["warnings"])


async def _async_value(value):
    return value


def test_qualitative_job_persistence_is_atomic_and_marks_orphans(tmp_path):
    root = tmp_path / "runs"
    job_dir = root / "orphan"
    job_dir.mkdir(parents=True)
    (job_dir / "run.json").write_text(
        '{"id":"orphan","kind":"latest_judgement","status":"running","created_at":"2026-08-18T00:00:00"}',
        encoding="utf-8",
    )

    manager = qualitative_jobs.QualitativeJobManager(root)
    jobs = manager.list_jobs("latest_judgement")

    assert jobs[0]["status"] == "interrupted"
    assert not (job_dir / "run.json.tmp").exists()


def test_legacy_validation_archive_keeps_only_latest_matching_run(tmp_path):
    frameworks = tmp_path / "strategies"
    backtest = frameworks / "demo" / "backtest"
    backtest.mkdir(parents=True)

    def write_summary(name, generated_at, agent_mean):
        payload = {
            "strategy": "示例框架",
            "version": "1.0",
            "generated_at": generated_at,
            "dates": ["2020-06-30", "2020-12-31"],
            "interval": "6m",
            "slices": [
                {
                    "cutoff_date": "2020-06-30",
                    "screen_count": 50,
                    "agent_count": 2,
                    "agent_scores": {
                        "600000.SH": {"recommendation": "买入"},
                        "600001.SH": {"recommendation": "观望"},
                    },
                }
            ],
            "performance": {
                "screen_all": {"stats": {"6个月": {"count": 2, "mean": 0.01}}},
                "agent_buy": {"stats": {"6个月": {"count": 1, "mean": agent_mean}}},
            },
        }
        (backtest / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    write_summary("backtest_summary_20260101_0000.json", "2026-01-01T00:00:00", 0.02)
    write_summary("backtest_summary_20260201_0000.json", "2026-02-01T00:00:00", 0.05)

    archives = validation_archive.list_validation_archive(frameworks)

    assert len(archives) == 1
    archive = archives[0]
    assert archive["imported"] is True
    assert archive["result"]["outcome_schema_version"] == 1
    assert archive["result"]["return_basis"] == "legacy_unspecified"
    assert archive["provenance"]["outcome_recomputed"] is False
    assert archive["is_current"] is False
    assert archive["params"]["framework_id"] == "demo"
    assert archive["params"]["screening_strategy_name"] == "历史内嵌筛选配置"
    assert archive["result"]["analysis_completed"] == 2
    assert archive["result"]["performance"]["agent_buy"]["stats"]["6个月"]["mean"] == 0.05
    assert archive["result"]["summary_path"].endswith("backtest_summary_20260201_0000.json")


def test_validation_archive_preserves_recomputed_outcome_contract(tmp_path):
    frameworks = tmp_path / "strategies"
    backtest = frameworks / "demo" / "backtest"
    backtest.mkdir(parents=True)
    payload = {
        "strategy": "示例框架",
        "version": "1.0",
        "generated_at": "2026-08-19T00:00:00",
        "provider": "tushare",
        "outcome_schema_version": 3,
        "evaluation_semantics": "forward_return",
        "return_basis": "hfq_adjusted_close",
        "dates": ["2020-06-30"],
        "interval": "6m",
        "slices": [],
        "performance": {},
    }
    (backtest / "backtest_summary_20260819_0000.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )

    archive = validation_archive.list_validation_archive(frameworks)[0]

    assert archive["result"]["outcome_schema_version"] == 3
    assert archive["result"]["evaluation_semantics"] == "forward_return"
    assert archive["result"]["return_basis"] == "hfq_adjusted_close"
    assert archive["params"]["provider"] == "tushare"
    assert archive["provenance"]["outcome_recomputed"] is True


def test_archive_endpoint_marks_current_history_contract(monkeypatch):
    monkeypatch.setattr(
        qualitative,
        "list_validation_archive",
        lambda root: [
            {"params": {"framework_id": "safe"}, "provenance": {}},
            {"params": {"framework_id": "unsafe"}, "provenance": {}},
        ],
    )
    monkeypatch.setattr(
        qualitative,
        "framework_snapshot",
        lambda framework_id: {
            "history_blockers": [] if framework_id == "safe" else [{"id": "news"}]
        },
    )

    archives = asyncio.run(qualitative.validation_archive())

    assert archives[0]["provenance"]["current_history_safe"] is True
    assert archives[0]["provenance"]["current_history_blocker_count"] == 0
    assert archives[1]["provenance"]["current_history_safe"] is False
    assert archives[1]["provenance"]["current_history_blocker_count"] == 1


def test_framework_validation_persists_analysis_coverage(tmp_path, monkeypatch):
    import src.backtest.pipeline as pipeline

    monkeypatch.setattr(pipeline, "step_screen", lambda config: ["2020-06-30"])
    monkeypatch.setattr(
        pipeline,
        "load_screen_csv",
        lambda cutoff_date, screen_dir: pd.DataFrame(
            [
                {"ts_code": "600000.SH", "stock_name": "甲"},
                {"ts_code": "600001.SH", "stock_name": "乙"},
            ]
        ),
    )

    def fake_eval(config, numeric_only=False):
        assert numeric_only is False
        run_dir = config.get_backtest_dir()
        summary = {
            "dates": ["2020-06-30"],
            "interval": "6m",
            "slices": [{"cutoff_date": "2020-06-30", "screen_count": 2}],
            "performance": {
                "screen_all": {"label": "筛选池", "stats": {}},
                "agent_buy": {"label": "框架买入", "stats": {}},
            },
        }
        (run_dir / "backtest_summary_20200101_0000.json").write_text(
            json.dumps(summary), encoding="utf-8"
        )
        report = run_dir / "backtest_report.md"
        report.write_text("ok", encoding="utf-8")
        return report

    monkeypatch.setattr(pipeline, "step_eval", fake_eval)
    manager = qualitative_jobs.QualitativeJobManager(tmp_path / "runs")

    async def fake_analyze(*args, **kwargs):
        runtime_operator_ids = [
            operator_id
            for chapter in kwargs["config"].get_chapter_defs()
            for operator_id in chapter["operators"]
        ]
        assert "news_signal_history" in runtime_operator_ids
        assert "news_signal" not in runtime_operator_ids
        return [
            {"ts_code": "600000.SH", "cutoff_date": "2020-06-30", "status": "completed"},
            {"ts_code": "600001.SH", "cutoff_date": "2020-06-30", "status": "failed"},
        ]

    monkeypatch.setattr(manager, "_analyze_candidates", fake_analyze)
    params = {
        "screening_strategy_id": "demo",
        "screening_strategy_name": "价值质量",
        "screening_strategy_snapshot": _strategy(),
        "framework_id": "v6_enhanced",
        "framework_name": "V6 增强分析",
        "start_date": "2020-01-01",
        "end_date": "2020-12-31",
        "interval": "6m",
        "top_n": 2,
        "concurrency": 2,
    }
    started = manager.start("framework_validation", params)

    job = started
    for _ in range(100):
        job = manager.get_job(started["id"])
        if job["status"] not in {"queued", "running"}:
            break
        time.sleep(0.01)

    assert job["status"] == "completed"
    assert job["result"]["analysis_total"] == 2
    assert job["result"]["analysis_completed"] == 1
    assert job["result"]["analysis_failed"] == 1
