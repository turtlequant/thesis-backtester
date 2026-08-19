import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from src.desktop.api.routers import chat, research
from src.desktop.api.services import research_jobs, screening_strategies
from src.desktop.api.services.screening_preview_cache import clear_screening_preview_cache
from src.backtest.pipeline import (
    OUTCOME_CACHE_SCHEMA_VERSION,
    EvalSlice,
    _format_eval_report,
    _save_eval_json,
)
from src.screener.quick_filter import _apply_filters, _compute_scores


FRONTEND_DIR = Path(__file__).parents[1] / "src" / "desktop" / "frontend"


def test_workspace_frontend_assets_are_registered():
    index = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    app = (FRONTEND_DIR / "js" / "app.js").read_text(encoding="utf-8")
    chat = (FRONTEND_DIR / "js" / "pages" / "chat.js").read_text(encoding="utf-8")
    guide = (FRONTEND_DIR / "js" / "pages" / "guide.js").read_text(encoding="utf-8")
    factors = (FRONTEND_DIR / "js" / "pages" / "factors.js").read_text(encoding="utf-8")
    frameworks = (FRONTEND_DIR / "js" / "pages" / "frameworks.js").read_text(
        encoding="utf-8"
    )
    cross_section = (FRONTEND_DIR / "js" / "pages" / "crosssection.js").read_text(
        encoding="utf-8"
    )
    header_pages = {
        name: (FRONTEND_DIR / "js" / "pages" / name).read_text(encoding="utf-8")
        for name in (
            "analysis.js",
            "reports.js",
            "qualitative.js",
            "crosssection.js",
            "datasources.js",
            "factors.js",
            "operators.js",
            "frameworks.js",
            "settings.js",
        )
    }

    assert "/js/pages/crosssection.js" in index
    assert "/js/pages/factors.js" in index
    assert "/js/pages/qualitative.js" in index
    for workspace in ("infrastructure", "qualitative", "cross_section"):
        assert f"id: '{workspace}'" in app
    assert "machine_learning" not in app
    assert "machine-learning" not in index
    assert "conversation_id: activeConversation" in chat
    assert "Vue.watch(conversationId" in chat
    assert "/js/pages/guide.js" in index
    assert "guide-sidebar-button" in app
    assert "const agentOpen = ref(true);" in app
    assert "selectWorkspace(workspace.id, $event)" in app
    assert "workspace-option-menu" in app
    assert "pageId === 'frameworks' || pageId === 'operators'" not in app
    assert app.index("id: 'cross_section'") < app.index("id: 'qualitative'")
    assert "label: '截面筛选'" in app
    assert "ScreeningWorkbenchPage" in app
    assert "defaultPage: 'screening-strategies'" in app
    assert "label: '策略构建'" in app
    assert "label: '截面选股'" in app
    assert "label: '历史验证'" in app
    assert "label: '因子库'" in app
    assert "label: '结构化投研'" in app
    assert "label: '个股分析'" in app
    assert "label: '最新研判'" in app
    assert "label: '框架验证'" in app
    assert "const WorkspacePageHeader" in app
    assert "app.component('workspace-page-header', WorkspacePageHeader)" in app
    for source in header_pages.values():
        assert "<workspace-page-header" in source
        assert "workspace-hero" not in source
        assert "workspace-principle" not in source
    assert "LatestJudgementPage" in app
    assert "FrameworkValidationPage" in app
    assert "FactorsPage" in app
    assert "输入字段" in factors
    assert "公式模板" in factors
    assert "/materialize" in factors
    assert "monitorJob" in factors
    assert 'class="card factor-summary-grid"' in factors
    assert 'class="page-header-control page-header-control-inline fw-selector"' in frameworks
    assert "currentPage === 'screening-current'" in app
    assert "currentPage === 'screening-backtest'" in app
    assert "outcome_schema_version || 1) < 3" in cross_section
    assert "outcome_schema_version || 1) < 3" in header_pages["qualitative.js"]
    assert "组合条件并即时预览" in cross_section
    assert "指标库" in cross_section
    assert "当前策略方案比较" in cross_section
    assert "screening-preview-scroll" in cross_section
    assert "规则预览结果，可左右滚动" in cross_section
    assert "screening-strategy-description-editor" in cross_section
    assert 'v-model="source.description"' in cross_section
    assert "description: this.source.description || ''" in cross_section
    assert "saveDialog.description" not in cross_section
    assert ".screening-preview-scroll" in (
        FRONTEND_DIR / "css" / "style.css"
    ).read_text(encoding="utf-8")
    assert ".screening-strategy-description-editor" in (
        FRONTEND_DIR / "css" / "style.css"
    ).read_text(encoding="utf-8")
    screening_styles = (FRONTEND_DIR / "css" / "style.css").read_text(
        encoding="utf-8"
    )
    assert ".screening-run-strip .screening-run-button" in screening_styles
    assert "align-items: start;" in screening_styles
    assert '.screening-rule > input:not([type="checkbox"])' in screening_styles
    assert "查看已有结果" in cross_section
    assert "screeningDefinitionIdentity" in cross_section
    assert "definition: this.currentStrategyIdentity" in cross_section
    assert "screeningDefinitionIdentity(this.jobStrategySnapshot(job))" in cross_section
    assert "job?.params?.screening_strategy_id === this.runForm.screening_strategy_id" in cross_section
    assert "规则版本" not in cross_section
    assert "this.autoRunReady = true" in cross_section
    assert "this.autoRunTimer = setTimeout(() => this.run(sequence), 450)" in cross_section
    assert "各持有期平均收益" in cross_section
    assert "载入其他策略" in cross_section
    assert "删除策略" in cross_section
    assert '@click="deleteStrategy"' in cross_section
    assert "历史验证快照会保留，但策略本身无法恢复" in cross_section
    assert "method: 'DELETE'" in cross_section
    assert "展示数量" not in cross_section
    assert "/api/research/screening-status" in cross_section
    assert "/api/research/screening-strategies" in cross_section
    assert "screening_strategy_id" in cross_section
    assert "LLM" not in cross_section
    assert "投研" not in cross_section
    assert "currentResultUsesLegacyOutcome" in cross_section
    assert "当前后复权收益口径前" in cross_section
    assert "按新口径重算" in cross_section
    assert "查看完整指引" in guide

    qualitative = (FRONTEND_DIR / "js" / "pages" / "qualitative.js").read_text(
        encoding="utf-8"
    )
    assert "/api/qualitative/latest/preflight" in qualitative
    assert "outcomeSemanticsCurrent" in qualitative
    assert "收益和 Alpha 继续按原始产物展示" in qualitative
    assert "/api/qualitative/validation/preflight" in qualitative
    assert "jobMatchesForm(job)" in qualitative
    assert "框架买入相对筛选池" in qualitative
    assert "当前方案不能执行" in qualitative
    assert "部分分析环节暂时无法验证" in qualitative
    assert "switchToSafeFramework" in qualitative
    assert "验证时只使用截面当时可见的数据" in qualitative
    assert "时间边界" in qualitative
    assert "historyAdaptations" in qualitative
    assert "/api/qualitative/validation/archive" in qualitative
    assert "历史验证档案" in qualitative
    assert "displayJob" in qualitative
    assert "运行前预览" in qualitative
    assert "章节 DAG" in qualitative
    assert "candidatePreview" in qualitative
    assert "candidatePreviewKey" in qualitative
    assert "refreshCandidatePreview(true)" in qualitative
    assert "historical: false, force" in qualitative
    assert "historical: true" in qualitative
    assert "零 LLM 调用" in qualitative

    reports = (FRONTEND_DIR / "js" / "pages" / "reports.js").read_text(
        encoding="utf-8"
    )
    assert "报告文件是事实来源，SQLite 只承担检索索引" in reports
    assert "report-reader" in reports
    assert "detailReportHtml" in reports
    assert "算子证据链" in reports
    assert "left.ts_code === right.ts_code" in reports
    assert "left.cutoff_date === right.cutoff_date || left.strategy === right.strategy" in reports
    assert "加入候选池" not in reports
    assert "historical_backtest" in reports
    assert "历史回测样本" in reports
    assert "report-pagination" in reports
    assert "page_size: this.pageSize" in reports
    assert "this.loadReports(false)" in reports
    assert "v-if=\"!report.read_only\"" in reports

    styles = (FRONTEND_DIR / "css" / "style.css").read_text(encoding="utf-8")
    assert ".workspace-select-wrap:hover .workspace-option-menu" in styles
    assert ".report-filter-search" in styles
    assert "grid-column: 1 / -1" in styles


