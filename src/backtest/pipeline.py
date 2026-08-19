"""
回测 Pipeline — 三步独立执行

Step 1: backtest-screen  → 日期生成 + 逐截面筛选 + 保存 CSV
Step 2: backtest-agent   → 读 CSV + 并发 Agent 分析 + 进度/重试/增量
Step 3: backtest-eval    → 读报告 + 采集前向收益 + 多基准绩效评估

用法:
    python -m src.engine.launcher workspace/strategies/v6_value/strategy.yaml backtest-screen
    python -m src.engine.launcher workspace/strategies/v6_value/strategy.yaml backtest-agent
    python -m src.engine.launcher workspace/strategies/v6_value/strategy.yaml backtest-eval
"""
import asyncio
import json
import time
import calendar
from dataclasses import dataclass, field
from datetime import datetime
from dateutil.relativedelta import relativedelta
from pathlib import Path
from typing import Callable, List, Dict, Optional, TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from src.engine.config import StrategyConfig


# ==================== 共享工具 ====================

def _parse_interval(interval: str) -> relativedelta:
    """解析间隔字符串: '6m' → relativedelta(months=6)"""
    s = interval.strip().lower()
    if s.endswith('m'):
        return relativedelta(months=int(s[:-1]))
    elif s.endswith('y'):
        return relativedelta(years=int(s[:-1]))
    elif s.endswith('w'):
        return relativedelta(weeks=int(s[:-1]))
    raise ValueError(f"无法解析间隔: {interval} (支持格式: 6m, 1y, 2w)")


def generate_crosssection_dates(
    start_date: str,
    end_date: str,
    interval: str,
) -> List[str]:
    """从起止日期和间隔生成截面日期列表，月级间隔自动对齐月末"""
    delta = _parse_interval(interval)
    start = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')
    today = datetime.now()

    dates = []
    current = start
    while current <= end and current <= today:
        if hasattr(delta, 'months') and (delta.months or delta.years):
            last_day = calendar.monthrange(current.year, current.month)[1]
            snapped = current.replace(day=last_day)
        else:
            snapped = current
        dates.append(snapped.strftime('%Y-%m-%d'))
        current += delta

    return dates


def _bt_dirs(config: "StrategyConfig"):
    """返回 (screen_dir, reports_dir, bt_dir)"""
    bt_dir = config.get_backtest_dir()
    return bt_dir / "screen_results", bt_dir / "agent_reports", bt_dir


def save_screen_csv(candidates: pd.DataFrame, cutoff_date: str, screen_dir: Path) -> Path:
    """保存筛选结果到 CSV"""
    screen_dir.mkdir(parents=True, exist_ok=True)
    path = screen_dir / f"screen_{cutoff_date}.csv"
    candidates.to_csv(path, index=False, encoding='utf-8-sig')
    return path


def load_screen_csv(cutoff_date: str, screen_dir: Path) -> Optional[pd.DataFrame]:
    """加载已保存的筛选结果"""
    path = screen_dir / f"screen_{cutoff_date}.csv"
    if path.exists():
        return pd.read_csv(path, dtype={'ts_code': str})
    return None


def load_agent_reports(reports_dir: Path, cutoff_date: str) -> Dict[str, dict]:
    """加载指定截面的所有 agent structured.json，返回 {ts_code: data}"""
    results = {}
    if not reports_dir.exists():
        return results
    for f in reports_dir.glob(f"*_{cutoff_date}_structured.json"):
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
            ts_code = data.get('metadata', {}).get('ts_code', '')
            if ts_code:
                results[ts_code] = data
        except Exception:
            continue
    return results


# ==================== Step 1: backtest-screen ====================

def step_screen(
    config: "StrategyConfig",
    progress: Optional[Callable[[Dict[str, object]], None]] = None,
) -> List[str]:
    """
    生成截面日期 + 逐截面筛选 + 保存 CSV

    Returns:
        生成的截面日期列表
    """
    from src.screener.quick_filter import screen_at_date

    dates = generate_crosssection_dates(
        config.get_backtest_start(),
        config.get_backtest_end(),
        config.get_cross_section_interval(),
    )
    top_n = config.get_backtest_top_n()
    screen_dir, _, _ = _bt_dirs(config)

    print(f"回测筛选: {config.name} v{config.version}")
    print(f"  截面: {len(dates)} 个 ({dates[0]} ~ {dates[-1]})")
    print(f"  间隔: {config.get_cross_section_interval()}")
    print(f"  候选数: top {top_n}")
    print(f"  输出: {screen_dir}")
    print()
    if progress:
        progress(
            {
                "phase": "screening",
                "message": f"准备生成 {len(dates)} 个历史截面",
                "current": 0,
                "total": len(dates),
                "percent": 0,
            }
        )

    for i, date in enumerate(dates, 1):
        print(f"[{i}/{len(dates)}] {date}")
        if progress:
            progress(
                {
                    "phase": "screening",
                    "message": f"正在筛选 {date} 截面",
                    "current": i - 1,
                    "total": len(dates),
                    "percent": round((i - 1) * 100 / max(len(dates), 1), 1),
                    "current_date": date,
                }
            )
        screen = screen_at_date(date, top_n=top_n, config=config)
        candidate_count = len(screen.candidates)
        if not screen.candidates.empty:
            csv_path = save_screen_csv(screen.candidates, date, screen_dir)
            n = candidate_count
            tier_info = ""
            if 'tier_rating' in screen.candidates.columns:
                dist = screen.candidates['tier_rating'].value_counts()
                tier_info = " | " + ", ".join(f"{k}:{v}" for k, v in dist.items())
            print(f"  → {n} 只{tier_info} → {csv_path.name}")
        else:
            print("  → 无候选")
        if progress:
            progress(
                {
                    "phase": "screening",
                    "message": f"{date} 截面完成，入选 {candidate_count} 只",
                    "current": i,
                    "total": len(dates),
                    "percent": round(i * 100 / max(len(dates), 1), 1),
                    "current_date": date,
                    "candidate_count": candidate_count,
                }
            )

    print(f"\n完成: {len(dates)} 个截面筛选结果已保存到 {screen_dir}")
    return dates


