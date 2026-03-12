"""
批量盲测分析

为选定的样本股票生成盲测prompt，运行AI分析，汇总对比结果。
支持通过 StrategyConfig 配置评分提取和报告阈值。

用法:
    python -m src.screener.blind_batch generate
    python -m src.screener.blind_batch analyze <sample_id>
    python -m src.screener.blind_batch report
    python -m src.screener.blind_batch generate --strategy strategies/v556_value/strategy.yaml
"""
import json
import os
import re
import sys
from pathlib import Path
from typing import List, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.engine.config import StrategyConfig


def _resolve_paths(config: Optional["StrategyConfig"] = None):
    """从 config 获取回测数据路径，或使用默认路径"""
    if config is None:
        from src.engine.config import get_default_config
        config = get_default_config()
    bt_dir = config.get_backtest_dir()
    return (
        bt_dir / "samples.json",
        bt_dir / "prompts",
        bt_dir / "reports",
        bt_dir,
    )


# ==================== 默认值（向后兼容） ====================

_DEFAULT_SCORE_PATTERNS = [
    r'综合评分[：:]\s*\**(\d+)/100\**',
    r'综合评分[：:]\s*\**(\d+)\**\s*/\s*100',
    r'\*\*(\d+)/100\*\*',
    r'(\d+)/100',
]

_DEFAULT_REC_PATTERNS = [
    r'投资(?:决策|建议)[：:]\s*\**([^*\n]+)\**',
    r'建议[：:]\s*\**([^*\n]+)\**',
]

_DEFAULT_BUY_KEYWORDS = ['买入', '建仓']
_DEFAULT_AVOID_KEYWORDS = ['回避', '排除', '不建议']
_DEFAULT_HOLD_KEYWORDS = ['观望', '持有']

_DEFAULT_THRESHOLDS = {
    'buy_score_min': 60,
    'avoid_score_max': 50,
    'false_positive_return': -10,
    'false_negative_return': 10,
}


def _resolve_blind_config(config: Optional["StrategyConfig"] = None):
    """从 config 提取盲测参数"""
    if config is not None:
        bt = config.get_blind_test_config()
        score_patterns = config.get_score_patterns()
        rec_config = config.get_recommendation_config()
        rec_patterns = rec_config.get('patterns', _DEFAULT_REC_PATTERNS)
        buy_kw = rec_config.get('buy_keywords', _DEFAULT_BUY_KEYWORDS)
        avoid_kw = rec_config.get('avoid_keywords', _DEFAULT_AVOID_KEYWORDS)
        hold_kw = rec_config.get('hold_keywords', _DEFAULT_HOLD_KEYWORDS)
        thresholds = config.get_thresholds()
        report_title = bt.get('report_title', '盲测AI分析验证报告')
    else:
        score_patterns = _DEFAULT_SCORE_PATTERNS
        rec_patterns = _DEFAULT_REC_PATTERNS
        buy_kw = _DEFAULT_BUY_KEYWORDS
        avoid_kw = _DEFAULT_AVOID_KEYWORDS
        hold_kw = _DEFAULT_HOLD_KEYWORDS
        thresholds = _DEFAULT_THRESHOLDS
        report_title = '6年盲测AI分析验证报告'

    return score_patterns, rec_patterns, buy_kw, avoid_kw, hold_kw, thresholds, report_title


def load_samples(config: Optional["StrategyConfig"] = None) -> List[Dict]:
    samples_file, _, _, _ = _resolve_paths(config)
    if not samples_file.exists():
        raise FileNotFoundError(f"样本文件不存在: {samples_file}")
    with open(samples_file, encoding='utf-8') as f:
        return json.load(f)


def sample_id(sample: Dict) -> str:
    """生成样本唯一ID: cutoff_tsCode"""
    return f"{sample['cutoff_date']}_{sample['ts_code'].replace('.', '_')}"


def generate_all_prompts(config: Optional["StrategyConfig"] = None):
    """为所有样本生成盲测prompt文件"""
    from src.data.snapshot import create_snapshot
    from src.analyzer.prompt_builder import build_full_analysis_prompt

    _, prompts_dir, _, _ = _resolve_paths(config)
    samples = load_samples(config=config)
    prompts_dir.mkdir(parents=True, exist_ok=True)

    print(f"生成 {len(samples)} 个盲测prompt...")

    for i, sample in enumerate(samples, 1):
        sid = sample_id(sample)
        prompt_file = prompts_dir / f"{sid}.txt"

        if prompt_file.exists():
            print(f"  [{i}/{len(samples)}] {sid} 已存在，跳过")
            continue

        ts_code = sample['ts_code']
        cutoff_date = sample['cutoff_date']

        print(f"  [{i}/{len(samples)}] {sid} ({sample['stock_name']})...", end=' ')
        try:
            snapshot = create_snapshot(ts_code, cutoff_date)
            prompt = build_full_analysis_prompt(
                ts_code, cutoff_date,
                snapshot=snapshot,
                blind_mode=True,
                config=config,
            )
            prompt_file.write_text(prompt, encoding='utf-8')
            print(f"OK ({len(prompt)} chars)")
        except Exception as e:
            print(f"失败: {e}")

    print(f"\nprompt已保存至 {prompts_dir}")


