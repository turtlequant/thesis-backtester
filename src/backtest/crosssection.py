"""
截面分析批量运行器

在多个时间点运行完整分析流程，支持：
  1. 单股票多截面
  2. 多股票单截面
  3. 批量截面（多股票×多时间点）

用法:
    python -m src.backtest.crosssection 601288.SH 2023-12-31,2024-06-30,2024-12-31
"""
import sqlite3
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path

from src.data.settings import ANALYSIS_DB_PATH
from src.analyzer.analysis_runner import (
    prepare_analysis, init_db, list_runs, save_report,
)


def _resolve_backtest_dir():
    """获取回测数据目录"""
    from src.engine.config import get_default_config
    return get_default_config().get_backtest_dir()


def plan_crosssections(
    ts_codes: List[str],
    cutoff_dates: List[str],
    skip_existing: bool = True,
) -> List[Dict[str, str]]:
    """
    规划截面分析任务列表

    Args:
        ts_codes: 股票代码列表
        cutoff_dates: 截止日期列表
        skip_existing: 跳过已有completed分析的截面

    Returns:
        待执行任务列表 [{"ts_code": ..., "cutoff_date": ...}, ...]
    """
    init_db()
    tasks = []

    # 查询已有分析
    existing = set()
    if skip_existing:
        conn = sqlite3.connect(str(ANALYSIS_DB_PATH))
        rows = conn.execute(
            "SELECT ts_code, cutoff_date FROM analysis_runs WHERE status='completed'"
        ).fetchall()
        conn.close()
        existing = {(r[0], r[1]) for r in rows}

    for ts_code in ts_codes:
        for cutoff_date in cutoff_dates:
            if skip_existing and (ts_code, cutoff_date) in existing:
                continue
            tasks.append({"ts_code": ts_code, "cutoff_date": cutoff_date})

    return tasks


def prepare_batch(
    ts_codes: List[str],
    cutoff_dates: List[str],
    skip_existing: bool = True,
) -> List[Dict[str, Any]]:
    """
    批量准备截面分析（生成快照+prompt），不执行分析

    Returns:
        准备结果列表，每个包含 run_id, prompt_path 等
    """
    tasks = plan_crosssections(ts_codes, cutoff_dates, skip_existing)

    if not tasks:
        print("所有截面已有分析结果，无需重复执行")
        return []

    print(f"需要准备 {len(tasks)} 个截面分析:")
    for t in tasks:
        print(f"  {t['ts_code']} @ {t['cutoff_date']}")
    print()

    results = []
    for i, task in enumerate(tasks):
        print(f"\n{'='*60}")
        print(f"[{i+1}/{len(tasks)}] {task['ts_code']} @ {task['cutoff_date']}")
        print(f"{'='*60}")
        try:
            result = prepare_analysis(task['ts_code'], task['cutoff_date'])
            result['status'] = 'prepared'
            results.append(result)
        except Exception as e:
            print(f"  准备失败: {e}")
            results.append({
                'ts_code': task['ts_code'],
                'cutoff_date': task['cutoff_date'],
                'status': 'error',
                'error': str(e),
            })

    return results