# ==================== Step 2: backtest-agent ====================

@dataclass
class AgentProgress:
    """Agent 批量分析进度追踪"""
    total: int = 0
    completed: int = 0
    failed: int = 0
    failed_list: List[Dict[str, str]] = field(default_factory=list)
    start_time: float = 0.0

    def tick_ok(self, ts_code: str, score, rec, elapsed):
        self.completed += 1
        pct = (self.completed + self.failed) / self.total * 100
        eta = self._eta()
        print(f"  ✓ [{self.completed + self.failed}/{self.total} {pct:.0f}%] "
              f"{ts_code} | {score}分 | {rec} | {elapsed:.0f}s | ETA {eta}")

    def tick_fail(self, ts_code: str, cutoff_date: str, error: str):
        self.failed += 1
        self.failed_list.append({'ts_code': ts_code, 'cutoff_date': cutoff_date, 'error': error})
        pct = (self.completed + self.failed) / self.total * 100
        print(f"  ✗ [{self.completed + self.failed}/{self.total} {pct:.0f}%] "
              f"{ts_code} | 失败: {error[:80]}")

    def _eta(self) -> str:
        elapsed = time.time() - self.start_time
        done = self.completed + self.failed
        if done == 0:
            return "?"
        remaining = (elapsed / done) * (self.total - done)
        if remaining > 3600:
            return f"{remaining/3600:.1f}h"
        return f"{remaining/60:.0f}min"


def step_agent(config: "StrategyConfig", max_retry: int = 1, dry_run: bool = False) -> AgentProgress:
    """
    读取筛选 CSV → 并发 Agent 分析 → 保存报告

    自动增量：跳过已有报告的股票。
    失败汇总：打印未跑通的列表，再次运行自动重试。

    Args:
        config: 策略配置
        max_retry: 失败后最大重试轮数
        dry_run: 仅统计任务量，不实际运行
    """
    screen_dir, reports_dir, _ = _bt_dirs(config)
    dates = generate_crosssection_dates(
        config.get_backtest_start(),
        config.get_backtest_end(),
        config.get_cross_section_interval(),
    )
    concurrency = config.get_agent_concurrency()
    avg_minutes_per_stock = 5  # 经验值，用于估算耗时

    # 收集所有待分析任务
    tasks = []  # [(ts_code, cutoff_date)]
    per_date_stats = []  # [(date, total, existing, pending)]
    for date in dates:
        df = load_screen_csv(date, screen_dir)
        if df is None:
            print(f"警告: {date} 无筛选结果，请先运行 backtest-screen")
            continue

        batch_n = config.get_agent_batch_size(len(df))
        codes = df['ts_code'].head(batch_n).tolist()

        existing = load_agent_reports(reports_dir, date)
        new_codes = [c for c in codes if c not in existing]
        per_date_stats.append((date, batch_n, len(existing), len(new_codes)))
        for c in new_codes:
            tasks.append((c, date))

    # 打印任务概览
    print(f"Agent 批量分析{'（模拟）' if dry_run else ''}")
    print(f"  截面: {len(dates)} 个")
    print(f"  并发数: {concurrency}")
    print()
    print(f"  {'截面':<12} {'选中':>4} {'已有':>4} {'待跑':>4}")
    print(f"  {'-'*12} {'-'*4} {'-'*4} {'-'*4}")
    for date, total, done, pending in per_date_stats:
        print(f"  {date:<12} {total:>4} {done:>4} {pending:>4}")

    total_pending = len(tasks)
    total_selected = sum(t for _, t, _, _ in per_date_stats)
    total_done = sum(d for _, _, d, _ in per_date_stats)
    print(f"  {'-'*12} {'-'*4} {'-'*4} {'-'*4}")
    print(f"  {'合计':<12} {total_selected:>4} {total_done:>4} {total_pending:>4}")

    if total_pending == 0:
        print("\n所有截面的 Agent 分析均已完成，无需重新运行。")
        return AgentProgress()

    # 估算耗时和成本
    est_minutes = total_pending * avg_minutes_per_stock / concurrency
    est_cost = total_pending * 0.4  # 经验值 0.4元/只
    print(f"\n  预估耗时: {est_minutes:.0f} 分钟 ({est_minutes/60:.1f} 小时)")
    print(f"  预估成本: ¥{est_cost:.1f} ({total_pending} 只 × ¥0.4/只)")
    print(f"  报告目录: {reports_dir}")

    if dry_run:
        # 打印任务列表
        print("\n  待分析股票列表:")
        for date, _, _, _ in per_date_stats:
            codes_for_date = [c for c, d in tasks if d == date]
            if codes_for_date:
                print(f"    {date}: {', '.join(codes_for_date)}")
        return AgentProgress(total=total_pending)

    print()

    # 运行（含重试）
    progress = AgentProgress(total=len(tasks), start_time=time.time())

    for attempt in range(1 + max_retry):
        if attempt > 0:
            # 重试轮
            retry_tasks = [(f['ts_code'], f['cutoff_date']) for f in progress.failed_list]
            progress.failed = 0
            progress.failed_list = []
            tasks = retry_tasks
            print(f"\n--- 重试第 {attempt} 轮: {len(tasks)} 只 ---\n")

        _run_agent_concurrent(tasks, config, reports_dir, concurrency, progress)

        if not progress.failed_list:
            break

    # 结果汇总
    elapsed_total = time.time() - progress.start_time
    print(f"\n{'='*60}")
    print("Agent 分析完成")
    print(f"  成功: {progress.completed}/{progress.total}")
    print(f"  失败: {progress.failed}")
    print(f"  总耗时: {elapsed_total/60:.1f} 分钟")

    if progress.failed_list:
        print("\n未完成列表 (再次运行 backtest-agent 自动增量重试):")
        for f in progress.failed_list:
            print(f"  {f['ts_code']} @ {f['cutoff_date']}: {f['error'][:80]}")

    print(f"{'='*60}")
    return progress