def test_infrastructure_libraries_open_the_first_available_item():
    operators = (FRONTEND_DIR / "js" / "pages" / "operators.js").read_text(encoding="utf-8")
    frameworks = (FRONTEND_DIR / "js" / "pages" / "frameworks.js").read_text(encoding="utf-8")

    assert "this.allOperators[0]" in operators
    assert "await this.selectOperator(first)" in operators
    assert "this.frameworks[0]?.name" in frameworks
    assert "await this.loadFramework()" in frameworks


def test_screening_assistant_uses_existing_strategy_api_and_pending_semantics():
    prompt = chat._build_system_prompt(
        {
            "page": "screening-strategies",
            "screening_strategy": {
                "id": "user_strategy",
                "name": "测试",
                "is_builtin": False,
                "definition": {"filters": [], "ranking": []},
            },
            "available_fields": [{"id": "roe_avg_3y", "name": "近三年平均 ROE"}],
        }
    )

    assert "PUT /api/research/screening-strategies/{id}" in prompt
    assert "available_fields" in prompt
    assert "50 亿元必须写成 500000 万元" in prompt
    assert "不得声称已经提交或生效" in prompt

    frontend = (FRONTEND_DIR / "js" / "pages" / "chat.js").read_text(encoding="utf-8")
    assert "ctx.screening_strategy?.name" in frontend
    assert "'/api/research/screening-strategies'" in frontend
    assert "当前页面允许的结构化编辑 API" in frontend
    assert "function prepareActionBody(action)" in frontend
    assert "'screening-current': '截面选股'" in frontend
    assert "'screening-backtest': '历史验证'" in frontend
    assert "body.name = body.name || current.name" in frontend
    assert "的单位是万元，当前数值异常偏大" in frontend

    api_client = (FRONTEND_DIR / "js" / "utils" / "api.js").read_text(encoding="utf-8")
    assert "Array.isArray(body.detail)" in api_client
    assert "Network error: ${error.message}" not in api_client


