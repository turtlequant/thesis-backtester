"""
策略启动器

统一入口，加载策略配置后 dispatch 到对应模块。

用法:
    # 策略命令 (需要 strategy.yaml)
    python -m src.engine.launcher strategies/v6_value/strategy.yaml screen 2024-06-30
    python -m src.engine.launcher strategies/v6_value/strategy.yaml analyze 601288.SH 2024-06-30
    python -m src.engine.launcher strategies/v6_value/strategy.yaml agent-analyze 601288.SH 2024-06-30

    # 数据命令 (不需要 strategy.yaml)
    python -m src.engine.launcher data update-daily
    python -m src.engine.launcher data update-indicator
    python -m src.engine.launcher data update-financials 601288.SH 000001.SZ
    python -m src.engine.launcher data update-factors
    python -m src.engine.launcher data daily-update
    python -m src.engine.launcher data status
"""
import sys
from pathlib import Path

from dotenv import load_dotenv

# 加载项目根目录 .env
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from .config import StrategyConfig

# 数据管理命令 (不需要策略配置)
_DATA_COMMANDS = {
    'update-daily', 'update-indicator', 'update-financials',
    'update-factors', 'update-disclosure', 'daily-update',
    'full-update', 'init-basic', 'init-market', 'status',
    'recalc-factors',
    'update-ts-factors', 'recalc-ts-factors',
}


def main():
    if len(sys.argv) < 3:
        _print_usage()
        sys.exit(1)

    # 判断是数据命令还是策略命令
    if sys.argv[1] == 'data':
        command = sys.argv[2]
        extra_args = sys.argv[3:]
        if command not in _DATA_COMMANDS:
            print(f"未知数据命令: {command}")
            _print_usage()
            sys.exit(1)
        _dispatch_data(command, extra_args)
    else:
        yaml_path = sys.argv[1]
        command = sys.argv[2]
        extra_args = sys.argv[3:]

        config = StrategyConfig.from_yaml(yaml_path)
        print(f"策略: {config.name} (v{config.version})")
        print()
        _dispatch_strategy(config, command, extra_args)


def _print_usage():
    S = "strategies/v6_value/strategy.yaml"
    print("用法:")
    print(f"  python -m src.engine.launcher <strategy.yaml> <command> [args...]")
    print(f"  python -m src.engine.launcher data <command> [args...]")
    print()
    print("═══ 分析命令 (需要 strategy.yaml) ═══")
    print()
    print("  单次分析:")
    print("    screen <date> [--top N]              量化筛选")
    print("    agent-analyze <code> <date>           单只 Agent 分析")
    print("    batch-analyze <date> [--top N]        筛选 + 批量 Agent 分析")
    print()
    print("  实时分析:")
    print("    live-analyze <code> [--no-blind]       单股实时分析 (免费数据, 无需 Tushare)")
    print()
    print("  回测 Pipeline (三步独立):")
    print("    backtest-screen                       ① 生成截面日期 + 逐截面筛选 + 保存 CSV")
    print("    backtest-agent [--retry N] [--dry-run] ② 并发 Agent 分析 (增量/重试/进度)")
    print("    backtest-eval                         ③ 采集前向收益 + 多基准绩效评估")
    print()
    print("═══ 数据命令 (不需要 strategy.yaml) ═══")
    print()
    print("  初始化:")
    print("    data init-basic                       股票列表 + 交易日历")
    print("    data init-market [start]              日线行情 + 指标 + 因子")
    print()
    print("  增量更新:")
    print("    data daily-update                     每日一键更新 (行情+指标+因子)")
    print("    data update-daily [start] [end]       日线行情")
    print("    data update-indicator [start] [end]   每日指标 (PE/PB/DV/市值)")
    print("    data update-financials [codes...]     财报 (无参数=全市场, 有参数=逐股全表)")
    print("    data update-disclosure                披露日期")
    print()
    print("  因子计算:")
    print("    data update-factors [start] [end]     增量截面因子")
    print("    data recalc-factors                   全量重算截面因子")
    print("    data update-ts-factors [codes...]     增量时序因子")
    print("    data recalc-ts-factors                全量重算时序因子")
    print()
    print("  综合:")
    print("    data full-update [start] [codes]      全量更新 (基础+行情+财报+因子)")
    print("    data status                           查看本地数据状态")
    print()
    print("═══ 示例 ═══")
    print()
    print(f"  python -m src.engine.launcher data daily-update")
    print(f"  python -m src.engine.launcher data update-financials 601288.SH 000001.SZ")
    print(f"  python -m src.engine.launcher {S} screen 2024-06-30")
    print(f"  python -m src.engine.launcher {S} agent-analyze 601288.SH 2024-06-30")
    print(f"  python -m src.engine.launcher {S} backtest-screen")
    print(f"  python -m src.engine.launcher {S} backtest-agent")
    print(f"  python -m src.engine.launcher {S} backtest-eval")
    print(f"  python -m src.engine.launcher {S} live-analyze 601288.SH")