def _run_agent_concurrent(
    tasks: List[tuple],
    config: "StrategyConfig",
    reports_dir: Path,
    concurrency: int,
    progress: AgentProgress,
):
    """并发执行 Agent 分析任务"""
    from src.agent.runtime import run_blind_analysis

    async def _run_all():
        semaphore = asyncio.Semaphore(concurrency)

        async def _analyze_one(ts_code: str, cutoff_date: str):
            async with semaphore:
                try:
                    r = await run_blind_analysis(
                        ts_code, cutoff_date, config, True, reports_dir,
                    )
                    syn = r.get('synthesis', {})
                    score = syn.get('综合评分', '?')
                    rec = syn.get('最终建议', '?')
                    elapsed = r.get('metadata', {}).get('elapsed_seconds', 0)
                    progress.tick_ok(ts_code, score, rec, elapsed)
                except Exception as e:
                    progress.tick_fail(ts_code, cutoff_date, str(e))

        coros = [_analyze_one(code, date) for code, date in tasks]
        await asyncio.gather(*coros)

    asyncio.run(_run_all())


# ==================== Outcome 缓存序列化 ====================

OUTCOME_CACHE_SCHEMA_VERSION = 3

def _outcome_to_dict(outcome) -> dict:
    """ForwardOutcome → 可 JSON 序列化的 dict"""
    return {
        '_schema_version': OUTCOME_CACHE_SCHEMA_VERSION,
        'cutoff_price': outcome.cutoff_price,
        'return_1m': outcome.return_1m,
        'return_3m': outcome.return_3m,
        'return_6m': outcome.return_6m,
        'return_12m': outcome.return_12m,
        'max_drawdown_6m': outcome.max_drawdown_6m,
        'max_gain_6m': outcome.max_gain_6m,
        'volatility_6m': outcome.volatility_6m,
        'actual_dividends': outcome.actual_dividends,
        'data_available_months': outcome.data_available_months,
        'collection_date': outcome.collection_date,
    }


def _dict_to_outcome(ts_code: str, cutoff_date: str, d: dict):
    """dict → ForwardOutcome"""
    from src.backtest.outcome_collector import ForwardOutcome
    o = ForwardOutcome(ts_code=ts_code, cutoff_date=cutoff_date)
    for k, v in d.items():
        if hasattr(o, k):
            setattr(o, k, v)
    return o


def _outcome_cache_is_current(
    cutoff_date: str,
    payload: dict,
    *,
    as_of_date: Optional[str] = None,
) -> bool:
    """旧语义缓存立即失效；跨过新期限后自动重新采集。"""
    from src.backtest.outcome_collector import _add_months

    if payload.get('_schema_version') != OUTCOME_CACHE_SCHEMA_VERSION:
        return False

    collected_at = str(payload.get('collection_date') or '')
    observed_at = as_of_date or datetime.now().strftime('%Y-%m-%d')
    try:
        collected_dt = datetime.strptime(collected_at, '%Y-%m-%d')
        observed_dt = datetime.strptime(observed_at, '%Y-%m-%d')
    except ValueError:
        return False

    for months in (1, 3, 6, 12):
        target_dt = datetime.strptime(_add_months(cutoff_date, months), '%Y-%m-%d')
        if collected_dt < target_dt <= observed_dt:
            return False
    return True


# ==================== Step 3: backtest-eval ====================

@dataclass
class EvalSlice:
    """评估用的单截面数据"""
    cutoff_date: str
    candidates: pd.DataFrame = field(default_factory=pd.DataFrame)
    agent_reports: Dict[str, dict] = field(default_factory=dict)
    outcomes: Dict[str, object] = field(default_factory=dict)


