"""
分析质量评估器

5维度评分体系，评估分析框架在特定截面的有效性。

维度：
  1. 估值方向（40%）— 分析给出的估值方向是否正确
  2. 建议质量（25%）— 买入/观望/回避建议的实际收益
  3. 风险识别（15%）— 实际发生的风险是否被预警
  4. 安全边际（10%）— 安全边际判断是否有效保护了下行风险
  5. 分红预测（10%）— 分红预测的准确性

用法:
    python -m src.backtest.quality_scorer <run_id>
"""
import json
import sqlite3
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field

from src.data.settings import ANALYSIS_DB_PATH
from src.analyzer.analysis_runner import init_db
from .outcome_collector import ForwardOutcome, collect_outcomes_for_run


@dataclass
class QualityScore:
    """分析质量评分"""
    run_id: str
    ts_code: str = ""
    cutoff_date: str = ""

    # 5维度评分（0-100）
    valuation_direction: float = 0    # 估值方向
    recommendation_quality: float = 0  # 建议质量
    risk_identification: float = 0     # 风险识别
    safety_margin_quality: float = 0   # 安全边际
    dividend_accuracy: float = 0       # 分红预测

    # 加权总分
    overall_score: float = 0

    # 评分详情
    details: Dict[str, Any] = field(default_factory=dict)

    # 数据充分性
    scorable: bool = True
    score_notes: str = ""


# 维度权重
WEIGHTS = {
    'valuation_direction': 0.40,
    'recommendation_quality': 0.25,
    'risk_identification': 0.15,
    'safety_margin_quality': 0.10,
    'dividend_accuracy': 0.10,
}


def score_valuation_direction(
    synthesis: Dict[str, Any],
    outcome_detail: Dict[str, Any],
) -> tuple:
    """
    评估估值方向（40%权重）

    判断逻辑：
    - 分析说"低估"且后续上涨 → 高分
    - 分析说"观望"且后续横盘/小幅波动 → 中等分
    - 分析说"低估"但后续大跌 → 低分
    """
    score = 50  # 基准分
    details = {}

    recommendation = synthesis.get('recommendation', '')
    safety_margin = synthesis.get('safety_margin_pct', 0)

    return_6m = outcome_detail.get('return_6m')
    return_12m = outcome_detail.get('return_12m')

    # 使用可用的最长期收益率
    actual_return = return_12m if return_12m is not None else return_6m
    if actual_return is None:
        return 50, {"note": "无足够前向数据"}

    # 判断分析给出的方向（注意否定表达优先级）
    has_negation = any(neg in recommendation for neg in ['不买', '不建仓', '禁止', '不宜', '不建议'])
    is_bearish = has_negation or any(kw in recommendation for kw in ['卖出', '减仓', '回避', '等待回调'])
    is_bullish = (not is_bearish) and any(kw in recommendation for kw in ['买入', '加仓', '建仓', '试探'])
    is_neutral = (not is_bullish and not is_bearish) or any(kw in recommendation for kw in ['观望', '持有'])

    details['recommendation'] = recommendation
    details['actual_return'] = f"{actual_return*100:.1f}%"
    details['direction'] = 'bearish' if is_bearish else ('bullish' if is_bullish else 'neutral')

    if is_bullish:
        if actual_return > 0.20:
            score = 95  # 大涨，完全正确
        elif actual_return > 0.10:
            score = 85
        elif actual_return > 0:
            score = 70  # 方向正确但涨幅一般
        elif actual_return > -0.10:
            score = 40  # 小亏，方向有误但可接受
        elif actual_return > -0.20:
            score = 20  # 中等亏损
        else:
            score = 5   # 大亏，严重误判
    elif is_bearish:
        if actual_return < -0.10:
            score = 90  # 正确回避了下跌
        elif actual_return < 0:
            score = 75
        elif actual_return < 0.10:
            score = 50  # 回避了但其实涨了一点
        else:
            score = 20  # 错过了上涨
    elif is_neutral:
        if abs(actual_return) < 0.10:
            score = 75  # 横盘，观望合理
        elif actual_return > 0.20:
            score = 30  # 大涨但只给了观望
        elif actual_return < -0.20:
            score = 30  # 大跌但只给了观望（应该更积极回避）
        else:
            score = 55

    # 安全边际加分/扣分
    if safety_margin and safety_margin > 30 and actual_return > 0:
        score = min(100, score + 5)  # 高安全边际且盈利，加分
        details['safety_margin_bonus'] = True

    return score, details