def get_crosssection_summary(
    ts_code: str,
    cutoff_dates: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    获取单只股票在多个截面的分析结果汇总

    Returns:
        按截面日期排序的分析结果列表
    """
    init_db()
    conn = sqlite3.connect(str(ANALYSIS_DB_PATH))
    conn.row_factory = sqlite3.Row

    if cutoff_dates:
        placeholders = ','.join(['?' for _ in cutoff_dates])
        rows = conn.execute(
            f"SELECT r.*, s.stream, s.turtle_rating, s.recommendation, "
            f"s.buy_logic, s.ev_fcf_multiple, s.safety_margin_pct, s.overall_score "
            f"FROM analysis_runs r "
            f"LEFT JOIN synthesis s ON r.id = s.run_id "
            f"WHERE r.ts_code=? AND r.cutoff_date IN ({placeholders}) "
            f"AND r.status='completed' "
            f"ORDER BY r.cutoff_date",
            [ts_code] + cutoff_dates
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT r.*, s.stream, s.turtle_rating, s.recommendation, "
            "s.buy_logic, s.ev_fcf_multiple, s.safety_margin_pct, s.overall_score "
            "FROM analysis_runs r "
            "LEFT JOIN synthesis s ON r.id = s.run_id "
            "WHERE r.ts_code=? AND r.status='completed' "
            "ORDER BY r.cutoff_date",
            (ts_code,)
        ).fetchall()

    conn.close()
    return [dict(row) for row in rows]


def compare_crosssections(
    ts_code: str,
    cutoff_dates: Optional[List[str]] = None,
) -> str:
    """
    对比多个截面的分析结果，生成对比报告（Markdown）

    Returns:
        对比报告 Markdown 文本
    """
    results = get_crosssection_summary(ts_code, cutoff_dates)

    if not results:
        return f"没有找到 {ts_code} 的已完成分析结果"

    if len(results) < 2:
        return f"只有 {len(results)} 个截面，需要至少2个截面才能对比"

    lines = [
        f"# {ts_code} 截面对比分析",
        "",
        f"**截面数量**: {len(results)}",
        f"**时间跨度**: {results[0]['cutoff_date']} ~ {results[-1]['cutoff_date']}",
        "",
        "## 核心指标对比",
        "",
        "| 截面日期 | 流派 | 龟级 | 建议 | 安全边际 | 评分 |",
        "|---------|------|------|------|---------|------|",
    ]

    for r in results:
        safety = f"{r.get('safety_margin_pct', 0):.1f}%" if r.get('safety_margin_pct') else "N/A"
        score = f"{r.get('overall_score', 0):.0f}" if r.get('overall_score') else "N/A"
        lines.append(
            f"| {r['cutoff_date']} "
            f"| {r.get('stream', 'N/A')} "
            f"| {r.get('turtle_rating', 'N/A')} "
            f"| {r.get('recommendation', 'N/A')} "
            f"| {safety} "
            f"| {score} |"
        )

    # 分析变化趋势
    lines.extend(["", "## 变化趋势分析", ""])

    # 流派一致性
    streams = [r.get('stream', '') for r in results if r.get('stream')]
    if len(set(streams)) == 1:
        lines.append(f"- **流派判定一致**: 所有截面均为「{streams[0]}」")
    else:
        lines.append(f"- **流派判定变化**: {' → '.join(streams)}")

    # 龟级变化
    turtles = [r.get('turtle_rating', '') for r in results if r.get('turtle_rating')]
    if len(set(turtles)) == 1:
        lines.append(f"- **龟级评定稳定**: 所有截面均为「{turtles[0]}」")
    else:
        lines.append(f"- **龟级评定变化**: {' → '.join(turtles)}")

    # 建议变化
    recs = [r.get('recommendation', '') for r in results if r.get('recommendation')]
    if recs:
        lines.append(f"- **建议变化**: {' → '.join(recs)}")

    # 评分趋势
    scores = [(r['cutoff_date'], r.get('overall_score', 0)) for r in results if r.get('overall_score')]
    if len(scores) >= 2:
        first, last = scores[0][1], scores[-1][1]
        direction = "上升" if last > first else ("下降" if last < first else "持平")
        lines.append(f"- **评分趋势**: {first:.0f} → {last:.0f} ({direction})")

    # 买入逻辑对比
    lines.extend(["", "## 各截面买入逻辑", ""])
    for r in results:
        logic = r.get('buy_logic', '无')
        lines.append(f"**{r['cutoff_date']}**: {logic}")
        lines.append("")

    return '\n'.join(lines)


def save_comparison(ts_code: str, report: str) -> Path:
    """保存截面对比报告"""
    bt_dir = _resolve_backtest_dir()
    bt_dir.mkdir(parents=True, exist_ok=True)
    path = bt_dir / f"{ts_code}_crosssection_comparison.md"
    path.write_text(report, encoding='utf-8')
    return path


# ==================== CLI ====================

def main():
    import sys
    if len(sys.argv) < 3:
        print("用法: python -m src.backtest.crosssection <ts_code> <cutoff_dates>")
        print("示例: python -m src.backtest.crosssection 601288.SH 2023-12-31,2024-06-30,2024-12-31")
        print("")
        print("子命令:")
        print("  plan    - 仅规划任务")
        print("  prepare - 准备快照和prompt")
        print("  compare - 对比已有分析结果")
        sys.exit(1)

    ts_code = sys.argv[1]
    dates_str = sys.argv[2]

    subcmd = sys.argv[3] if len(sys.argv) > 3 else "plan"

    cutoff_dates = [d.strip() for d in dates_str.split(',')]

    if subcmd == "plan":
        tasks = plan_crosssections([ts_code], cutoff_dates)
        if tasks:
            print(f"需要执行 {len(tasks)} 个截面分析:")
            for t in tasks:
                print(f"  {t['ts_code']} @ {t['cutoff_date']}")
        else:
            print("所有截面已有分析结果")

    elif subcmd == "prepare":
        prepare_batch([ts_code], cutoff_dates)

    elif subcmd == "compare":
        report = compare_crosssections(ts_code, cutoff_dates)
        print(report)
        path = save_comparison(ts_code, report)
        print(f"\n对比报告已保存: {path}")

    else:
        print(f"未知子命令: {subcmd}")


if __name__ == '__main__':
    main()