def step_eval(
    config: "StrategyConfig",
    numeric_only: bool = False,
    progress: Optional[Callable[[Dict[str, object]], None]] = None,
) -> Path:
    """
    读取筛选 CSV + Agent 报告 → 采集前向收益 → 多基准绩效评估 → 保存报告

    Returns:
        报告文件路径
    """
    from src.backtest.outcome_cache import load_cutoff, save_cutoff
    from src.backtest.outcome_collector import collect_forward_outcomes_by_cutoff
    from src.data.config import get_active_provider_name

    screen_dir, reports_dir, bt_dir = _bt_dirs(config)
    dates = generate_crosssection_dates(
        config.get_backtest_start(),
        config.get_backtest_end(),
        config.get_cross_section_interval(),
    )
    print(f"回测评估: {config.name} v{config.version}")
    print(f"  截面: {len(dates)} 个")
    print()
    if progress:
        progress(
            {
                "phase": "loading",
                "message": "正在载入历史筛选结果",
                "current": 0,
                "total": len(dates),
                "percent": 0,
            }
        )

    # 1. 加载数据
    slices = []
    for index, date in enumerate(dates, 1):
        df = load_screen_csv(date, screen_dir)
        if df is None:
            print(f"  {date}: 无筛选结果，跳过")
            if progress:
                progress(
                    {
                        "phase": "loading",
                        "message": f"{date} 没有可用筛选结果，已跳过",
                        "current": index,
                        "total": len(dates),
                        "percent": round(index * 5 / max(len(dates), 1), 1),
                        "current_date": date,
                        "candidate_count": 0,
                    }
                )
            continue
        reports = {} if numeric_only else load_agent_reports(reports_dir, date)
        slices.append(EvalSlice(
            cutoff_date=date,
            candidates=df,
            agent_reports=reports,
        ))
        if numeric_only:
            print(f"  {date}: {len(df)} 候选")
        else:
            print(f"  {date}: {len(df)} 候选, {len(reports)} 份 Agent 报告")
        if progress:
            progress(
                {
                    "phase": "loading",
                    "message": f"正在载入 {date} 筛选结果",
                    "current": index,
                    "total": len(dates),
                    "percent": round(index * 5 / max(len(dates), 1), 1),
                    "current_date": date,
                    "candidate_count": len(df),
                }
            )

    if not slices:
        print("无数据可评估，请先运行 backtest-screen")
        return bt_dir

    # 2. 采集前向收益（带缓存 + 进度）
    outcomes_dir = bt_dir / "outcomes_cache"
    outcomes_dir.mkdir(parents=True, exist_ok=True)
    total_stocks = sum(len(sl.candidates) for sl in slices)
    done = 0
    cached = 0
    t0 = time.time()
    provider = get_active_provider_name()

    print(f"\n采集后复权前向收益 ({total_stocks} 只)...")
    if progress:
        progress(
            {
                "phase": "outcomes",
                "message": f"准备采集 {total_stocks} 个候选样本的后复权前向收益",
                "current": 0,
                "total": total_stocks,
                "percent": 5,
                "cached": 0,
            }
        )
    cache_states = {}
    missing_requests = {}
    reusable_count = 0
    for sl in slices:
        codes = sl.candidates['ts_code'].tolist()
        cache_path = outcomes_dir / f"outcomes_{sl.cutoff_date}.json"
        local_cache = {}
        if cache_path.exists():
            try:
                local_cache = json.loads(cache_path.read_text(encoding='utf-8'))
            except Exception:
                pass
        if not isinstance(local_cache, dict):
            local_cache = {}
        shared_cache = load_cutoff(provider, sl.cutoff_date)
        cache_data = {**shared_cache, **local_cache}
        current_cache = {
            code: payload
            for code, payload in cache_data.items()
            if isinstance(payload, dict)
            and _outcome_cache_is_current(sl.cutoff_date, payload)
        }
        missing_codes = list(dict.fromkeys(code for code in codes if code not in current_cache))
        cache_states[sl.cutoff_date] = {
            "path": cache_path,
            "data": cache_data,
            "current": current_cache,
        }
        if missing_codes:
            missing_requests[sl.cutoff_date] = missing_codes
        reusable_count += len(codes) - len(missing_codes)

    missing_total = sum(len(codes) for codes in missing_requests.values())
    if missing_total:
        unique_missing = len({
            code
            for codes in missing_requests.values()
            for code in codes
        })
        print(
            f"  合并读取 {len(missing_requests)} 个截面、{unique_missing} 只股票的行情窗口 "
            f"({missing_total} 个待计算样本)..."
        )
        if progress:
            progress(
                {
                    "phase": "outcomes",
                    "message": (
                        f"正在合并读取 {len(missing_requests)} 个截面的后复权行情，"
                        f"避免重复扫描磁盘"
                    ),
                    "current": reusable_count,
                    "total": total_stocks,
                    "percent": round(
                        5 + reusable_count * 85 / max(total_stocks, 1),
                        1,
                    ),
                    "cached": reusable_count,
                    "unique_stocks": unique_missing,
                }
            )
        fresh_by_cutoff = collect_forward_outcomes_by_cutoff(missing_requests)
        print(f"  行情批量读取与计算完成，耗时 {time.time() - t0:.0f}s")
    else:
        fresh_by_cutoff = {}
        print(f"  共享缓存命中全部 {total_stocks} 个样本，无需读取行情库")

    for sl in slices:
        codes = sl.candidates['ts_code'].tolist()
        state = cache_states[sl.cutoff_date]
        cache_path = state["path"]
        cache_data = state["data"]
        current_cache = state["current"]
        fresh_outcomes = fresh_by_cutoff.get(sl.cutoff_date, {})
        reusable_payloads = {}

        for ts_code in codes:
            done += 1
            # 命中缓存
            if ts_code in current_cache:
                outcome = _dict_to_outcome(ts_code, sl.cutoff_date, current_cache[ts_code])
                sl.outcomes[ts_code] = outcome
                cached += 1
                reusable_payloads[ts_code] = current_cache[ts_code]
            else:
                outcome = fresh_outcomes.get(ts_code)
                if outcome is not None:
                    sl.outcomes[ts_code] = outcome
                    payload = _outcome_to_dict(outcome)
                    cache_data[ts_code] = payload
                    reusable_payloads[ts_code] = payload
            # 进度
            if done % 20 == 0 or done == total_stocks:
                elapsed = time.time() - t0
                speed = done / elapsed if elapsed > 0 else 0
                print(f"  [{done}/{total_stocks}] {sl.cutoff_date} "
                      f"| {elapsed:.0f}s | {speed:.1f}只/s | 批量行情已就绪")
                if progress:
                    progress(
                        {
                            "phase": "outcomes",
                            "message": f"正在采集 {sl.cutoff_date} 后复权前向收益",
                            "current": done,
                            "total": total_stocks,
                            "percent": round(
                                5 + done * 85 / max(total_stocks, 1),
                                1,
                            ),
                            "current_date": sl.cutoff_date,
                            "cached": cached,
                            "speed": round(speed, 2),
                            "eta_seconds": 0,
                        }
                    )

        # 每次运行保留独立快照，同时写入按数据源复用的共享缓存。
        temporary_cache_path = cache_path.with_suffix(".json.tmp")
        temporary_cache_path.write_text(
            json.dumps(cache_data, ensure_ascii=False, default=str),
            encoding='utf-8',
        )
        temporary_cache_path.replace(cache_path)
        save_cutoff(provider, sl.cutoff_date, reusable_payloads)

    print(f"  完成: {done} 只, 缓存命中 {cached}, 新采集 {done - cached}, 耗时 {time.time()-t0:.0f}s")

    # 3. 多基准评估
    print("\n计算绩效...")
    if progress:
        progress(
            {
                "phase": "summarizing",
                "message": "正在计算组合收益与沪深300基准",
                "current": total_stocks,
                "total": total_stocks,
                "percent": 92,
                "cached": cached,
            }
        )
    performance = _evaluate_multi_baseline(slices, config, numeric_only=numeric_only)

    # 4. 生成报告
    report_text = _format_eval_report(slices, performance, config, numeric_only=numeric_only)
    ts = datetime.now().strftime('%Y%m%d_%H%M')
    report_path = bt_dir / f"backtest_report_{ts}.md"
    report_path.write_text(report_text, encoding='utf-8')

    summary_path = bt_dir / f"backtest_summary_{ts}.json"
    _save_eval_json(slices, performance, config, summary_path, numeric_only=numeric_only)
    if progress:
        progress(
            {
                "phase": "reporting",
                "message": "正在生成历史验证报告与图表",
                "current": total_stocks,
                "total": total_stocks,
                "percent": 97,
                "cached": cached,
            }
        )

    # 5. 打印摘要
    print(f"\n{'='*60}")
    print("绩效摘要 (6个月前向)")
    print(f"{'='*60}")
    baseline_keys = ['market', 'screen_all', 'screen_top']
    if not numeric_only:
        baseline_keys.extend(['agent_buy', 'agent_top'])
    for key in baseline_keys:
        bl = performance.get(key, {})
        stats = bl.get('stats', {}).get('6个月', {})
        label = bl.get('label', key)
        if stats.get('count', 0) > 0:
            print(f"  {label}: "
                  f"均收益={stats['mean']*100:+.1f}% "
                  f"胜率={stats['win_rate']*100:.0f}% "
                  f"样本={stats['count']}")
        else:
            print(f"  {label}: 无数据")

    # Alpha
    s_mkt = performance.get('market', {}).get('stats', {}).get('6个月', {})
    s_all = performance.get('screen_all', {}).get('stats', {}).get('6个月', {})
    mkt_mean = s_mkt.get('mean')
    all_mean = s_all.get('mean')
    if all_mean is not None and mkt_mean is not None:
        print(f"\n  Alpha (6m): 筛选池 vs 沪深300 = {(all_mean-mkt_mean)*100:+.1f}pp")
    if not numeric_only:
        s_buy = performance.get('agent_buy', {}).get('stats', {}).get('6个月', {})
        buy_mean = s_buy.get('mean')
        if buy_mean is not None and mkt_mean is not None:
            print(f"  Alpha (6m): Agent买入 vs 沪深300 = {(buy_mean-mkt_mean)*100:+.1f}pp")

    # 6. 生成收益曲线图
    chart_path = _generate_return_chart(slices, performance, config, bt_dir, ts)
    if chart_path:
        print(f"曲线图: {chart_path}")

    print(f"\n报告: {report_path}")
    print(f"数据: {summary_path}")
    if progress:
        progress(
            {
                "phase": "completed",
                "message": "历史验证结果已生成",
                "current": total_stocks,
                "total": total_stocks,
                "percent": 100,
                "cached": cached,
            }
        )
    return report_path


