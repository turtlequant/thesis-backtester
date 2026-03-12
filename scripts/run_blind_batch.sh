#!/usr/bin/env bash
#
# 批量盲测分析 — 用 claude -p 并发执行
#
# 用法:
#   ./scripts/run_blind_batch.sh                    # 默认20并发
#   ./scripts/run_blind_batch.sh --concurrency 10   # 指定并发数
#   ./scripts/run_blind_batch.sh --model sonnet      # 指定模型
#   ./scripts/run_blind_batch.sh --dry-run           # 仅列出待处理任务
#
# 前置条件:
#   - claude CLI 已安装并配置好 API key
#   - strategies/v556_value/backtest/prompts/ 下有 prompt 文件
#
# 输出:
#   strategies/v556_value/backtest/reports/{sample_id}_report.md

set -euo pipefail

# ==================== 配置 ====================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
STRATEGY_DIR="$PROJECT_ROOT/strategies/v556_value"
PROMPTS_DIR="$STRATEGY_DIR/backtest/prompts"
REPORTS_DIR="$STRATEGY_DIR/backtest/reports"
LOG_DIR="$STRATEGY_DIR/backtest/logs"

CONCURRENCY=20
MODEL="sonnet"
DRY_RUN=false

# ==================== 参数解析 ====================

while [[ $# -gt 0 ]]; do
    case $1 in
        --concurrency|-c) CONCURRENCY="$2"; shift 2 ;;
        --model|-m)       MODEL="$2"; shift 2 ;;
        --dry-run)        DRY_RUN=true; shift ;;
        *) echo "未知参数: $1"; exit 1 ;;
    esac
done

# ==================== 初始化 ====================

mkdir -p "$REPORTS_DIR" "$LOG_DIR"

# 统计待处理
total=0
pending=0
done=0
failed_count=0
prompt_files=()

for prompt_file in "$PROMPTS_DIR"/*.txt; do
    [[ -f "$prompt_file" ]] || continue
    total=$((total + 1))

    basename=$(basename "$prompt_file" .txt)
    report_file="$REPORTS_DIR/${basename}_report.md"

    if [[ -f "$report_file" ]] && [[ -s "$report_file" ]]; then
        done=$((done + 1))
    else
        pending=$((pending + 1))
        prompt_files+=("$prompt_file")
    fi
done

echo "=========================================="
echo "  批量盲测分析"
echo "=========================================="
echo "  模型:     $MODEL"
echo "  并发数:   $CONCURRENCY"
echo "  总样本:   $total"
echo "  已完成:   $done"
echo "  待处理:   $pending"
echo "=========================================="

if [[ $pending -eq 0 ]]; then
    echo "所有样本已处理完毕！"
    exit 0
fi

if $DRY_RUN; then
    echo ""
    echo "待处理样本:"
    for f in "${prompt_files[@]}"; do
        echo "  $(basename "$f" .txt)"
    done
    exit 0
fi

# ==================== 系统提示词 ====================

SYSTEM_PROMPT="你是一位严谨的价值投资分析师，正在进行盲测分析。你将收到一份匿名公司的财务数据快照，请按照模版框架逐章分析。

关键要求：
1. 严格基于提供的数据进行分析，不要猜测公司身份
2. 按10章框架逐章给出分析
3. 最终必须给出：流派判定、龟级评定、综合评分(X/100)、投资建议(买入/观望/回避)
4. 综合评分格式必须为: 综合评分: XX/100"

# ==================== 单个分析函数 ====================

analyze_one() {
    local prompt_file="$1"
    local basename=$(basename "$prompt_file" .txt)
    local report_file="$REPORTS_DIR/${basename}_report.md"
    local log_file="$LOG_DIR/${basename}.log"

    # 跳过已完成
    if [[ -f "$report_file" ]] && [[ -s "$report_file" ]]; then
        return 0
    fi

    local start_time=$(date +%s)

    # 调用 claude -p（清除嵌套检测）
    unset CLAUDECODE
    if claude -p \
        --model "$MODEL" \
        --append-system-prompt "$SYSTEM_PROMPT" \
        < "$prompt_file" \
        > "$report_file" \
        2> "$log_file"; then

        local end_time=$(date +%s)
        local duration=$((end_time - start_time))
        local report_size=$(wc -c < "$report_file")
        echo "[OK] $basename  (${duration}s, ${report_size}B)"
    else
        local exit_code=$?
        local end_time=$(date +%s)
        local duration=$((end_time - start_time))
        echo "[FAIL] $basename  (exit=$exit_code, ${duration}s)" >&2
        # 删除可能的空/不完整报告
        rm -f "$report_file"
        return 1
    fi
}

export -f analyze_one
export REPORTS_DIR LOG_DIR MODEL SYSTEM_PROMPT

# ==================== 并发执行 ====================

echo ""
echo "开始处理 $pending 个样本 ($(date '+%H:%M:%S'))..."
echo ""

start_all=$(date +%s)

# 用 xargs 并发
printf '%s\n' "${prompt_files[@]}" | \
    xargs -P "$CONCURRENCY" -I {} bash -c 'analyze_one "$@"' _ {}

end_all=$(date +%s)
duration_all=$((end_all - start_all))

# ==================== 统计结果 ====================

echo ""
echo "=========================================="
echo "  完成统计"
echo "=========================================="

final_done=0
final_missing=0
for prompt_file in "$PROMPTS_DIR"/*.txt; do
    basename=$(basename "$prompt_file" .txt)
    report_file="$REPORTS_DIR/${basename}_report.md"
    if [[ -f "$report_file" ]] && [[ -s "$report_file" ]]; then
        final_done=$((final_done + 1))
    else
        final_missing=$((final_missing + 1))
    fi
done

echo "  总样本:    $total"
echo "  已完成:    $final_done"
echo "  未完成:    $final_missing"
echo "  本轮耗时:  ${duration_all}s"
echo "=========================================="

if [[ $final_missing -gt 0 ]]; then
    echo ""
    echo "提示: 有 $final_missing 个未完成，可重新运行此脚本继续处理"
fi
