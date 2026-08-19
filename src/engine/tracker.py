"""
分析任务追踪器

管理分析任务的生命周期：创建、记录、查询、保存报告。
所有配置从 StrategyConfig 读取，引擎层不含任何策略默认值。

用法:
    python -m src.engine.launcher workspace/strategies/v6_value/strategy.yaml analyze 601288.SH 2024-06-30
"""
import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from src.data.snapshot import create_snapshot, snapshot_to_markdown, save_snapshot, StockSnapshot
from src.data.settings import ANALYSIS_DB_PATH

from .config import StrategyConfig


def _resolve_dirs(config: StrategyConfig):
    """获取 prompts/reports 目录"""
    bt_dir = config.get_backtest_dir()
    prompts_dir = bt_dir / "analysis_prompts"
    reports_dir = bt_dir / "analysis_reports"
    return prompts_dir, reports_dir


def init_db():
    """初始化 SQLite 数据库"""
    ANALYSIS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(ANALYSIS_DB_PATH)) as conn:
        c = conn.cursor()

        c.execute("""
            CREATE TABLE IF NOT EXISTS analysis_runs (
                id TEXT PRIMARY KEY,
                ts_code TEXT NOT NULL,
                cutoff_date TEXT NOT NULL,
                framework_version TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                prompt_path TEXT,
                report_path TEXT,
                snapshot_path TEXT
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS chapter_outputs (
                id TEXT PRIMARY KEY,
                run_id TEXT REFERENCES analysis_runs(id),
                chapter_id TEXT NOT NULL,
                structured_output TEXT,
                reasoning TEXT,
                confidence REAL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS synthesis (
                run_id TEXT PRIMARY KEY REFERENCES analysis_runs(id),
                stream TEXT,
                turtle_rating TEXT,
                buy_logic TEXT,
                recommendation TEXT,
                ev_fcf_multiple REAL,
                safety_margin_pct REAL,
                overall_score REAL,
                report_markdown TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS backtest_outcomes (
                id TEXT PRIMARY KEY,
                run_id TEXT REFERENCES analysis_runs(id),
                actual_return_3m REAL,
                actual_return_6m REAL,
                actual_return_12m REAL,
                quality_score REAL,
                quality_detail TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()


def prepare_analysis(
    ts_code: str,
    cutoff_date: str,
    config: StrategyConfig,
    mode: str = "full",
    blind_mode: bool = False,
) -> Dict[str, Any]:
    """
    准备分析任务

    Args:
        ts_code: 股票代码
        cutoff_date: 截止日期
        config: 策略配置
        mode: "full" 完整分析, "single" 单章
        blind_mode: 盲测模式，隐藏公司名称

    Returns:
        {
            "run_id": 分析ID,
            "prompt_path": prompt文件路径,
            "snapshot_path": 快照路径,
            "prompt_length": prompt字符数,
        }
    """
    init_db()

    run_id = f"{ts_code}_{cutoff_date}_{uuid.uuid4().hex[:8]}"

    # 1. 生成数据快照
    print(f"[1/3] 生成数据快照: {ts_code} @ {cutoff_date}")
    snapshot = create_snapshot(ts_code, cutoff_date)
    snapshot_path = save_snapshot(snapshot)
    print(f"  快照已保存: {snapshot_path}")
    print(f"  数据源: {', '.join(snapshot.data_sources)}")
    print(f"  最新报告期: {snapshot.latest_report_period}")
    if snapshot.warnings:
        print(f"  警告: {', '.join(snapshot.warnings)}")
    if blind_mode:
        print(f"  盲测模式: 已启用（公司身份将被隐藏）")

    # 2. 记录到数据库
    print(f"\n[2/2] 记录分析任务...")
    fw_version = config.get_framework_version_tag()
    with sqlite3.connect(str(ANALYSIS_DB_PATH)) as conn:
        conn.execute(
            "INSERT INTO analysis_runs (id, ts_code, cutoff_date, framework_version, status, snapshot_path) "
            "VALUES (?, ?, ?, ?, 'pending', ?)",
            (run_id, ts_code, cutoff_date, fw_version, str(snapshot_path))
        )
        conn.commit()

    print(f"\n{'='*60}")
    print(f"分析任务已准备就绪")
    print(f"  Run ID: {run_id}")
    print(f"{'='*60}")

    return {
        "run_id": run_id,
        "snapshot_path": str(snapshot_path),
    }


def save_report(
    run_id: str,
    report_markdown: str,
    config: StrategyConfig,
    synthesis: Dict[str, Any] = None,
) -> Path:
    """
    保存分析报告

    Args:
        run_id: 分析任务ID
        report_markdown: 完整分析报告（Markdown）
        config: 策略配置
        synthesis: 结构化综合研判结果
    """
    init_db()
    _, reports_dir = _resolve_dirs(config)
    reports_dir.mkdir(parents=True, exist_ok=True)

    report_path = reports_dir / f"{run_id}_report.md"
    report_path.write_text(report_markdown, encoding='utf-8')

    with sqlite3.connect(str(ANALYSIS_DB_PATH)) as conn:
        conn.execute(
            "UPDATE analysis_runs SET status='completed', completed_at=?, report_path=? WHERE id=?",
            (datetime.now().isoformat(), str(report_path), run_id)
        )

        if synthesis:
            conn.execute(
                "INSERT OR REPLACE INTO synthesis "
                "(run_id, stream, turtle_rating, buy_logic, recommendation, "
                "ev_fcf_multiple, safety_margin_pct, overall_score, report_markdown) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    synthesis.get('stream', ''),
                    synthesis.get('turtle_rating', ''),
                    synthesis.get('buy_logic', ''),
                    synthesis.get('recommendation', ''),
                    synthesis.get('ev_fcf_multiple', 0),
                    synthesis.get('safety_margin_pct', 0),
                    synthesis.get('overall_score', 0),
                    report_markdown,
                )
            )

        conn.commit()

    print(f"报告已保存: {report_path}")
    return report_path


def list_runs(ts_code: str = None, limit: int = 20) -> list:
    """列出分析任务"""
    init_db()
    with sqlite3.connect(str(ANALYSIS_DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        if ts_code:
            rows = conn.execute(
                "SELECT * FROM analysis_runs WHERE ts_code=? ORDER BY created_at DESC LIMIT ?",
                (ts_code, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM analysis_runs ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [dict(row) for row in rows]


def get_synthesis(run_id: str) -> Optional[dict]:
    """获取综合研判结果"""
    init_db()
    with sqlite3.connect(str(ANALYSIS_DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM synthesis WHERE run_id=?", (run_id,)).fetchone()
        return dict(row) if row else None
