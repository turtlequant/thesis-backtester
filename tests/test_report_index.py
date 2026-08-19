import json

from src.desktop.api.routers import chat
from src.desktop.api.services import report_index


def _write_report(
    project_root,
    *,
    score=72,
    ts_code="600000.SH",
    stock_name="浦发银行",
    cutoff_date="2026-06-30",
    recommendation="买入",
):
    strategy_dir = project_root / "strategies" / "demo"
    live_dir = strategy_dir / "live" / f"{ts_code}_{cutoff_date}"
    live_dir.mkdir(parents=True, exist_ok=True)
    (strategy_dir / "strategy.yaml").write_text(
        """
meta:
  name: 示例研究框架
  version: '1.0'
framework:
  chapters:
    - id: ch01_quality
      chapter: 1
      title: 经营质量
      operators: []
      dependencies: []
""".strip(),
        encoding="utf-8",
    )
    structured = live_dir / f"{ts_code}_{cutoff_date}_structured.json"
    structured.write_text(
        json.dumps(
            {
                "metadata": {
                    "ts_code": ts_code,
                    "stock_name": stock_name,
                    "cutoff_date": cutoff_date,
                    "model": "test-model",
                    "elapsed_seconds": 12.5,
                },
                "synthesis": {
                    "综合评分": score,
                    "最终建议": recommendation,
                    "核心逻辑": "盈利稳定且估值偏低",
                    "关键风险": ["息差收窄", "信用成本上升"],
                    "信心水平": "中",
                },
                "chapter_outputs": {"ch01_quality": {"结论": "通过"}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    structured.with_name(f"{ts_code}_{cutoff_date}_report.md").write_text(
        "# ch01_quality\n\n## 质量结论\n\n经营质量通过。",
        encoding="utf-8",
    )
    return structured


def test_report_index_search_is_filtered_and_paginated_in_sql(tmp_path):
    project_root = tmp_path / "project"
    db_path = tmp_path / "research.db"
    runs_root = tmp_path / "runs"
    _write_report(
        project_root,
        ts_code="600000.SH",
        stock_name="浦发银行",
        cutoff_date="2026-06-30",
    )
    _write_report(
        project_root,
        ts_code="600000.SH",
        stock_name="浦发银行",
        cutoff_date="2025-06-30",
        recommendation="观望",
    )
    _write_report(
        project_root,
        ts_code="000001.SZ",
        stock_name="平安银行",
        cutoff_date="2024-06-30",
    )

    first = report_index.search_reports(
        project_root,
        db_path,
        runs_root,
        page=1,
        page_size=1,
        query="浦发",
        refresh=True,
    )
    second = report_index.search_reports(
        project_root,
        db_path,
        runs_root,
        page=2,
        page_size=1,
        query="浦发",
    )

    assert first["index_total"] == 3
    assert first["total"] == 2
    assert first["pages"] == 2
    assert len(first["items"]) == 1
    assert first["items"][0]["cutoff_date"] == "2026-06-30"
    assert second["page"] == 2
    assert second["items"][0]["cutoff_date"] == "2025-06-30"
    assert first["frameworks"] == [
        {"id": "demo", "name": "示例研究框架", "count": 3}
    ]

    watched = report_index.search_reports(
        project_root,
        db_path,
        runs_root,
        recommendation="观望",
        start_date="2025-01-01",
        end_date="2025-12-31",
    )
    assert watched["total"] == 1
    assert watched["items"][0]["recommendation"] == "观望"


def test_report_index_reconciles_files_and_latest_batch_origin(tmp_path):
    project_root = tmp_path / "project"
    structured = _write_report(project_root)
    runs_root = tmp_path / "qualitative_runs"
    run_dir = runs_root / "latest01"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "id": "latest01",
                "kind": "latest_judgement",
                "rows": [{"report_path": str(structured)}],
            }
        ),
        encoding="utf-8",
    )
    db_path = tmp_path / "research.db"

    first = report_index.sync_report_index(
        project_root,
        db_path=db_path,
        qualitative_runs_root=runs_root,
    )
    reports = report_index.list_reports(
        project_root,
        db_path=db_path,
        qualitative_runs_root=runs_root,
    )

    assert first["indexed"] == 1
    assert reports[0]["framework_name"] == "示例研究框架"
    assert reports[0]["stock_name"] == "浦发银行"
    assert reports[0]["core_logic"] == "盈利稳定且估值偏低"
    assert reports[0]["risks"] == "息差收窄；信用成本上升"
    assert reports[0]["origin"] == "latest_judgement"
    assert reports[0]["origin_run_id"] == "latest01"

    detail = report_index.get_report(
        reports[0]["id"],
        project_root,
        db_path,
        qualitative_runs_root=runs_root,
    )
    assert detail["chapter_titles"] == {"ch01_quality": "经营质量"}
    assert "经营质量通过" in detail["report_text"]

    assert report_index.delete_report(reports[0]["id"], project_root, db_path)
    assert not structured.exists()
    assert not structured.with_name("600000.SH_2026-06-30_report.md").exists()


def test_report_index_survives_portable_workspace_move(tmp_path):
    old_root = tmp_path / "old_workspace"
    structured = _write_report(old_root)
    runs_root = tmp_path / "qualitative_runs"
    run_dir = runs_root / "latest01"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "id": "latest01",
                "kind": "latest_judgement",
                "rows": [{"report_path": str(structured)}],
            }
        ),
        encoding="utf-8",
    )
    db_path = tmp_path / "research.db"
    report_index.sync_report_index(
        old_root,
        db_path=db_path,
        qualitative_runs_root=runs_root,
    )

    new_root = tmp_path / "new_workspace"
    old_root.rename(new_root)
    counts = report_index.sync_report_index(
        new_root,
        db_path=db_path,
        qualitative_runs_root=runs_root,
    )
    reports = report_index.list_reports(
        new_root,
        db_path=db_path,
        qualitative_runs_root=runs_root,
    )

    assert counts == {"indexed": 1, "unchanged": 0, "removed": 0, "errors": 0}
    assert len(reports) == 1
    assert reports[0]["origin"] == "latest_judgement"
    assert str(new_root) in reports[0]["file_path"]


