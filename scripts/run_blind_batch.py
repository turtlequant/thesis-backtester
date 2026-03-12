#!/usr/bin/env python3
"""
批量盲测分析 — 用 claude -p (订阅模式) 多线程并发执行

用法:
    python scripts/run_blind_batch.py                      # 默认20并发
    python scripts/run_blind_batch.py --concurrency 10     # 指定并发数
    python scripts/run_blind_batch.py --model sonnet       # 指定模型
    python scripts/run_blind_batch.py --dry-run            # 仅列出待处理
    python scripts/run_blind_batch.py --retry-failed       # 重试失败的
    python scripts/run_blind_batch.py --validate           # 仅验证已有报告
"""
import argparse
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent
STRATEGY_DIR = PROJECT_ROOT / "strategies" / "v556_value"
PROMPTS_DIR = STRATEGY_DIR / "backtest" / "prompts"
REPORTS_DIR = STRATEGY_DIR / "backtest" / "reports"
LOG_DIR = STRATEGY_DIR / "backtest" / "logs"

SYSTEM_PROMPT = """你是一位严谨的价值投资分析师，正在进行盲测分析。你将收到一份匿名公司的财务数据快照，请按照模版框架逐章分析。

关键要求：
1. 严格基于提供的数据进行分析，不要猜测公司身份
2. 按10章框架逐章给出分析
3. 最终必须给出：流派判定、龟级评定、综合评分(X/100)、投资建议(买入/观望/回避)
4. 综合评分格式必须为: 综合评分: XX/100"""


def get_pending_prompts(retry_failed=False):
    """获取待处理的 prompt 文件列表"""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    pending = []
    done = []
    failed = []

    for prompt_file in sorted(PROMPTS_DIR.glob("*.txt")):
        sid = prompt_file.stem
        report_file = REPORTS_DIR / f"{sid}_report.md"

        if report_file.exists() and report_file.stat().st_size > 0:
            text = report_file.read_text(encoding='utf-8')
            if _validate_report(text):
                done.append(sid)
            else:
                failed.append((prompt_file, "报告格式不完整"))
        else:
            pending.append(prompt_file)

    if retry_failed:
        for pf, reason in failed:
            pending.append(pf)

    return pending, done, failed


def _validate_report(text):
    """验证报告是否包含关键输出"""
    has_score = bool(re.search(r'(\d+)/100', text))
    has_recommendation = any(kw in text for kw in ['买入', '观望', '回避'])
    min_length = len(text) > 2000
    return has_score and has_recommendation and min_length


def analyze_one(prompt_file, model="sonnet"):
    """调用 claude -p 分析单个样本"""
    sid = prompt_file.stem
    report_file = REPORTS_DIR / f"{sid}_report.md"
    log_file = LOG_DIR / f"{sid}.log"

    # 跳过已完成
    if report_file.exists() and report_file.stat().st_size > 0:
        text = report_file.read_text(encoding='utf-8')
        if _validate_report(text):
            return sid, "skipped", 0

    start = time.time()

    try:
        prompt_text = prompt_file.read_text(encoding='utf-8')

        # 将 system prompt 拼接到用户 prompt 前面
        full_prompt = f"{SYSTEM_PROMPT}\n\n---\n\n{prompt_text}"

        env = os.environ.copy()
        env.pop("CLAUDECODE", None)  # 避免嵌套会话检测

        result = subprocess.run(
            ["claude", "-p", "--model", model],
            input=full_prompt,
            capture_output=True,
            text=True,
            timeout=600,  # 10分钟超时
            env=env,
        )

        duration = time.time() - start

        if result.returncode == 0 and len(result.stdout) > 1000:
            report_file.write_text(result.stdout, encoding='utf-8')

            if result.stderr:
                log_file.write_text(result.stderr, encoding='utf-8')

            if _validate_report(result.stdout):
                return sid, "ok", duration
            else:
                return sid, "incomplete", duration
        else:
            error_msg = f"exit={result.returncode}\nstdout_len={len(result.stdout)}\nstderr={result.stderr[:500]}"
            log_file.write_text(error_msg, encoding='utf-8')
            report_file.unlink(missing_ok=True)
            return sid, "error", duration

    except subprocess.TimeoutExpired:
        duration = time.time() - start
        return sid, "timeout", duration
    except Exception as e:
        duration = time.time() - start
        log_file.write_text(str(e), encoding='utf-8')
        return sid, "exception", duration