def test_cross_section_presets_reuse_independent_screening_strategy(tmp_path, monkeypatch):
    monkeypatch.setattr(screening_strategies, "SCREENING_DB_PATH", tmp_path / "research.db")
    created = screening_strategies.create_strategy(
        "我的价值策略",
        "测试",
        {
            "filters": [{"field": "pb", "mode": "value", "max": 2}],
            "ranking": [{"field": "bp", "weight": 1, "direction": "desc"}],
        },
    )
    presets = asyncio.run(research.cross_section_presets())

    value = next(item for item in presets if item["id"] == created["id"])
    assert value["filter_count"] > 0
    assert value["factor_count"] > 0
    assert value["interval"]
    assert value["top_n"] > 0
    assert not any(item["id"].startswith("builtin_") for item in presets)


def test_screening_status_uses_latest_local_indicator_snapshot(monkeypatch):
    monkeypatch.setattr(research, "get_active_provider_name", lambda: "baostock")
    monkeypatch.setattr(
        research,
        "_read_dataset_catalog",
        lambda provider: {
            ("daily", "raw"): {"partitions": 20, "latest_date": "2026-08-18"},
            ("daily", "indicator"): {"partitions": 20, "latest_date": "2026-08-14"},
        },
    )

    status = asyncio.run(research.screening_status())

    assert status == {
        "provider": "baostock",
        "latest_date": "2026-08-14",
        "available": True,
    }


