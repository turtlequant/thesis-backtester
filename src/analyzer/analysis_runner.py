"""
分析流程编排器

编排顺序分析流程，管理章节间依赖。
支持通过 StrategyConfig 配置不同的分析框架。

用法:
    python -m src.analyzer.analysis_runner 601288.SH 2024-06-30
    python -m src.analyzer.analysis_runner 601288.SH 2024-06-30 --strategy strategies/v556_value/strategy.yaml
"""
import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, TYPE_CHECKING

from src.data.snapshot import create_snapshot, snapshot_to_markdown, save_snapshot, StockSnapshot
from src.data.settings import ANALYSIS_DB_PATH
from .framework_parser import load_all_chunks, CHAPTER_DEFS
from .prompt_builder import build_full_analysis_prompt, build_chapter_prompt

if TYPE_CHECKING:
    from src.engine.config import StrategyConfig


def _resolve_dirs(config: Optional["StrategyConfig"] = None):
    """获取 prompts/reports 目录，优先从 config 读取"""
    if config is not None:
        bt_dir = config.get_backtest_dir()
    else:
        from src.engine.config import get_default_config
        bt_dir = get_default_config().get_backtest_dir()
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
                framework_version TEXT DEFAULT 'V5.5.6',
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
    mode: str = "full",
    blind_mode: bool = False,
    config: Optional["StrategyConfig"] = None,
) -> Dict[str, Any]:
    """
    准备分析任务

    Args:
        ts_code: 股票代码
        cutoff_date: 截止日期
        mode: "full" 完整10章分析, "single" 单章
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

    # 2. 构建分析prompt
    print(f"\n[2/3] 构建分析prompt...")
    prompt = build_full_analysis_prompt(ts_code, cutoff_date, snapshot, blind_mode=blind_mode, config=config)

    prompts_dir, _ = _resolve_dirs(config)
    prompts_dir.mkdir(parents=True, exist_ok=True)
    prompt_filename = f"{ts_code}_{cutoff_date}_prompt.md"
    prompt_path = prompts_dir / prompt_filename
    prompt_path.write_text(prompt, encoding='utf-8')
    print(f"  Prompt已保存: {prompt_path}")
    print(f"  Prompt长度: {len(prompt)} 字符")

    # 3. 记录到数据库
    print(f"\n[3/3] 记录分析任务...")
    fw_version = config.get_framework_version_tag() if config else 'V5.5.6'
    with sqlite3.connect(str(ANALYSIS_DB_PATH)) as conn:
        conn.execute(
            "INSERT INTO analysis_runs (id, ts_code, cutoff_date, framework_version, status, prompt_path, snapshot_path) "
            "VALUES (?, ?, ?, ?, 'pending', ?, ?)",
            (run_id, ts_code, cutoff_date, fw_version, str(prompt_path), str(snapshot_path))
        )
        conn.commit()

    print(f"\n{'='*60}")
    print(f"分析任务已准备就绪")
    print(f"  Run ID: {run_id}")
    print(f"  Prompt: {prompt_path}")
    print(f"{'='*60}")
    print(f"\n下一步: 在 Claude Code 中阅读 prompt 文件并执行分析")
    print(f"  1. 阅读 {prompt_path}")
    print(f"  2. 按10章框架逐章分析")
    print(f"  3. 输出综合研判报告")

    return {
        "run_id": run_id,
        "prompt_path": str(prompt_path),
        "snapshot_path": str(snapshot_path),
        "prompt_length": len(prompt),
    }


def save_report(
    run_id: str,
    report_markdown: str,
    synthesis: Dict[str, Any] = None,
    config: Optional["StrategyConfig"] = None,
) -> Path:
    """
    保存分析报告

    Args:
        run_id: 分析任务ID
        report_markdown: 完整分析报告（Markdown）
        synthesis: 结构化综合研判结果
        config: 策略配置
    """
    init_db()
    _, reports_dir = _resolve_dirs(config)
    reports_dir.mkdir(parents=True, exist_ok=True)

    # 保存报告文件
    report_path = reports_dir / f"{run_id}_report.md"
    report_path.write_text(report_markdown, encoding='utf-8')

    with sqlite3.connect(str(ANALYSIS_DB_PATH)) as conn:
        # 更新运行状态
        conn.execute(
            "UPDATE analysis_runs SET status='completed', completed_at=?, report_path=? WHERE id=?",
            (datetime.now().isoformat(), str(report_path), run_id)
        )

        # 保存综合研判
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


# ==================== CLI ====================

def main():
    import sys
    if len(sys.argv) < 3:
        print("用法: python -m src.analyzer.analysis_runner <ts_code> <cutoff_date> [--strategy <yaml>]")
        print("示例: python -m src.analyzer.analysis_runner 601288.SH 2024-06-30")
        sys.exit(1)

    ts_code = sys.argv[1]
    cutoff_date = sys.argv[2]

    config = None
    if '--strategy' in sys.argv:
        idx = sys.argv.index('--strategy')
        if idx + 1 < len(sys.argv):
            from src.engine.config import StrategyConfig
            config = StrategyConfig.from_yaml(sys.argv[idx + 1])
            print(f"使用策略: {config.name}")

    prepare_analysis(ts_code, cutoff_date, config=config)


if __name__ == '__main__':
    main()