def test_chat_assistant_receives_the_complete_indexed_report(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    structured = _write_report(project_root)
    markdown = structured.with_name("600000.SH_2026-06-30_report.md")
    complete_report = (
        "# 第一章\n\n开头结论\n\n"
        + "完整章节证据。" * 900
        + "\n\n# 最终结论\n\n这是报告末尾不可丢失的结论。"
    )
    markdown.write_text(complete_report, encoding="utf-8")
    db_path = tmp_path / "research.db"
    runs_root = tmp_path / "runs"
    reports = report_index.list_reports(project_root, db_path, runs_root)

    monkeypatch.setattr(report_index, "REPORT_DB_PATH", db_path)
    monkeypatch.setattr(report_index, "QUALITATIVE_RUNS_ROOT", runs_root)
    monkeypatch.setattr(chat, "_project_root", project_root)

    content = chat._load_report_context(reports[0]["id"])
    prompt = chat._build_system_prompt(
        {"page": "reports", "report_id": reports[0]["id"]}
    )

    assert len(complete_report) > 4000
    assert content == complete_report
    assert "这是报告末尾不可丢失的结论。" in prompt
    assert "报告内容已截断" not in prompt
    assert f"完整正文，共 {len(complete_report)} 字符" in prompt


def test_report_index_updates_changed_files_and_prunes_deleted_files(tmp_path):
    project_root = tmp_path / "project"
    structured = _write_report(project_root, score=60)
    db_path = tmp_path / "research.db"
    runs_root = tmp_path / "runs"
    report_index.sync_report_index(
        project_root, db_path=db_path, qualitative_runs_root=runs_root
    )

    _write_report(project_root, score=88)
    updated = report_index.list_reports(
        project_root, db_path=db_path, qualitative_runs_root=runs_root
    )
    assert updated[0]["score"] == 88

    structured.unlink()
    counts = report_index.sync_report_index(
        project_root, db_path=db_path, qualitative_runs_root=runs_root
    )
    assert counts["removed"] == 1
    assert report_index.list_reports(
        project_root, db_path=db_path, qualitative_runs_root=runs_root
    ) == []


def test_report_index_includes_read_only_historical_backtest_samples(
    tmp_path, monkeypatch
):
    project_root = tmp_path / "project"
    strategy_dir = project_root / "strategies" / "demo"
    reports_dir = strategy_dir / "backtest" / "agent_reports"
    screen_dir = strategy_dir / "backtest" / "screen_results"
    reports_dir.mkdir(parents=True)
    screen_dir.mkdir(parents=True)
    (strategy_dir / "strategy.yaml").write_text(
        """
meta:
  name: 示例历史框架
  version: '2.0'
framework:
  chapters:
    - id: ch01
      chapter: 1
      title: 历史证据
      operators: []
      dependencies: []
""".strip(),
        encoding="utf-8",
    )
    (screen_dir / "screen_2024-12-31.csv").write_text(
        "ts_code,stock_name,industry\n600000.SH,浦发银行,银行\n",
        encoding="utf-8",
    )
    structured = reports_dir / "600000.SH_2024-12-31_structured.json"
    structured.write_text(
        json.dumps(
            {
                "metadata": {"ts_code": "600000.SH", "cutoff_date": "2024-12-31"},
                "synthesis": {"综合评分": 70, "最终建议": "观望"},
                "chapter_outputs": {"ch01": {"结论": "历史样本"}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    structured.with_name("600000.SH_2024-12-31_report.md").write_text(
        "# 历史样本", encoding="utf-8"
    )
    db_path = tmp_path / "research.db"

    reports = report_index.list_reports(project_root, db_path, tmp_path / "runs")

    assert len(reports) == 1
    report = reports[0]
    assert report["origin"] == "historical_backtest"
    assert report["read_only"] is True
    assert report["stock_name"] == "浦发银行"
    assert "historical_backtest" in report["id"]
    monkeypatch.setattr(report_index, "REPORT_DB_PATH", db_path)
    monkeypatch.setattr(report_index, "QUALITATIVE_RUNS_ROOT", tmp_path / "runs")
    monkeypatch.setattr(chat, "_project_root", project_root)
    assert chat._load_report_context(report["id"]) == "# 历史样本"
    assert report_index.delete_report(report["id"], project_root, db_path) is False
    assert structured.exists()