def test_identical_screening_previews_share_one_calculation(monkeypatch):
    calls = 0

    def fake_screen(_date, _config, _top_n):
        nonlocal calls
        calls += 1
        time.sleep(0.05)
        return SimpleNamespace(
            effective_date="2026-08-17",
            total_stocks=5539,
            after_basic_filter=273,
            candidates=pd.DataFrame(
                [{"ts_code": "600000.SH", "stock_name": "浦发银行"}]
            ),
        )

    monkeypatch.setattr(research, "_validate_screening_definition", lambda value: value)
    monkeypatch.setattr(research, "_require_screening_coverage", lambda *args, **kwargs: None)
    monkeypatch.setattr(research, "_screening_data_revision", lambda _provider: "revision-1")
    monkeypatch.setattr(research, "get_active_provider_name", lambda: "baostock")
    monkeypatch.setattr(research, "screen_at_date", fake_screen)
    clear_screening_preview_cache()
    request = research.ScreeningPreviewRequest(
        definition={"filters": [], "ranking": []},
        as_of_date="2026-08-17",
        top_n=10,
    )

    async def run_twice():
        return await asyncio.gather(
            research.preview_screening(request),
            research.preview_screening(request),
        )

    first, second = asyncio.run(run_twice())

    assert calls == 1
    assert first == second
    assert first["funnel"] == {"universe": 5539, "after_filters": 273, "selected": 1}

    forced = request.model_copy(update={"force": True})
    asyncio.run(research.preview_screening(forced))
    assert calls == 2
    clear_screening_preview_cache()


def test_cross_section_job_uses_isolated_run_directory(tmp_path, monkeypatch):
    progress_events = []

    def fake_screen(config, progress=None):
        config.get_backtest_dir().mkdir(parents=True, exist_ok=True)
        progress({
            "phase": "screening",
            "message": "截面完成",
            "current": 1,
            "total": 1,
            "percent": 100,
            "current_date": "2020-06-30",
        })
        progress_events.append("screening")
        return ["2020-06-30"]

    def fake_eval(config, numeric_only=False, progress=None):
        assert numeric_only is True
        progress({
            "phase": "outcomes",
            "message": "收益采集完成",
            "current": 12,
            "total": 12,
            "percent": 90,
            "cached": 4,
        })
        progress_events.append("evaluation")
        run_dir = config.get_backtest_dir()
        summary = {
            "strategy": config.name,
            "version": config.version,
            "dates": ["2020-06-30"],
            "interval": "6m",
            "slices": [{"cutoff_date": "2020-06-30", "screen_count": 12}],
            "performance": {
                "screen_all": {
                    "label": "筛选池",
                    "stats": {"6个月": {"count": 12}},
                    "slices": [
                        {
                            "cutoff_date": "2020-06-30",
                            "count": 12,
                            "returns": {"6个月": 0.12},
                        }
                    ],
                }
            },
        }
        (run_dir / "backtest_summary_20200101_0000.json").write_text(
            json.dumps(summary), encoding="utf-8"
        )
        report = run_dir / "report.md"
        report.write_text("ok", encoding="utf-8")
        return report

    import src.backtest.pipeline as pipeline

    monkeypatch.setattr(pipeline, "step_screen", fake_screen)
    monkeypatch.setattr(pipeline, "step_eval", fake_eval)
    manager = research_jobs.ResearchJobManager(tmp_path / "runs")
    started = manager.start_cross_section(
        {
            "screening_strategy_id": "demo",
            "screening_strategy_name": "Demo",
            "screening_strategy_snapshot": {
                "id": "demo",
                "name": "Demo",
                "updated_at": "1.0",
                "definition": {
                    "exclude_st": True,
                    "industry_cap": 0,
                    "filters": [],
                    "ranking": [],
                },
            },
            "start_date": "2020-01-01",
            "end_date": "2020-12-31",
            "interval": "6m",
            "top_n": 20,
        }
    )

    job = started
    for _ in range(100):
        job = manager.get_job(str(started["id"]))
        if job["status"] not in {"queued", "running"}:
            break
        time.sleep(0.01)

    assert job["status"] == "completed"
    assert job["result"]["slices"][0]["screen_count"] == 12
    assert job["result"]["performance"]["screen_all"]["slices"][0]["returns"]["6个月"] == 0.12
    assert Path(job["result"]["summary_path"]).is_relative_to(tmp_path / "runs")
    assert progress_events == ["screening", "evaluation"]
    assert job["progress"]["phase"] == "completed"
    assert job["progress"]["overall_percent"] == 100