def score_recommendation_quality(
    synthesis: Dict[str, Any],
    outcome_detail: Dict[str, Any],
) -> tuple:
    """
    评估建议质量（25%权重）

    基于实际收益和总回报（含分红）
    """
    score = 50
    details = {}

    return_6m = outcome_detail.get('return_6m')
    dividends = outcome_detail.get('actual_dividends', 0)
    cutoff_price = outcome_detail.get('cutoff_price', 0)

    if return_6m is None:
        return 50, {"note": "数据不足"}

    # 含分红总回报
    total_return = return_6m
    if cutoff_price > 0 and dividends > 0:
        total_return += dividends / cutoff_price

    recommendation = synthesis.get('recommendation', '')
    is_buy = any(kw in recommendation for kw in ['买入', '加仓', '建仓'])

    details['total_return_6m'] = f"{total_return*100:.1f}%"

    if is_buy:
        # 建议买入：收益越高分越高
        if total_return > 0.30:
            score = 100
        elif total_return > 0.15:
            score = 85
        elif total_return > 0.05:
            score = 70
        elif total_return > -0.05:
            score = 50
        elif total_return > -0.15:
            score = 25
        else:
            score = 5
    else:
        # 非买入建议：不亏就好
        if total_return > 0.20:
            score = 30  # 错过了大涨
        elif total_return > 0:
            score = 60
        elif total_return > -0.10:
            score = 75  # 正确没买，避免了小亏
        else:
            score = 90  # 正确没买，避免了大亏

    return score, details


def score_risk_identification(
    synthesis: Dict[str, Any],
    outcome_detail: Dict[str, Any],
) -> tuple:
    """
    评估风险识别（15%权重）

    基于最大回撤评估风险预警质量
    """
    score = 50
    details = {}

    max_dd = outcome_detail.get('max_drawdown_6m')
    if max_dd is None:
        return 50, {"note": "无回撤数据"}

    details['max_drawdown_6m'] = f"{max_dd*100:.1f}%"

    # 大回撤时，看分析是否有充分风险提示
    recommendation = synthesis.get('recommendation', '')
    overall_score = synthesis.get('overall_score', 50)

    if max_dd > 0.30:
        # 大幅回撤
        if any(kw in recommendation for kw in ['回避', '卖出', '减仓']):
            score = 85  # 给出了回避建议
        elif '观望' in recommendation:
            score = 55  # 至少没说买
        else:
            score = 15  # 说买但大跌了
        details['severity'] = '大幅回撤(>30%)'
    elif max_dd > 0.15:
        if any(kw in recommendation for kw in ['回避', '卖出']):
            score = 75
        elif overall_score < 60:
            score = 70  # 评分低，间接暗示了风险
        else:
            score = 40
        details['severity'] = '中等回撤(15-30%)'
    elif max_dd > 0.05:
        score = 70  # 正常波动
        details['severity'] = '正常波动(5-15%)'
    else:
        score = 80  # 几乎没回撤
        details['severity'] = '极低波动(<5%)'

    return score, details


def score_safety_margin(
    synthesis: Dict[str, Any],
    outcome_detail: Dict[str, Any],
) -> tuple:
    """
    评估安全边际有效性（10%权重）

    安全边际应保护下行风险
    """
    score = 50
    details = {}

    safety_margin = synthesis.get('safety_margin_pct', 0)
    max_dd = outcome_detail.get('max_drawdown_6m')

    if max_dd is None:
        return 50, {"note": "数据不足"}

    details['claimed_safety_margin'] = f"{safety_margin:.1f}%"
    details['actual_max_drawdown'] = f"{max_dd*100:.1f}%"

    if safety_margin > 30:
        # 声称高安全边际
        if max_dd < 0.15:
            score = 90  # 高安全边际 + 低回撤，验证了安全边际
        elif max_dd < 0.30:
            score = 50  # 高安全边际但中等回撤
        else:
            score = 15  # 高安全边际但大幅回撤，安全边际失效
    elif safety_margin > 15:
        if max_dd < 0.20:
            score = 70
        else:
            score = 30
    else:
        # 低安全边际
        if max_dd < 0.10:
            score = 60  # 低安全边际但碰巧没跌
        else:
            score = 40  # 低安全边际且跌了

    return score, details


