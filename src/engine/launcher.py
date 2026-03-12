"""
策略启动器

统一入口，加载策略配置后 dispatch 到对应模块。

用法:
    python -m src.engine.launcher strategies/v556_value/strategy.yaml screen 2024-06-30
    python -m src.engine.launcher strategies/v556_value/strategy.yaml screen 2024-06-30 --top 30
    python -m src.engine.launcher strategies/v556_value/strategy.yaml analyze 601288.SH 2024-06-30
    python -m src.engine.launcher strategies/v556_value/strategy.yaml analyze 601288.SH 2024-06-30 --blind
    python -m src.engine.launcher strategies/v556_value/strategy.yaml blind-generate
    python -m src.engine.launcher strategies/v556_value/strategy.yaml blind-report
    python -m src.engine.launcher strategies/v556_value/strategy.yaml parse-template
"""
import sys

from .config import StrategyConfig


def main():
    if len(sys.argv) < 3:
        print("用法: python -m src.engine.launcher <strategy.yaml> <command> [args...]")
        print()
        print("命令:")
        print("  screen <cutoff_date> [--top N]        量化筛选")
        print("  analyze <ts_code> <cutoff_date>       单股分析（生成prompt）")
        print("  blind-generate                        批量生成盲测prompt")
        print("  blind-report                          汇总盲测结果报告")
        print("  parse-template                        解析投资模版为章节")
        print()
        print("示例:")
        print("  python -m src.engine.launcher strategies/v556_value/strategy.yaml screen 2024-06-30")
        sys.exit(1)

    yaml_path = sys.argv[1]
    command = sys.argv[2]
    extra_args = sys.argv[3:]

    config = StrategyConfig.from_yaml(yaml_path)
    print(f"策略: {config.name} (v{config.version})")
    print()

    if command == "screen":
        _cmd_screen(config, extra_args)
    elif command == "analyze":
        _cmd_analyze(config, extra_args)
    elif command == "blind-generate":
        _cmd_blind_generate(config)
    elif command == "blind-report":
        _cmd_blind_report(config)
    elif command == "parse-template":
        _cmd_parse_template(config)
    else:
        print(f"未知命令: {command}")
        sys.exit(1)


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


def _cmd_analyze(config: StrategyConfig, args: list):
    """单股分析"""
    if len(args) < 2:
        print("用法: analyze <ts_code> <cutoff_date> [--blind]")
        sys.exit(1)

    from src.analyzer.analysis_runner import prepare_analysis

    ts_code = args[0]
    cutoff_date = args[1]
    blind_mode = '--blind' in args

    prepare_analysis(ts_code, cutoff_date, blind_mode=blind_mode, config=config)


def _cmd_blind_generate(config: StrategyConfig):
    """批量生成盲测prompt"""
    from src.screener.blind_batch import generate_all_prompts
    generate_all_prompts(config=config)


def _cmd_blind_report(config: StrategyConfig):
    """汇总盲测结果"""
    from src.screener.blind_batch import generate_report
    generate_report(config=config)


def _cmd_parse_template(config: StrategyConfig):
    """解析投资模版为章节"""
    from src.analyzer.framework_parser import parse_template, save_chunks

    chunks = parse_template(config=config)
    print(f"解析完成, 共 {len(chunks)} 章:")
    for chunk in chunks:
        print(f"  Ch{chunk.chapter}: {chunk.title} ({chunk.line_count} 行, {chunk.char_count} 字符)")

    out_dir = save_chunks(chunks, config=config)
    print(f"\n已保存到: {out_dir}")


if __name__ == '__main__':
    main()