def test_screening_strategy_crud_and_snapshot_config(tmp_path, monkeypatch):
    monkeypatch.setattr(screening_strategies, "SCREENING_DB_PATH", tmp_path / "research.db")
    definition = {
        "exclude_st": True,
        "industry_cap": 2,
        "filters": [
            {"field": "pb", "mode": "value", "min": 0.01, "max": 1.5},
            {"field": "bp", "mode": "percentile", "percentile_min": 70},
        ],
        "ranking": [
            {"field": "bp", "weight": 2, "direction": "desc", "na_handling": "worst"}
        ],
    }

    created = screening_strategies.create_strategy("价值筛选", "测试", definition)
    loaded = screening_strategies.get_strategy(created["id"])
    assert loaded["definition"]["industry_cap"] == 2

    config = screening_strategies.build_config(
        loaded,
        start_date="2020-01-01",
        end_date="2021-01-01",
        interval="3m",
        top_n=30,
        run_dir=tmp_path / "run",
    )
    assert config.get_filters()[1]["percentile_min"] == 70
    assert config.get_scoring_factors()[0]["method"] == "percentile"
    assert "framework" not in config.raw
    assert "llm" not in config.raw

    updated = screening_strategies.update_strategy(
        created["id"],
        "价值筛选 v2",
        "更新",
        {**definition, "filters": [{**definition["filters"][0], "max": 2.0}, *definition["filters"][1:]]},
    )
    assert updated["name"] == "价值筛选 v2"
    screening_strategies.delete_strategy(created["id"])
    assert screening_strategies.list_strategies() == []


def test_listing_purges_retired_builtins_and_keeps_user_strategies(tmp_path, monkeypatch):
    monkeypatch.setattr(screening_strategies, "SCREENING_DB_PATH", tmp_path / "research.db")
    user = screening_strategies.create_strategy("我的策略", "保留", {"filters": [], "ranking": []})
    retired = screening_strategies.create_strategy("旧内置策略", "清理", {"filters": [], "ranking": []})
    with screening_strategies._connect() as connection:
        connection.execute(
            "UPDATE screening_strategies SET is_builtin = 1, source = ? WHERE id = ?",
            ("retired.yaml", retired["id"]),
        )

    strategies = screening_strategies.list_strategies()

    assert [item["id"] for item in strategies] == [user["id"]]
    with screening_strategies._connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM screening_strategies WHERE is_builtin = 1"
        ).fetchone()[0] == 0


def test_screening_layer_does_not_scan_qualitative_strategy_directory():
    service_source = Path(screening_strategies.__file__).read_text(encoding="utf-8")
    router_source = Path(research.__file__).read_text(encoding="utf-8")
    assert 'PROJECT_ROOT / "strategies"' not in service_source
    assert 'PROJECT_ROOT / "strategies"' not in router_source
    assert "sync_builtin_strategies" not in service_source


def test_percentile_filter_and_weighted_ranking_are_numerical():
    frame = pd.DataFrame(
        {
            "quality": [1.0, 2.0, 3.0, 4.0],
            "valuation": [40.0, 30.0, 20.0, 10.0],
        }
    )
    filtered = _apply_filters(
        frame.copy(),
        [{"field": "quality", "percentile_min": 50, "enabled": True}],
    )
    assert filtered["quality"].tolist() == [3.0, 4.0]

    scores = _compute_scores(
        frame,
        [
            {"field": "quality", "weight": 1, "direction": "desc", "method": "percentile"},
            {"field": "valuation", "weight": 1, "direction": "asc", "method": "percentile"},
        ],
    )
    assert scores.is_monotonic_increasing