def score_dividend_accuracy(
    synthesis: Dict[str, Any],
    outcome_detail: Dict[str, Any],
) -> tuple:
    """
    评估分红预测准确性（10%权重）
    """
    score = 50
    details = {}

    stream = synthesis.get('stream', '')
    actual_div = outcome_detail.get('actual_dividends', 0)
    cutoff_price = outcome_detail.get('cutoff_price', 0)

    if cutoff_price <= 0:
        return 50, {"note": "无价格数据"}

    actual_yield = actual_div / cutoff_price if actual_div > 0 else 0
    details['actual_yield'] = f"{actual_yield*100:.2f}%"

    is_dividend_focused = '收息' in stream or '分红' in stream

    if is_dividend_focused:
        # 以分红为核心的流派，分红预测准确性更重要
        if actual_yield > 0.05:
            score = 95  # 实际分红丰厚
        elif actual_yield > 0.03:
            score = 80
        elif actual_yield > 0.01:
            score = 55
        elif actual_yield > 0:
            score = 35  # 有分红但很少
        else:
            score = 10  # 没分红，严重误判
    else:
        # 非分红流派，分红预测权重低
        if actual_yield > 0:
            score = 70  # 有分红就行
        else:
            score = 50  # 没分红也不扣太多分

    return score, details


def calculate_quality_score(
    run_id: str,
    force_recollect: bool = False,
) -> Optional[QualityScore]:
    """
    计算分析质量评分

    Args:
        run_id: 分析运行ID
        force_recollect: 强制重新采集实际结果
    """
    init_db()
    conn = sqlite3.connect(str(ANALYSIS_DB_PATH))
    conn.row_factory = sqlite3.Row

    # 获取分析信息
    run = conn.execute(
        "SELECT * FROM analysis_runs WHERE id=?", (run_id,)
    ).fetchone()
    if not run:
        print(f"找不到分析任务: {run_id}")
        conn.close()
        return None

    # 获取综合研判
    synthesis_row = conn.execute(
        "SELECT * FROM synthesis WHERE run_id=?", (run_id,)
    ).fetchone()
    if not synthesis_row:
        print(f"找不到综合研判结果: {run_id}")
        conn.close()
        return None

    synthesis = dict(synthesis_row)

    # 获取或采集实际结果
    outcome_row = conn.execute(
        "SELECT * FROM backtest_outcomes WHERE run_id=?", (run_id,)
    ).fetchone()
    conn.close()

    if outcome_row and not force_recollect:
        outcome_detail = json.loads(outcome_row['quality_detail']) if outcome_row['quality_detail'] else {}
    else:
        outcome = collect_outcomes_for_run(run_id)
        if not outcome:
            return None
        outcome_detail = json.loads(
            _outcome_detail_from_outcome(outcome)
        )

    # 检查数据充分性
    months = outcome_detail.get('data_available_months', 0)
    if months < 3:
        qs = QualityScore(
            run_id=run_id,
            ts_code=run['ts_code'],
            cutoff_date=run['cutoff_date'],
            scorable=False,
            score_notes=f"数据不足: 仅有{months}个月前向数据，需至少3个月",
        )
        return qs

    # 5维度评分
    v_score, v_detail = score_valuation_direction(synthesis, outcome_detail)
    r_score, r_detail = score_recommendation_quality(synthesis, outcome_detail)
    ri_score, ri_detail = score_risk_identification(synthesis, outcome_detail)
    sm_score, sm_detail = score_safety_margin(synthesis, outcome_detail)
    d_score, d_detail = score_dividend_accuracy(synthesis, outcome_detail)

    # 加权总分
    overall = (
        v_score * WEIGHTS['valuation_direction'] +
        r_score * WEIGHTS['recommendation_quality'] +
        ri_score * WEIGHTS['risk_identification'] +
        sm_score * WEIGHTS['safety_margin_quality'] +
        d_score * WEIGHTS['dividend_accuracy']
    )

    qs = QualityScore(
        run_id=run_id,
        ts_code=run['ts_code'],
        cutoff_date=run['cutoff_date'],
        valuation_direction=v_score,
        recommendation_quality=r_score,
        risk_identification=ri_score,
        safety_margin_quality=sm_score,
        dividend_accuracy=d_score,
        overall_score=overall,
        details={
            'valuation_direction': v_detail,
            'recommendation_quality': r_detail,
            'risk_identification': ri_detail,
            'safety_margin_quality': sm_detail,
            'dividend_accuracy': d_detail,
            'outcome': outcome_detail,
        },
    )

    # 保存评分到数据库
    _save_quality_score(run_id, qs)

    return qs