def _dispatch_strategy(config: StrategyConfig, command: str, args: list):
    if command == "screen":
        _cmd_screen(config, args)
    elif command == "agent-analyze":
        _cmd_agent_analyze(config, args)
    elif command == "batch-analyze":
        _cmd_batch_analyze(config, args)
    elif command == "live-analyze":
        _cmd_live_analyze(config, args)
    elif command == "backtest-screen":
        _cmd_backtest_screen(config, args)
    elif command == "backtest-agent":
        _cmd_backtest_agent(config, args)
    elif command == "backtest-eval":
        _cmd_backtest_eval(config, args)
    else:
        print(f"未知策略命令: {command}")
        sys.exit(1)


def _dispatch_data(command: str, args: list):
    from src.data.updater import DataUpdater
    updater = DataUpdater()

    if command == 'update-daily':
        start = args[0] if len(args) > 0 else None
        end = args[1] if len(args) > 1 else None
        updater.update_daily(start, end)

    elif command == 'update-indicator':
        start = args[0] if len(args) > 0 else None
        end = args[1] if len(args) > 1 else None
        updater.update_daily_indicator(start, end)

    elif command == 'update-financials':
        if args:
            # 指定股票: 逐股获取全部表 (含分红/股东等补充表)
            updater.update_financials(args)
        else:
            # 全市场: 按报告期截面获取核心四表 (高效)
            updater.update_financials_by_period()

    elif command == 'update-factors':
        start = args[0] if len(args) > 0 else None
        end = args[1] if len(args) > 1 else None
        updater.update_factors(start, end)

    elif command == 'recalc-factors':
        from src.data.factor_store import recalc_all_factors
        recalc_all_factors()

    elif command == 'update-ts-factors':
        from src.data.factor_store import compute_and_store_ts_factors
        codes = args if args else None
        compute_and_store_ts_factors(ts_codes=codes)

    elif command == 'recalc-ts-factors':
        from src.data.factor_store import recalc_all_ts_factors
        recalc_all_ts_factors()

    elif command == 'update-disclosure':
        end_date = args[0] if args else None
        updater.update_disclosure_date(end_date)

    elif command == 'daily-update':
        updater.daily_update()

    elif command == 'init-basic':
        updater.init_basic()

    elif command == 'init-market':
        start = args[0] if args else '2020-01-01'
        updater.init_market_data(start)

    elif command == 'full-update':
        start = args[0] if len(args) > 0 else '2020-01-01'
        codes = args[1:] if len(args) > 1 else None
        updater.full_update(market_start=start, financial_codes=codes)

    elif command == 'status':
        _cmd_data_status()