def _collect_index_returns(
    dates: List[str],
    forward_periods: List[dict],
    index_code: str = '000300.SH',
) -> dict:
    """采集指数在各截面的前向收益，返回 {label: {count, mean, median, ...}}"""
    slices = _collect_index_return_slices(dates, forward_periods, index_code)
    return _aggregate_returns(slices, forward_periods)


def _collect_index_return_slices(
    dates: List[str],
    forward_periods: List[dict],
    index_code: str = '000300.SH',
    *,
    as_of_date: Optional[str] = None,
) -> List[dict]:
    """Collect one index return observation per date and forward horizon."""
    from src.data import api
    from src.backtest.outcome_collector import (
        _add_months,
        _find_nearest_trade_date,
        _has_forward_horizon_elapsed,
    )

    if not dates:
        return []

    slices = [
        {
            'cutoff_date': date,
            'count': 1,
            **{f"returns_{fp['months']}m": [] for fp in forward_periods},
        }
        for date in dates
    ]

    # 一次性拉取指数全部数据
    start = (datetime.strptime(min(dates), '%Y-%m-%d') - relativedelta(days=15)).strftime('%Y-%m-%d')
    end = _add_months(max(dates), 13)
    try:
        idx_df = api.get_index_daily(index_code, start, end)
    except Exception as e:
        print(f"  警告: 无法获取指数 {index_code} 数据: {e}")
        return slices

    if idx_df.empty:
        return slices

    observed_at = as_of_date or datetime.now().strftime('%Y-%m-%d')
    idx_df = idx_df.copy()
    idx_df['trade_date'] = pd.to_datetime(idx_df['trade_date'], errors='coerce')
    idx_df['close'] = pd.to_numeric(idx_df['close'], errors='coerce')
    idx_df = idx_df.dropna(subset=['trade_date', 'close']).sort_values('trade_date')
    idx_df['trade_date'] = idx_df['trade_date'].dt.strftime('%Y-%m-%d')
    idx_df = idx_df[idx_df['trade_date'] <= observed_at]
    if idx_df.empty:
        return slices
    idx_prices = idx_df.set_index('trade_date')['close']

    for item in slices:
        date = item['cutoff_date']
        cutoff_trade = _find_nearest_trade_date(idx_df, date, direction='backward')
        if cutoff_trade is None:
            continue
        p0 = idx_prices.loc[cutoff_trade]
        for fp in forward_periods:
            months = fp['months']
            # 找 N 个月后最近交易日
            target = _add_months(date, months)
            if not _has_forward_horizon_elapsed(target, as_of_date=observed_at):
                continue
            terminal_trade = _find_nearest_trade_date(
                idx_df,
                target,
                direction='backward',
            )
            if terminal_trade is None or terminal_trade <= cutoff_trade:
                continue
            p1 = idx_prices.loc[terminal_trade]
            item[f'returns_{months}m'] = [(p1 - p0) / p0]

    return slices