def analyze_single(sid: str, config: Optional["StrategyConfig"] = None) -> Optional[str]:
    """读取prompt文件，返回prompt文本供Agent分析。"""
    _, prompts_dir, _, _ = _resolve_paths(config)
    prompt_file = prompts_dir / f"{sid}.txt"
    if not prompt_file.exists():
        print(f"prompt文件不存在: {prompt_file}")
        return None

    return prompt_file.read_text(encoding='utf-8')


def extract_score_from_report(
    report_text: str,
    config: Optional["StrategyConfig"] = None,
) -> Dict:
    """从分析报告中提取评分和建议"""
    score_patterns, rec_patterns, buy_kw, avoid_kw, hold_kw, _, _ = _resolve_blind_config(config)

    result = {
        'score': None,
        'recommendation': None,
    }

    for pat in score_patterns:
        m = re.search(pat, report_text)
        if m:
            result['score'] = int(m.group(1))
            break

    for pat in rec_patterns:
        m = re.search(pat, report_text)
        if m:
            rec = m.group(1).strip()
            if any(w in rec for w in buy_kw):
                result['recommendation'] = '买入'
            elif any(w in rec for w in avoid_kw):
                result['recommendation'] = '回避'
            elif any(w in rec for w in hold_kw):
                result['recommendation'] = '观望'
            else:
                result['recommendation'] = rec
            break

    return result