def _cmd_data_status():
    """显示本地数据状态"""
    from src.data.api import get_data_status
    status = get_data_status()

    print("=" * 50)
    print("本地数据状态")
    print("=" * 50)

    print("\n日线数据:")
    for key in ['daily_raw', 'daily_indicator', 'daily_adj_factor', 'daily_factors']:
        info = status.get(key, {})
        label = key.replace('daily_', '  ')
        partitions = info.get('partitions', 0)
        latest = info.get('latest_date', '-')
        months = info.get('months', '-')
        print(f"  {label}: {partitions} 分区, 最新 {latest}, 范围 {months}")

    # 时序因子
    ts_info = status.get('ts_factors', {})
    print(f"\n时序因子: {ts_info.get('stocks', 0)} 只股票, {ts_info.get('factors', 0)} 个因子")

    _FINANCIAL_KEYS = [
        'balancesheet', 'income', 'cashflow', 'fina_indicator',
        'dividend', 'top10_holders', 'top10_floatholders',
        'pledge_stat', 'pledge_detail', 'fina_audit', 'fina_mainbz',
        'stk_holdernumber', 'stk_holdertrade', 'share_float', 'repurchase',
        'disclosure_date',
    ]
    print("\n财报数据:")
    for sub in _FINANCIAL_KEYS:
        info = status.get(f'financial_{sub}', {})
        count = info.get('count', 0)
        if count > 0:
            print(f"    {sub}: {count} 只/期")

    print(f"\n股票列表: {status.get('stock_list', {}).get('active_count', 0)} 只活跃")

    from src.data.settings import DATA_START_DATE
    print(f"数据起始日期: {DATA_START_DATE}")


def _cmd_screen(config: StrategyConfig, args: list):
    """量化筛选"""
    if not args:
        print("用法: screen <cutoff_date> [--top N]")
        sys.exit(1)

    from src.screener.quick_filter import screen_at_date, format_screen_result

    cutoff_date = args[0]
    top_n = 50
    if '--top' in args:
        idx = args.index('--top')
        if idx + 1 < len(args):
            top_n = int(args[idx + 1])

    print(f"量化筛选: {cutoff_date} (top {top_n})")
    result = screen_at_date(cutoff_date, top_n=top_n, config=config)
    print()
    print(format_screen_result(result))