def _evaluate_multi_baseline(
    slices: List[EvalSlice],
    config: "StrategyConfig",
    numeric_only: bool = False,
) -> Dict[str, dict]:
    """五基准绩效评估"""
    forward_periods = config.get_forward_periods()
    tiers = config.get_tiers()
    top_tier = tiers[0]['name'] if tiers else None
    buy_threshold = config.get_decision_thresholds().get('buy', 70)

    # 全市场基准: 沪深300 指数
    print("  采集沪深300指数基准...")
    dates = [sl.cutoff_date for sl in slices]
    market_slices = _collect_index_return_slices(
        dates, forward_periods, '000300.SH'
    )
    market_stats = _aggregate_returns(market_slices, forward_periods)

    baselines = {
        'market': {'label': '沪深300', 'desc': '沪深300指数收益 (全市场基准)',
                   'slices': market_slices, 'stats': market_stats},
        'screen_all': {'label': '筛选池等权', 'desc': '所有通过量化筛选的候选'},
        'screen_top': {'label': f'筛选池 Top ({top_tier or "前10名"})', 'desc': '量化排名最高的候选'},
    }
    if not numeric_only:
        baselines.update({
            'agent_buy': {'label': 'Agent 买入', 'desc': f'Agent 建议"买入" (≥{buy_threshold}分)'},
            'agent_top': {'label': 'Agent Top5', 'desc': 'Agent 评分最高的5只'},
        })
    for key in baselines:
        baselines[key].setdefault('slices', [])

    for sl in slices:
        all_codes = sl.candidates['ts_code'].tolist()

        # screen_all
        baselines['screen_all']['slices'].append(
            _extract_returns(all_codes, sl, forward_periods)
        )

        # screen_top
        if top_tier and 'tier_rating' in sl.candidates.columns:
            top_codes = sl.candidates[sl.candidates['tier_rating'] == top_tier]['ts_code'].tolist()
        else:
            top_codes = all_codes[:10]
        baselines['screen_top']['slices'].append(
            _extract_returns(top_codes, sl, forward_periods)
        )

        if not numeric_only:
            buy_codes = []
            for code, report in sl.agent_reports.items():
                syn = report.get('synthesis', {})
                score = syn.get('综合评分')
                if syn.get('最终建议') == '买入' or (isinstance(score, (int, float)) and score >= buy_threshold):
                    buy_codes.append(code)
            baselines['agent_buy']['slices'].append(
                _extract_returns(buy_codes, sl, forward_periods)
            )

            scored = []
            for code, report in sl.agent_reports.items():
                syn = report.get('synthesis', {})
                score = syn.get('综合评分')
                if isinstance(score, (int, float)):
                    scored.append((code, score))
            scored.sort(key=lambda x: -x[1])
            baselines['agent_top']['slices'].append(
                _extract_returns([c for c, _ in scored[:5]], sl, forward_periods)
            )

    # 汇总统计 (market 已有 stats，跳过)
    for key, bl in baselines.items():
        if key != 'market':
            bl['stats'] = _aggregate_returns(bl['slices'], forward_periods)

    return baselines


def _extract_returns(codes: List[str], sl: EvalSlice, forward_periods: List[dict]) -> dict:
    """提取一组股票在某截面的前向收益"""
    data = {'cutoff_date': sl.cutoff_date, 'count': len(codes), 'codes': codes}
    for fp in forward_periods:
        months = fp['months']
        rets = []
        for code in codes:
            outcome = sl.outcomes.get(code)
            if outcome:
                ret = getattr(outcome, f'return_{months}m', None)
                if ret is not None:
                    rets.append(ret)
        data[f'returns_{months}m'] = rets
    return data