def _outcome_detail_from_outcome(outcome: ForwardOutcome) -> str:
    """从ForwardOutcome构造detail JSON"""
    import json
    return json.dumps({
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
    }, ensure_ascii=False)


def _save_quality_score(run_id: str, qs: QualityScore):
    """保存质量评分到数据库"""
    conn = sqlite3.connect(str(ANALYSIS_DB_PATH))
    conn.execute(
        "UPDATE backtest_outcomes SET quality_score=?, quality_detail=? WHERE run_id=?",
        (qs.overall_score, json.dumps(qs.details, ensure_ascii=False), run_id)
    )
    conn.commit()
    conn.close()


def format_quality_score(qs: QualityScore) -> str:
    """格式化质量评分为可读文本"""
    if not qs.scorable:
        return f"## 质量评分: {qs.ts_code} @ {qs.cutoff_date}\n\n⚠️ {qs.score_notes}"

    lines = [
        f"## 分析质量评分: {qs.ts_code} @ {qs.cutoff_date}",
        "",
        f"**综合评分: {qs.overall_score:.1f}/100**",
        "",
        "| 维度 | 权重 | 得分 | 等级 |",
        "|------|------|------|------|",
    ]

    dims = [
        ("估值方向", 'valuation_direction', WEIGHTS['valuation_direction']),
        ("建议质量", 'recommendation_quality', WEIGHTS['recommendation_quality']),
        ("风险识别", 'risk_identification', WEIGHTS['risk_identification']),
        ("安全边际", 'safety_margin_quality', WEIGHTS['safety_margin_quality']),
        ("分红预测", 'dividend_accuracy', WEIGHTS['dividend_accuracy']),
    ]

    for label, attr, weight in dims:
        score = getattr(qs, attr)
        grade = _score_to_grade(score)
        lines.append(f"| {label} | {weight*100:.0f}% | {score:.0f} | {grade} |")

    # 详情
    lines.extend(["", "### 评分详情", ""])
    for label, attr, _ in dims:
        detail = qs.details.get(attr, {})
        if detail:
            lines.append(f"**{label}**: {json.dumps(detail, ensure_ascii=False)}")
            lines.append("")

    return '\n'.join(lines)


def _score_to_grade(score: float) -> str:
    if score >= 90:
        return "A+"
    elif score >= 80:
        return "A"
    elif score >= 70:
        return "B+"
    elif score >= 60:
        return "B"
    elif score >= 50:
        return "C"
    elif score >= 40:
        return "D"
    else:
        return "F"


# ==================== CLI ====================

def main():
    import sys
    if len(sys.argv) < 2:
        print("用法: python -m src.backtest.quality_scorer <run_id>")
        print("示例: python -m src.backtest.quality_scorer 601288.SH_2024-06-30_abc12345")
        sys.exit(1)

    run_id = sys.argv[1]
    qs = calculate_quality_score(run_id)
    if qs:
        print(format_quality_score(qs))


if __name__ == '__main__':
    main()