def _cmd_live_analyze(config: StrategyConfig, args: list):
    """实时单股分析（免费数据，不需要 Tushare）"""
    if not args:
        print("用法: live-analyze <ts_code> [--no-blind]")
        sys.exit(1)

    import asyncio
    import json
    import logging
    from pathlib import Path
    from datetime import datetime
    from src.data.live_snapshot import create_live_snapshot
    from src.data.snapshot import snapshot_to_markdown
    from src.agent.runtime import run_blind_analysis

    ts_code = args[0]
    blind_mode = "--no-blind" not in args
    cutoff_date = datetime.now().strftime('%Y-%m-%d')

    # 输出目录: strategies/xxx/live/{ts_code}_{date}/
    live_dir = config.strategy_dir / "live" / f"{ts_code}_{cutoff_date}"
    live_dir.mkdir(parents=True, exist_ok=True)

    # 配置日志到文件
    log_path = live_dir / "run.log"
    file_handler = logging.FileHandler(log_path, encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('%(asctime)s %(name)s %(levelname)s %(message)s'))
    logging.getLogger().addHandler(file_handler)

    print(f"实时分析: {ts_code} @ {cutoff_date}")
    print(f"输出目录: {live_dir}")
    print()

    # 1. 获取实时数据
    print("[1/3] 获取实时数据...")
    snapshot = create_live_snapshot(ts_code)
    print(f"  数据源: {', '.join(snapshot.data_sources)}")
    print(f"  最新报告期: {snapshot.latest_report_period}")
    if snapshot.warnings:
        print(f"  警告: {', '.join(snapshot.warnings)}")

    # 保存原始数据
    raw_dir = live_dir / "raw_data"
    raw_dir.mkdir(exist_ok=True)
    for attr in ['price_history', 'balancesheet', 'income', 'cashflow',
                 'fina_indicator', 'dividend', 'top10_holders',
                 'news', 'fund_flow', 'index_daily', 'industry_summary']:
        df = getattr(snapshot, attr, None)
        if df is not None and not df.empty:
            df.to_csv(raw_dir / f"{attr}.csv", index=False, encoding='utf-8-sig')

    # 保存 snapshot 元数据
    snap_meta = {
        'ts_code': snapshot.ts_code,
        'stock_name': snapshot.stock_name,
        'industry': snapshot.industry,
        'cutoff_date': snapshot.cutoff_date,
        'generated_at': snapshot.generated_at,
        'latest_report_period': snapshot.latest_report_period,
        'data_sources': snapshot.data_sources,
        'warnings': snapshot.warnings,
    }
    (live_dir / "snapshot.json").write_text(
        json.dumps(snap_meta, ensure_ascii=False, indent=2), encoding='utf-8')

    # 2. Agent 分析
    print(f"\n[2/3] Agent 分析 ({'盲测' if blind_mode else '非盲测'})...")
    result = asyncio.run(
        run_blind_analysis(ts_code, cutoff_date, config, blind_mode, live_dir)
    )

    # 3. 输出结果
    meta = result["metadata"]
    synthesis = result.get("synthesis", {})
    print(f"\n[3/3] 分析完成")
    print(f"  耗时: {meta['elapsed_seconds']:.0f}秒")
    print(f"  模型: {meta['model']}")
    print(f"  章节: {meta['chapters_completed']} 章")

    if synthesis:
        print(f"\n{'='*60}")
        print(f"综合研判: {snapshot.stock_name} ({ts_code})")
        print(f"{'='*60}")
        score = synthesis.get('综合评分', '?')
        rec = synthesis.get('最终建议', '?')
        stream = synthesis.get('流派判定', '?')
        print(f"  评分: {score}")
        print(f"  建议: {rec}")
        print(f"  流派: {stream}")
        buy_logic = synthesis.get('一句话买入逻辑（强制）', '')
        if buy_logic:
            print(f"  买入逻辑: {buy_logic[:80]}")
        risks = synthesis.get('关键风险', [])
        if risks:
            print(f"  关键风险:")
            for r in risks[:3]:
                print(f"    - {r}")

    print(f"\n输出目录: {live_dir}")
    print(f"  raw_data/    原始数据")
    print(f"  snapshot.json 快照元数据")
    print(f"  *_report.md  完整分析报告")
    print(f"  *_structured.json 结构化结论")
    print(f"  run.log      运行日志")

    # 清理日志 handler
    logging.getLogger().removeHandler(file_handler)


def _cmd_agent_analyze(config: StrategyConfig, args: list):
    """Agent 驱动的自动分析"""
    if len(args) < 2:
        print("用法: agent-analyze <ts_code> <cutoff_date> [--no-blind]")
        sys.exit(1)

    import asyncio
    from src.agent.runtime import run_blind_analysis

    ts_code = args[0]
    cutoff_date = args[1]
    blind_mode = "--no-blind" not in args

    output_dir = config.get_backtest_dir() / "agent_reports"
    print(f"Agent 分析: {ts_code} @ {cutoff_date} ({'盲测' if blind_mode else '非盲测'})")
    print(f"输出目录: {output_dir}")
    print()

    result = asyncio.run(
        run_blind_analysis(ts_code, cutoff_date, config, blind_mode, output_dir)
    )

    meta = result["metadata"]
    print(f"\n分析完成: {meta['chapters_completed']} 章, {meta['elapsed_seconds']}秒")
    print(f"模型: {meta['model']}")

    synthesis = result.get("synthesis", {})
    if synthesis:
        print(f"\n综合研判:")
        for k, v in synthesis.items():
            print(f"  {k}: {v}")