def validate_reports():
    """验证所有已有报告"""
    print("验证已有报告...")
    valid = 0
    invalid = []

    for report_file in sorted(REPORTS_DIR.glob("*_report.md")):
        text = report_file.read_text(encoding='utf-8')
        if _validate_report(text):
            valid += 1
        else:
            sid = report_file.stem.replace("_report", "")
            score_match = re.search(r'(\d+)/100', text)
            score = score_match.group(1) if score_match else "无"
            has_rec = any(kw in text for kw in ['买入', '观望', '回避'])
            invalid.append((sid, len(text), score, has_rec))

    print(f"  有效: {valid}")
    print(f"  无效: {len(invalid)}")
    for sid, size, score, has_rec in invalid[:20]:
        print(f"    {sid}: {size}B, 评分={score}, 建议={'有' if has_rec else '无'}")

    return valid, invalid


def main():
    parser = argparse.ArgumentParser(description="批量盲测分析")
    parser.add_argument("--concurrency", "-c", type=int, default=20)
    parser.add_argument("--model", "-m", default="sonnet")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    if args.validate:
        validate_reports()
        return

    pending, done, failed = get_pending_prompts(retry_failed=args.retry_failed)

    print("=" * 50)
    print("  批量盲测分析 (claude -p 订阅模式)")
    print("=" * 50)
    print(f"  模型:     {args.model}")
    print(f"  并发数:   {args.concurrency}")
    print(f"  总prompt: {len(list(PROMPTS_DIR.glob('*.txt')))}")
    print(f"  已完成:   {len(done)}")
    print(f"  待处理:   {len(pending)}")
    print(f"  格式异常: {len(failed)}")
    print("=" * 50)

    if not pending:
        print("所有样本已处理完毕！")
        return

    if args.dry_run:
        print("\n待处理样本:")
        for f in pending:
            print(f"  {f.stem}")
        return

    # 先验证 claude 能否正常运行
    print("\n验证 claude CLI...")
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    test = subprocess.run(
        ["claude", "-p", "--model", args.model],
        input="回复OK",
        capture_output=True, text=True, timeout=30, env=env,
    )
    if test.returncode != 0:
        print(f"  错误: claude -p 无法运行")
        print(f"  stderr: {test.stderr[:300]}")
        print(f"\n请先运行 'claude' 并执行 /login 登录")
        sys.exit(1)
    print(f"  OK: {test.stdout[:50].strip()}")

    print(f"\n开始处理 {len(pending)} 个样本 ({datetime.now().strftime('%H:%M:%S')})...\n")

    start_all = time.time()
    results = {"ok": 0, "skipped": 0, "incomplete": 0, "error": 0, "timeout": 0, "exception": 0}

    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = {
            executor.submit(analyze_one, pf, args.model): pf
            for pf in pending
        }

        completed = 0
        for future in as_completed(futures):
            sid, status, duration = future.result()
            completed += 1
            results[status] = results.get(status, 0) + 1

            elapsed = time.time() - start_all
            rate = completed / elapsed if elapsed > 0 else 0
            eta = (len(pending) - completed) / rate if rate > 0 else 0

            if status == "ok":
                print(f"  [{completed}/{len(pending)}] {sid} OK ({duration:.0f}s)  "
                      f"ETA: {eta/60:.1f}min")
            elif status != "skipped":
                print(f"  [{completed}/{len(pending)}] {sid} {status.upper()} ({duration:.0f}s)")

    elapsed_all = time.time() - start_all

    print()
    print("=" * 50)
    print("  完成统计")
    print("=" * 50)
    print(f"  成功:   {results['ok']}")
    print(f"  跳过:   {results['skipped']}")
    print(f"  不完整: {results['incomplete']}")
    print(f"  失败:   {results['error']}")
    print(f"  超时:   {results['timeout']}")
    print(f"  异常:   {results['exception']}")
    print(f"  耗时:   {elapsed_all:.0f}s ({elapsed_all/60:.1f}min)")
    print("=" * 50)

    if results['error'] + results['timeout'] + results['incomplete'] > 0:
        print(f"\n提示: 有失败/不完整的样本，可用 --retry-failed 重试")


if __name__ == "__main__":
    main()