def _aggregate_returns(slices: List[dict], forward_periods: List[dict]) -> dict:
    """汇总多截面收益统计"""
    stats = {}
    for fp in forward_periods:
        months = fp['months']
        label = fp['label']
        all_rets = []
        for s in slices:
            all_rets.extend(s.get(f'returns_{months}m', []))
        if all_rets:
            sorted_r = sorted(all_rets)
            stats[label] = {
                'count': len(all_rets),
                'mean': sum(all_rets) / len(all_rets),
                'median': sorted_r[len(sorted_r) // 2],
                'win_rate': sum(1 for r in all_rets if r > 0) / len(all_rets),
                'best': max(all_rets),
                'worst': min(all_rets),
            }
        else:
            stats[label] = {'count': 0}
    stats['total_stocks'] = sum(s['count'] for s in slices)
    stats['total_slices'] = len(slices)
    return stats


# ==================== 报告格式化 ====================

def _format_eval_report(
    slices: List[EvalSlice],
    performance: Dict[str, dict],
    config: "StrategyConfig",
    numeric_only: bool = False,
) -> str:
    """生成 Markdown 绩效报告"""
    forward_periods = config.get_forward_periods()
    dates = [sl.cutoff_date for sl in slices]

    lines = [
        f"# 回测绩效报告: {config.name}",
        "",
        f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**截面**: {len(dates)} 个 ({dates[0]} ~ {dates[-1]})",
        f"**间隔**: {config.get_cross_section_interval()}",
        "**个股收益口径**: 后复权价格序列（不另行拼接现金分红）",
        "",
        "## 各截面概览",
        "",
    ]
    if numeric_only:
        lines.extend(["| 截面 | 筛选候选 |", "|------|---------|"])
        for sl in slices:
            lines.append(f"| {sl.cutoff_date} | {len(sl.candidates)} |")
    else:
        lines.extend([
            "| 截面 | 筛选候选 | Agent报告 | Agent买入 |",
            "|------|---------|----------|----------|",
        ])
        for sl in slices:
            n_buy = sum(
                1 for r in sl.agent_reports.values()
                if r.get('synthesis', {}).get('最终建议') == '买入'
            )
            lines.append(
                f"| {sl.cutoff_date} | {len(sl.candidates)} "
                f"| {len(sl.agent_reports)} | {n_buy} |"
            )

    # 多基准对比
    lines.extend(["", "## 多基准绩效对比", ""])
    for fp in forward_periods:
        label = fp['label']
        lines.extend([f"### {label}前向收益", ""])
        lines.append("| 基准 | 样本数 | 平均收益 | 中位数 | 胜率 | 最好 | 最差 |")
        lines.append("|------|--------|---------|--------|------|------|------|")
        baseline_keys = ['market', 'screen_all', 'screen_top']
        if not numeric_only:
            baseline_keys.extend(['agent_buy', 'agent_top'])
        for key in baseline_keys:
            bl = performance.get(key, {})
            stats = bl.get('stats', {}).get(label, {})
            bl_label = bl.get('label', key)
            count = stats.get('count', 0)
            if count > 0:
                lines.append(
                    f"| {bl_label} | {count} "
                    f"| {stats['mean']*100:+.1f}% "
                    f"| {stats['median']*100:+.1f}% "
                    f"| {stats['win_rate']*100:.0f}% "
                    f"| {stats['best']*100:+.1f}% "
                    f"| {stats['worst']*100:+.1f}% |"
                )
            else:
                lines.append(f"| {bl_label} | 0 | N/A | N/A | N/A | N/A | N/A |")
        lines.append("")

    if not numeric_only:
        lines.extend(["## Agent 分析结果汇总", ""])
        lines.append("| 截面 | 股票 | 评分 | 建议 | 流派 | 6m实际 |")
        lines.append("|------|------|------|------|------|--------|")
        for sl in slices:
            for code, report in sorted(sl.agent_reports.items()):
                syn = report.get('synthesis', {})
                outcome = sl.outcomes.get(code)
                ret_6m = f"{outcome.return_6m*100:+.1f}%" if outcome and outcome.return_6m is not None else "N/A"
                lines.append(
                    f"| {sl.cutoff_date} | {code} "
                    f"| {syn.get('综合评分', '')} | {syn.get('最终建议', '')} "
                    f"| {syn.get('流派判定', '')} | {ret_6m} |"
                )

    # Alpha
    lines.extend(["", "## Alpha 分析", ""])
    for fp in forward_periods:
        label = fp['label']
        s_mkt = performance.get('market', {}).get('stats', {}).get(label, {})
        s_all = performance.get('screen_all', {}).get('stats', {}).get(label, {})
        mkt_mean = s_mkt.get('mean')
        all_mean = s_all.get('mean')

        parts = []
        if all_mean is not None and mkt_mean is not None:
            parts.append(f"筛选池 vs 沪深300 = {(all_mean-mkt_mean)*100:+.1f}pp")
        if not numeric_only:
            s_buy = performance.get('agent_buy', {}).get('stats', {}).get(label, {})
            buy_mean = s_buy.get('mean')
            if buy_mean is not None and all_mean is not None:
                parts.append(f"Agent买入 vs 筛选池 = {(buy_mean-all_mean)*100:+.1f}pp")
            if buy_mean is not None and mkt_mean is not None:
                parts.append(f"Agent买入 vs 沪深300 = {(buy_mean-mkt_mean)*100:+.1f}pp")

        if parts:
            lines.append(f"- **{label}**: {' | '.join(parts)}")
        else:
            lines.append(f"- **{label}**: 数据不足")

    return '\n'.join(lines)


def _generate_return_chart(
    slices: List[EvalSlice],
    performance: Dict[str, dict],
    config: "StrategyConfig",
    bt_dir: Path,
    timestamp: str,
) -> Optional[Path]:
    """生成各基准 6 个月前向收益的逐截面对比曲线图"""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
    except ImportError:
        print("  警告: matplotlib 不可用，跳过曲线图生成")
        return None

    # 检测中文字体可用性
    from matplotlib.font_manager import fontManager
    _CN_FONT = False
    available_fonts = {f.name for f in fontManager.ttflist}
    for font_name in ['SimHei', 'WenQuanYi Micro Hei', 'Noto Sans CJK SC']:
        if font_name in available_fonts:
            plt.rcParams['font.sans-serif'] = [font_name, 'DejaVu Sans']
            _CN_FONT = True
            break
    plt.rcParams['axes.unicode_minus'] = False

    dates = [sl.cutoff_date for sl in slices]
    x_dates = [datetime.strptime(d, '%Y-%m-%d') for d in dates]

    baselines_to_plot = [
        ('market', 'CSI300' if not _CN_FONT else '沪深300', '#888888', '--'),
        ('screen_all', 'Screen All' if not _CN_FONT else '筛选池等权', '#2196F3', '-'),
        ('screen_top', 'Screen Top' if not _CN_FONT else '筛选池 Top', '#4CAF50', '-'),
        ('agent_buy', 'Agent Buy' if not _CN_FONT else 'Agent 买入', '#FF5722', '-'),
        ('agent_top', 'Agent Top5', '#FF9800', '-'),
    ]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), gridspec_kw={'height_ratios': [3, 1]})

    # === 上图: 累计收益曲线 ===
    for key, label, color, style in baselines_to_plot:
        bl = performance.get(key, {})
        bl_slices = bl.get('slices', [])

        # 从 slices 数据取每截面均收益
        per_date_returns = {}
        for s in bl_slices:
            rets = s.get('returns_6m', [])
            if rets:
                per_date_returns[s['cutoff_date']] = sum(rets) / len(rets)

        # 构建累计收益序列
        cum = 1.0
        cum_values = []
        for d in dates:
            r = per_date_returns.get(d)
            if r is not None:
                cum *= (1 + r)
            cum_values.append(cum)

        if any(v != 1.0 for v in cum_values):
            ax1.plot(x_dates, cum_values, label=label, color=color, linestyle=style,
                     linewidth=2.5 if key == 'agent_buy' else 1.5,
                     marker='o' if key == 'agent_buy' else None,
                     markersize=4)

    ax1.axhline(y=1.0, color='gray', linewidth=0.5, linestyle=':')
    title1 = 'Cumulative Return (6M Forward, Per-Slice Compounding)' if not _CN_FONT else '累计收益曲线 (6个月前向, 逐截面复利)'
    ax1.set_title(title1, fontsize=14, fontweight='bold')
    ylabel1 = 'Cumulative Return (1.0 = Principal)' if not _CN_FONT else '累计收益 (1.0 = 本金)'
    ax1.set_ylabel(ylabel1)
    ax1.legend(loc='upper left', fontsize=10)
    ax1.grid(True, alpha=0.3)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax1.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
    fig.autofmt_xdate(rotation=45)

    # === 下图: 逐截面 Agent 买入 vs 筛选池的超额收益柱状图 ===
    agent_slices = performance.get('agent_buy', {}).get('slices', [])
    screen_slices = performance.get('screen_all', {}).get('slices', [])

    alphas = []
    for d in dates:
        agent_r = None
        screen_r = None
        for s in agent_slices:
            if s['cutoff_date'] == d:
                rets = s.get('returns_6m', [])
                if rets:
                    agent_r = sum(rets) / len(rets)
        for s in screen_slices:
            if s['cutoff_date'] == d:
                rets = s.get('returns_6m', [])
                if rets:
                    screen_r = sum(rets) / len(rets)
        if agent_r is not None and screen_r is not None:
            alphas.append((agent_r - screen_r) * 100)
        else:
            alphas.append(0)

    colors = ['#4CAF50' if a >= 0 else '#F44336' for a in alphas]
    ax2.bar(x_dates, alphas, width=40, color=colors, alpha=0.8)
    ax2.axhline(y=0, color='gray', linewidth=0.5)
    title2 = 'Agent Buy vs Screen Pool: Per-Slice Alpha (pp)' if not _CN_FONT else 'Agent 买入 vs 筛选池 逐截面超额收益 (pp)'
    ax2.set_title(title2, fontsize=12)
    ax2.set_ylabel('Alpha (pp)')
    ax2.grid(True, alpha=0.3)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))

    plt.tight_layout()
    chart_path = bt_dir / f"backtest_chart_{timestamp}.png"
    fig.savefig(chart_path, dpi=150, bbox_inches='tight')
    plt.close(fig)

    print(f"  收益曲线已生成: {chart_path.name}")
    return chart_path