def _cmd_batch_analyze(config: StrategyConfig, args: list):
    """筛选 + 批量 Agent 分析"""
    if not args:
        print("用法: batch-analyze <cutoff_date> [--top N] [--no-blind]")
        sys.exit(1)

    import asyncio
    from src.screener.quick_filter import screen_at_date, format_screen_result
    from src.agent.runtime import run_blind_analysis

    cutoff_date = args[0]
    blind_mode = "--no-blind" not in args
    top_n = 50
    if '--top' in args:
        idx = args.index('--top')
        if idx + 1 < len(args):
            top_n = int(args[idx + 1])

    # Step 1: 量化筛选
    print(f"[1/2] 量化筛选: {cutoff_date} (top {top_n})")
    result = screen_at_date(cutoff_date, top_n=top_n, config=config)
    print(format_screen_result(result))

    if result.candidates.empty:
        print("无候选股票，退出。")
        return

    # Step 2: 确定 agent 分析数量
    total = len(result.candidates)
    batch_n = config.get_agent_batch_size(total)
    codes = result.candidates['ts_code'].head(batch_n).tolist()

    print(f"\n[2/2] Agent 批量分析: {batch_n}/{total} 只 "
          f"(ratio={config.get_agent_batch_config().get('ratio')}, "
          f"max={config.get_agent_batch_config().get('max')})")
    print(f"  股票列表: {', '.join(codes)}")
    print(f"  模式: {'盲测' if blind_mode else '非盲测'}")
    print()

    output_dir = config.get_backtest_dir() / "agent_reports"

    # 逐个分析（串行，避免 API 限流）
    summaries = []
    for i, ts_code in enumerate(codes, 1):
        print(f"--- [{i}/{batch_n}] {ts_code} ---")
        try:
            r = asyncio.run(
                run_blind_analysis(ts_code, cutoff_date, config, blind_mode, output_dir)
            )
            meta = r["metadata"]
            synthesis = r.get("synthesis", {})
            score = synthesis.get("综合评分", "?")
            recommendation = synthesis.get("最终建议", "?")
            print(f"  完成: {meta['elapsed_seconds']}s | 评分: {score} | 建议: {recommendation}")
            summaries.append({
                "ts_code": ts_code,
                "score": score,
                "recommendation": recommendation,
                "elapsed": meta['elapsed_seconds'],
            })
        except Exception as e:
            print(f"  失败: {e}")
            summaries.append({
                "ts_code": ts_code,
                "score": "ERR",
                "recommendation": str(e)[:50],
                "elapsed": 0,
            })

    # 汇总
    print(f"\n{'='*60}")
    print(f"批量分析完成: {len([s for s in summaries if s['score'] != 'ERR'])}/{batch_n} 成功")
    print(f"{'='*60}")
    print(f"{'股票':<12} {'评分':<8} {'建议':<8} {'耗时':<8}")
    print(f"{'-'*12} {'-'*8} {'-'*8} {'-'*8}")
    for s in summaries:
        print(f"{s['ts_code']:<12} {str(s['score']):<8} {str(s['recommendation']):<8} {s['elapsed']}s")


def _cmd_backtest_screen(config: StrategyConfig, args: list):
    """Step 1: 生成截面日期 + 逐截面筛选 + 保存 CSV"""
    from src.backtest.pipeline import step_screen
    step_screen(config)


def _cmd_backtest_agent(config: StrategyConfig, args: list):
    """Step 2: 并发 Agent 分析 (增量/重试/进度)"""
    from src.backtest.pipeline import step_agent
    max_retry = 1
    dry_run = '--dry-run' in args
    if '--retry' in args:
        idx = args.index('--retry')
        if idx + 1 < len(args):
            max_retry = int(args[idx + 1])
    step_agent(config, max_retry=max_retry, dry_run=dry_run)


def _cmd_backtest_eval(config: StrategyConfig, args: list):
    """Step 3: 采集前向收益 + 多基准绩效评估"""
    from src.backtest.pipeline import step_eval
    step_eval(config)


if __name__ == '__main__':
    main()