def test_market_curve_keeps_per_snapshot_forward_returns(monkeypatch):
    import src.backtest.pipeline as pipeline
    from src.data import api as data_api

    monkeypatch.setattr(
        data_api,
        "get_index_daily",
        lambda code, start, end: pd.DataFrame(
            {
                "trade_date": ["2020-01-31", "2020-02-28", "2020-04-30"],
                "close": [100.0, 110.0, 121.0],
            }
        ),
    )

    slices = pipeline._collect_index_return_slices(
        ["2020-01-31"],
        [{"months": 1, "label": "1个月"}, {"months": 3, "label": "3个月"}],
    )

    assert round(slices[0]["returns_1m"][0], 6) == 0.1
    assert round(slices[0]["returns_3m"][0], 6) == 0.21


def test_market_curve_omits_unelapsed_forward_returns(monkeypatch):
    import src.backtest.pipeline as pipeline
    from src.data import api as data_api

    monkeypatch.setattr(
        data_api,
        "get_index_daily",
        lambda code, start, end: pd.DataFrame(
            {
                "trade_date": ["2026-07-31", "2026-08-17", "2026-08-31"],
                "close": [100.0, 103.0, 110.0],
            }
        ),
    )

    slices = pipeline._collect_index_return_slices(
        ["2026-07-31"],
        [{"months": 1, "label": "1个月"}, {"months": 3, "label": "3个月"}],
        as_of_date="2026-08-18",
    )

    assert slices[0]["returns_1m"] == []
    assert slices[0]["returns_3m"] == []


def test_outcome_cache_invalidates_old_semantics_and_newly_elapsed_horizon():
    import src.backtest.pipeline as pipeline

    current_payload = {
        "_schema_version": pipeline.OUTCOME_CACHE_SCHEMA_VERSION,
        "collection_date": "2026-08-18",
    }

    assert not pipeline._outcome_cache_is_current(
        "2026-07-31",
        {"collection_date": "2026-08-18"},
        as_of_date="2026-08-18",
    )
    assert pipeline._outcome_cache_is_current(
        "2026-07-31",
        current_payload,
        as_of_date="2026-08-29",
    )
    assert not pipeline._outcome_cache_is_current(
        "2026-07-31",
        current_payload,
        as_of_date="2026-08-30",
    )


def test_numeric_backtest_artifacts_have_no_qualitative_fields(tmp_path):
    strategy = {
        "id": "numeric",
        "name": "纯数值策略",
        "updated_at": "1",
        "definition": {"filters": [], "ranking": []},
    }
    config = screening_strategies.build_config(
        strategy,
        start_date="2020-06-30",
        end_date="2020-06-30",
        interval="6m",
        top_n=20,
        run_dir=tmp_path / "run",
    )
    slices = [
        EvalSlice(
            cutoff_date="2020-06-30",
            candidates=pd.DataFrame([{"ts_code": "600000.SH"}]),
        )
    ]
    performance = {
        "screen_all": {
            "label": "筛选池",
            "desc": "数值筛选",
            "stats": {"6个月": {"count": 0}},
            "slices": [
                {
                    "cutoff_date": "2020-06-30",
                    "count": 1,
                    "returns_1m": [0.02],
                    "returns_3m": [0.06],
                    "returns_6m": [0.12],
                    "returns_12m": [0.18],
                }
            ],
        }
    }

    report = _format_eval_report(slices, performance, config, numeric_only=True)
    assert "Agent" not in report
    assert "LLM" not in report

    summary_path = tmp_path / "summary.json"
    _save_eval_json(slices, performance, config, summary_path, numeric_only=True)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["outcome_schema_version"] == OUTCOME_CACHE_SCHEMA_VERSION
    assert summary["return_basis"] == "hfq_adjusted_close"
    assert summary["evaluation_semantics"] == "forward_return"
    assert "agent_count" not in summary["slices"][0]
    assert "agent_scores" not in summary["slices"][0]
    curve_slice = summary["performance"]["screen_all"]["slices"][0]
    assert curve_slice == {
        "cutoff_date": "2020-06-30",
        "count": 1,
        "returns": {
            "1个月": 0.02,
            "3个月": 0.06,
            "6个月": 0.12,
            "12个月": 0.18,
        },
    }