def generate_report(config: Optional["StrategyConfig"] = None):
    """汇总所有盲测结果，对比AI评分与实际收益"""
    _, _, _, _, _, thresholds, report_title = _resolve_blind_config(config)
    _, _, reports_dir, bt_dir = _resolve_paths(config)

    buy_min = thresholds['buy_score_min']
    avoid_max = thresholds['avoid_score_max']
    fp_return = thresholds['false_positive_return']
    fn_return = thresholds['false_negative_return']

    samples = load_samples(config=config)
    reports_dir.mkdir(parents=True, exist_ok=True)

    results = []
    missing = []

    for sample in samples:
        sid = sample_id(sample)
        report_file = reports_dir / f"{sid}_report.md"

        if not report_file.exists():
            missing.append(sid)
            continue

        report_text = report_file.read_text(encoding='utf-8')
        extracted = extract_score_from_report(report_text, config=config)

        results.append({
            **sample,
            'sample_id': sid,
            'ai_score': extracted['score'],
            'ai_recommendation': extracted['recommendation'],
        })

    if missing:
        print(f"警告: {len(missing)} 个样本缺少分析报告")

    if not results:
        print("无结果可汇总")
        return

    lines = [
        f"# {report_title}",
        "",
        f"**样本数**: {len(results)} / {len(samples)}",
        "",
        "## 全部样本明细",
        "",
        "| 截面 | 股票 | 龟级 | AI评分 | AI建议 | 实际6m收益 | AI判断 |",
        "|------|------|------|--------|--------|-----------|--------|",
    ]

    correct = 0
    total_with_score = 0
    buy_returns = []
    avoid_returns = []

    for r in sorted(results, key=lambda x: (x['cutoff_date'], -x['fwd_6m'])):
        score_str = str(r['ai_score']) if r['ai_score'] else "?"
        rec_str = r['ai_recommendation'] or "?"
        ret_str = f"{r['fwd_6m']:+.1f}%"

        if r['ai_score'] is not None:
            total_with_score += 1
            if r['ai_recommendation'] == '买入':
                buy_returns.append(r['fwd_6m'])
            elif r['ai_recommendation'] == '回避':
                avoid_returns.append(r['fwd_6m'])

            if (r['ai_score'] >= buy_min and r['fwd_6m'] > 0) or \
               (r['ai_score'] < avoid_max and r['fwd_6m'] < fp_return):
                judgment = "正确"
                correct += 1
            elif (r['ai_score'] >= buy_min and r['fwd_6m'] < fp_return):
                judgment = "错误(假阳)"
            elif (r['ai_score'] < avoid_max and r['fwd_6m'] > fn_return):
                judgment = "错误(假阴)"
            else:
                judgment = "中性"
        else:
            judgment = "-"

        lines.append(
            f"| {r['cutoff_date']} | {r['stock_name']} "
            f"| {r['turtle_rating']} | {score_str} | {rec_str} "
            f"| {ret_str} | {judgment} |"
        )

    lines.extend(["", "## 统计汇总", ""])

    if total_with_score > 0:
        lines.append(f"- **有效评分样本**: {total_with_score}")
        lines.append(f"- **方向正确率**: {correct}/{total_with_score} = {correct/total_with_score*100:.0f}%")

    if buy_returns:
        avg_buy = sum(buy_returns) / len(buy_returns)
        win_buy = sum(1 for r in buy_returns if r > 0) / len(buy_returns) * 100
        lines.extend([
            "",
            f"### AI建议「买入」的股票 ({len(buy_returns)}只)",
            f"- 平均6m收益: {avg_buy:+.1f}%",
            f"- 胜率: {win_buy:.0f}%",
        ])

    if avoid_returns:
        avg_avoid = sum(avoid_returns) / len(avoid_returns)
        lines.extend([
            "",
            f"### AI建议「回避」的股票 ({len(avoid_returns)}只)",
            f"- 平均6m收益: {avg_avoid:+.1f}%",
        ])

    all_returns = [r['fwd_6m'] for r in results]
    if all_returns:
        avg_all = sum(all_returns) / len(all_returns)
        lines.extend([
            "",
            "### 策略对比",
            f"- **纯量化选股**: {len(all_returns)}只, 平均6m收益={avg_all:+.1f}%",
        ])
        if buy_returns:
            lines.append(f"- **量化+AI过滤(仅买入)**: {len(buy_returns)}只, 平均6m收益={sum(buy_returns)/len(buy_returns):+.1f}%")
            improvement = sum(buy_returns)/len(buy_returns) - avg_all
            lines.append(f"- **AI过滤增益**: {improvement:+.1f}个百分点")

    lines.extend(["", "## 按截面分组", ""])
    lines.append("| 截面 | 样本 | 纯量化均收益 | AI买入均收益 | AI回避均收益 |")
    lines.append("|------|------|-------------|-------------|-------------|")

    from collections import defaultdict
    by_date = defaultdict(list)
    for r in results:
        by_date[r['cutoff_date']].append(r)

    for date in sorted(by_date.keys()):
        rs = by_date[date]
        all_ret = [r['fwd_6m'] for r in rs]
        buy_ret = [r['fwd_6m'] for r in rs if r.get('ai_recommendation') == '买入']
        avoid_ret = [r['fwd_6m'] for r in rs if r.get('ai_recommendation') == '回避']

        avg_all_d = sum(all_ret) / len(all_ret) if all_ret else float('nan')
        avg_buy_d = sum(buy_ret) / len(buy_ret) if buy_ret else float('nan')
        avg_avoid_d = sum(avoid_ret) / len(avoid_ret) if avoid_ret else float('nan')

        all_str = f"{avg_all_d:+.1f}%" if all_ret else "-"
        buy_str = f"{avg_buy_d:+.1f}% ({len(buy_ret)}只)" if buy_ret else "-"
        avoid_str = f"{avg_avoid_d:+.1f}% ({len(avoid_ret)}只)" if avoid_ret else "-"

        lines.append(f"| {date} | {len(rs)} | {all_str} | {buy_str} | {avoid_str} |")

    report_text = '\n'.join(lines)

    report_file = bt_dir / "validation_report.md"
    report_file.write_text(report_text, encoding='utf-8')
    print(report_text)
    print(f"\n报告已保存: {report_file}")


# ==================== CLI ====================

def main():
    if len(sys.argv) < 2:
        print("用法:")
        print("  python -m src.screener.blind_batch generate  # 生成prompt")
        print("  python -m src.screener.blind_batch analyze <sample_id>  # 分析单个")
        print("  python -m src.screener.blind_batch report   # 汇总报告")
        print("  添加 --strategy <yaml> 指定策略配置")
        sys.exit(1)

    config = None
    if '--strategy' in sys.argv:
        idx = sys.argv.index('--strategy')
        if idx + 1 < len(sys.argv):
            from src.engine.config import StrategyConfig
            config = StrategyConfig.from_yaml(sys.argv[idx + 1])
            print(f"使用策略: {config.name}")

    cmd = sys.argv[1]
    if cmd == 'generate':
        generate_all_prompts(config=config)
    elif cmd == 'analyze':
        if len(sys.argv) < 3:
            print("需要 sample_id")
            sys.exit(1)
        sid = sys.argv[2]
        prompt = analyze_single(sid, config=config)
        if prompt:
            print(prompt[:500] + "...")
    elif cmd == 'report':
        generate_report(config=config)
    else:
        print(f"未知命令: {cmd}")


if __name__ == '__main__':
    main()