def _get_market_per_date_returns(
    dates: List[str],
    config: "StrategyConfig",
    *,
    as_of_date: Optional[str] = None,
) -> dict:
    """获取沪深300在各截面的 6m 收益。"""
    slices = _collect_index_return_slices(
        dates,
        [{'months': 6, 'label': '6个月'}],
        '000300.SH',
        as_of_date=as_of_date,
    )
    return {
        item['cutoff_date']: item['returns_6m'][0]
        for item in slices
        if item.get('returns_6m')
    }


def _save_eval_json(
    slices: List[EvalSlice],
    performance: Dict[str, dict],
    config: "StrategyConfig",
    path: Path,
    numeric_only: bool = False,
):
    """保存结构化回测结果"""
    from src.data.config import get_active_provider_name

    summary = {
        'outcome_schema_version': OUTCOME_CACHE_SCHEMA_VERSION,
        'evaluation_semantics': 'forward_return',
        'return_basis': 'hfq_adjusted_close',
        'provider': get_active_provider_name(),
        'strategy': config.name,
        'version': config.version,
        'dates': [sl.cutoff_date for sl in slices],
        'interval': config.get_cross_section_interval(),
        'generated_at': datetime.now().isoformat(),
        'slices': [],
        'performance': {},
    }
    for sl in slices:
        sd = {
            'cutoff_date': sl.cutoff_date,
            'screen_count': len(sl.candidates),
        }
        if not numeric_only:
            sd['agent_count'] = len(sl.agent_reports)
            sd['agent_scores'] = {}
            for code, report in sl.agent_reports.items():
                syn = report.get('synthesis', {})
                sd['agent_scores'][code] = {
                    'score': syn.get('综合评分'),
                    'recommendation': syn.get('最终建议'),
                    'stream': syn.get('流派判定'),
                }
        summary['slices'].append(sd)

    for key, bl in performance.items():
        summarized_slices = []
        for item in bl.get('slices', []):
            period_returns = {}
            for fp in config.get_forward_periods():
                values = item.get(f"returns_{fp['months']}m", [])
                period_returns[fp['label']] = (
                    sum(values) / len(values) if values else None
                )
            summarized_slices.append({
                'cutoff_date': item.get('cutoff_date'),
                'count': item.get('count', 0),
                'returns': period_returns,
            })
        summary['performance'][key] = {
            'label': bl.get('label', ''),
            'desc': bl.get('desc', ''),
            'stats': bl.get('stats', {}),
            'slices': summarized_slices,
        }

    path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding='utf-8',
    )
