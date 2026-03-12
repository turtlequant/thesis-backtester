"""
Prompt 组装器

将框架章节 + 时间过滤数据快照 + 前置章节输出组装为完整的分析prompt。
支持通过 StrategyConfig 配置不同的分析框架。

用法:
    python -m src.analyzer.prompt_builder 601288.SH 2024-06-30 all
    python -m src.analyzer.prompt_builder 601288.SH 2024-06-30 all --blind
    python -m src.analyzer.prompt_builder 601288.SH 2024-06-30 all --strategy strategies/v556_value/strategy.yaml
"""
import json
import logging
from dataclasses import asdict, fields
from pathlib import Path
from typing import List, Optional, Dict, Any, TYPE_CHECKING

logger = logging.getLogger(__name__)

from src.data.snapshot import create_snapshot, snapshot_to_markdown, StockSnapshot

from .framework_parser import load_chunk, load_all_chunks, FrameworkChunk, CHAPTER_DEFS
from . import output_schema as schemas

if TYPE_CHECKING:
    from src.engine.config import StrategyConfig


# ==================== 默认值（向后兼容） ====================

_DEFAULT_SCHEMA_MAP = {
    "ch01_data_verify": schemas.Ch01Output,
    "ch02_soe_stream": schemas.Ch02Output,
    "ch03_debt_cycle": schemas.Ch03Output,
    "ch04_cash_trend": schemas.Ch04Output,
    "ch05_stress_test": schemas.Ch05Output,
    "ch06_valuation": schemas.Ch06Output,
    "ch07_decision": schemas.Ch07Output,
    "ch08_cigar_butt": schemas.Ch08Output,
    "ch09_repair": schemas.Ch09Output,
    "ch10_light_asset": schemas.Ch10Output,
}

_DEFAULT_SYNTHESIS_FIELDS = [
    "流派判定: 纯硬收息 / 价值发现 / 烟蒂股 / 关联方资源",
    "龟级评定: 金龟 / 银龟 / 铜龟 / 不达标",
    "核心估值指标: EV/FCF倍数、安全边际",
    "苹果买卖模型: 正常价 / 买入价 / 卖出价",
    "一句话买入逻辑（强制）: 可证伪的投资命题",
    "关键风险: Top 3-5 风险点",
    "管理人诚信评估: 可信 / 存疑 / 不可信",
    "最终建议: 买入 / 观望 / 回避",
    "综合评分: 0-100分",
    "信心水平: 高 / 中 / 低",
]

_DEFAULT_VERSION_STRING = "个股分析标准模版 V5.5.6"
_DEFAULT_ANALYST_ROLE = "严谨的价值投资分析师"


def _get_schema_map(config: Optional["StrategyConfig"] = None) -> dict:
    if config is not None:
        schema_map = config.get_schema_map()
        if schema_map:
            return schema_map
    return _DEFAULT_SCHEMA_MAP


def _get_version_string(config: Optional["StrategyConfig"] = None) -> str:
    if config is not None:
        return config.get_version_string()
    return _DEFAULT_VERSION_STRING


def _get_analyst_role(config: Optional["StrategyConfig"] = None) -> str:
    if config is not None:
        return config.get_analyst_role()
    return _DEFAULT_ANALYST_ROLE


def _get_synthesis_fields(config: Optional["StrategyConfig"] = None) -> List[str]:
    if config is not None:
        fields_list = config.get_synthesis_fields()
        if fields_list:
            return fields_list
    return _DEFAULT_SYNTHESIS_FIELDS


def _get_chapter_defs(config: Optional["StrategyConfig"] = None) -> List[dict]:
    if config is not None:
        defs = config.get_chapter_defs()
        if defs:
            return defs
    return CHAPTER_DEFS


def build_chapter_prompt(
    chunk: FrameworkChunk,
    snapshot: StockSnapshot,
    prior_outputs: Dict[str, Any] = None,
    blind_mode: bool = False,
    config: Optional["StrategyConfig"] = None,
) -> str:
    """
    组装单章分析prompt

    Args:
        chunk: 框架章节
        snapshot: 数据快照
        prior_outputs: 前置章节的输出结果 {chunk_id: output_dict}
        blind_mode: 盲测模式，隐藏公司身份
        config: 策略配置（可选）
    """
    if prior_outputs is None:
        prior_outputs = {}

    sections = []
    sections.append(_build_system_instruction(chunk, snapshot, blind_mode, config=config))
    sections.append(_build_data_context(chunk, snapshot, blind_mode))

    if chunk.dependencies:
        sections.append(_build_prior_context(chunk, prior_outputs, config=config))

    sections.append(_build_framework_section(chunk, config=config))
    sections.append(_build_output_requirement(chunk, config=config))

    return "\n\n".join(sections)


def _build_system_instruction(
    chunk: FrameworkChunk,
    snapshot: StockSnapshot,
    blind_mode: bool = False,
    config: Optional["StrategyConfig"] = None,
) -> str:
    """系统指令：角色定义 + 时间边界"""
    version_string = _get_version_string(config)
    analyst_role = _get_analyst_role(config)

    if blind_mode:
        company_desc = "一家**匿名公司**（代码和名称已隐藏）"
        blind_notice = """
- **盲测模式**: 公司名称和代码已被隐藏，你不知道分析的是哪家公司
- 禁止猜测公司身份，仅基于提供的财务数据和指标进行分析
- 不得使用训练数据中对任何特定公司的既有认知"""
    else:
        company_desc = f"**{snapshot.stock_name}（{snapshot.ts_code}）**"
        blind_notice = "- 不得使用你的训练数据中关于该日期之后事件的知识"

    return f"""# 分析任务

你是一位{analyst_role}，正在使用「{version_string}」框架，
对 {company_desc} 进行深度分析。

## 严格时间边界

**截止日期: {snapshot.cutoff_date}**

- 你正在分析 {snapshot.cutoff_date} 时间点下的投资价值
- 禁止使用任何该日期之后的信息
- 提供的数据是完整的——未出现的信息代表在该时间点不可获取
{blind_notice}

## 当前任务

**第{chunk.chapter}章: {chunk.title}**

分析焦点: {chunk.focus}"""


def _build_data_context(chunk: FrameworkChunk, snapshot: StockSnapshot, blind_mode: bool = False) -> str:
    """根据章节需要的数据类型，提取相关数据"""
    sections = ["# 数据上下文\n"]

    data_needed = chunk.data_needed

    if blind_mode:
        sections.append("**股票**: 匿名标的（代码已隐藏）")
    else:
        sections.append(f"**股票**: {snapshot.stock_name}（{snapshot.ts_code}）")
    sections.append(f"**截止日期**: {snapshot.cutoff_date}")
    sections.append(f"**最新可用报告期**: {snapshot.latest_report_period}")
    sections.append("")

    if "price_summary" in data_needed or "daily_indicators" in data_needed:
        if not snapshot.price_history.empty:
            ph = snapshot.price_history
            latest = ph.iloc[-1]
            high_52w = ph.tail(250)['high'].max() if len(ph) >= 250 else ph['high'].max()
            low_52w = ph.tail(250)['low'].min() if len(ph) >= 250 else ph['low'].min()
            close = latest.get('close', 0)
            position = (close - low_52w) / (high_52w - low_52w) * 100 if high_52w > low_52w else 50

            sections.append("## 行情概览")
            sections.append(f"- 最新收盘价: {close}")
            sections.append(f"- 52周高点: {high_52w:.2f}, 低点: {low_52w:.2f}")
            sections.append(f"- 价格位置: {position:.1f}%")
            sections.append("")

        if not snapshot.daily_indicators.empty:
            di = snapshot.daily_indicators.iloc[-1]
            sections.append("## 估值指标")
            for col, label in [
                ('pe_ttm', 'PE(TTM)'), ('pb', 'PB'), ('dv_ratio', '股息率(%)'),
                ('dv_ttm', '股息率TTM(%)'), ('total_mv', '总市值(万元)'),
            ]:
                val = di.get(col)
                if val is not None and str(val) != 'nan':
                    if col == 'total_mv':
                        sections.append(f"- {label}: {float(val)/10000:.2f}亿")
                    else:
                        sections.append(f"- {label}: {float(val):.2f}")
            sections.append("")

    if "basic_info" in data_needed and not blind_mode:
        try:
            from src.data.api import get_stock_list
            sl = get_stock_list(only_active=False)
            match = sl[sl['ts_code'] == snapshot.ts_code]
            if not match.empty:
                row = match.iloc[0]
                sections.append("## 基本信息")
                sections.append(f"- 行业: {row.get('industry', 'N/A')}")
                sections.append(f"- 地区: {row.get('area', 'N/A')}")
                sections.append(f"- 上市日期: {row.get('list_date', 'N/A')}")
                sections.append("")
        except Exception as e:
            logger.debug(f"加载基本信息失败: {e}")

    if "balancesheet" in data_needed and not snapshot.balancesheet.empty:
        sections.append("## 资产负债表")
        sections.append(_df_to_markdown_vertical(
            snapshot.balancesheet,
            key_cols=['total_assets', 'total_liab', 'total_hldr_eqy_exc_min_int',
                      'money_cap', 'accounts_receiv', 'inventories', 'fix_assets',
                      'lt_borr', 'st_borr', 'bond_payable', 'notes_payable',
                      'accounts_payable', 'contract_liab'],
            n_periods=4,
        ))

    if "income" in data_needed and not snapshot.income.empty:
        sections.append("## 利润表")
        sections.append(_df_to_markdown_vertical(
            snapshot.income,
            key_cols=['revenue', 'oper_cost', 'operate_profit', 'n_income',
                      'n_income_attr_p', 'basic_eps', 'finance_exp',
                      'sell_exp', 'admin_exp', 'rd_exp',
                      'impair_ttl_am', 'non_oper_income', 'non_oper_exp'],
            n_periods=4,
        ))

    if "cashflow" in data_needed and not snapshot.cashflow.empty:
        sections.append("## 现金流量表")
        sections.append(_df_to_markdown_vertical(
            snapshot.cashflow,
            key_cols=['n_cashflow_act', 'n_cashflow_inv_act', 'n_cash_flows_fnc_act',
                      'c_pay_acq_const_fixa', 'c_paid_invest',
                      'c_recp_borrow', 'c_pay_dist_dpcp_int_exp'],
            n_periods=4,
        ))

    if "fina_indicator" in data_needed and not snapshot.fina_indicator.empty:
        sections.append("## 财务指标")
        sections.append(_df_to_markdown_vertical(
            snapshot.fina_indicator,
            key_cols=['roe', 'roe_dt', 'grossprofit_margin', 'netprofit_margin',
                      'debt_to_assets', 'current_ratio', 'quick_ratio',
                      'ocfps', 'bps', 'eps'],
            n_periods=4,
        ))

    if "dividend" in data_needed and not snapshot.dividend.empty:
        sections.append("## 分红历史")
        div = snapshot.dividend.tail(10)
        lines = ["| 年度 | 每股派息(元) | 公告日 |"]
        lines.append("|------|-------------|--------|")
        for _, row in div.iterrows():
            cash_div = row.get('cash_div', 0)
            if cash_div is not None and str(cash_div) != 'nan' and float(cash_div) > 0:
                lines.append(f"| {str(row.get('end_date', 'N/A'))[:4]} | {float(cash_div):.4f} | {row.get('ann_date', 'N/A')} |")
        sections.append('\n'.join(lines))
        sections.append("")

    if "top10_holders" in data_needed and not snapshot.top10_holders.empty:
        latest_period = snapshot.top10_holders['end_date'].max()
        holders = snapshot.top10_holders[snapshot.top10_holders['end_date'] == latest_period]
        sections.append(f"## 前十大股东（{latest_period}）")
        if blind_mode:
            from src.data.snapshot import _classify_holder
            lines = ["| 股东属性 | 持股比例(%) |"]
            lines.append("|---------|------------|")
            for _, row in holders.head(10).iterrows():
                name = row.get('holder_name', '')
                ratio = row.get('hold_ratio', 0)
                attr = _classify_holder(name)
                lines.append(f"| {attr} | {float(ratio):.2f} |")
        else:
            lines = ["| 股东名称 | 持股比例(%) |"]
            lines.append("|---------|------------|")
            for _, row in holders.head(10).iterrows():
                name = row.get('holder_name', 'N/A')
                ratio = row.get('hold_ratio', 0)
                lines.append(f"| {name} | {float(ratio):.2f} |")
        sections.append('\n'.join(lines))
        sections.append("")

    return "\n".join(sections)


def _build_prior_context(
    chunk: FrameworkChunk,
    prior_outputs: Dict[str, Any],
    config: Optional["StrategyConfig"] = None,
) -> str:
    """构建前置章节输出上下文"""
    chapter_defs = _get_chapter_defs(config)
    lines = ["# 前置分析结果\n"]

    for dep_id in chunk.dependencies:
        if dep_id in prior_outputs:
            output = prior_outputs[dep_id]
            dep_def = next((d for d in chapter_defs if d["id"] == dep_id), None)
            dep_title = dep_def["title"] if dep_def else dep_id

            lines.append(f"## {dep_title}（已完成）\n")

            if isinstance(output, dict):
                for key, val in output.items():
                    if val and str(val) not in ('', '0', '0.0', 'False', '[]'):
                        lines.append(f"- **{key}**: {val}")
            else:
                lines.append(str(output))

            lines.append("")
        else:
            lines.append(f"（{dep_id} 尚未完成）\n")

    return "\n".join(lines)


def _build_framework_section(
    chunk: FrameworkChunk,
    config: Optional["StrategyConfig"] = None,
) -> str:
    """框架章节内容"""
    version_string = _get_version_string(config)
    return f"""# 分析框架

以下是「{version_string}」第{chunk.chapter}章的完整内容。
请严格按照此框架进行分析。

---

{chunk.content}

---"""


def _build_output_requirement(
    chunk: FrameworkChunk,
    config: Optional["StrategyConfig"] = None,
) -> str:
    """输出格式要求"""
    schema_map = _get_schema_map(config)
    schema_cls = schema_map.get(chunk.id)
    if not schema_cls:
        return "请输出你的分析结论。"

    field_lines = []
    for f in fields(schema_cls):
        field_lines.append(f"- **{f.name}**: ({f.type.__name__ if hasattr(f.type, '__name__') else str(f.type)})")

    return f"""# 输出要求

请按以下结构输出你的分析结果。先给出详细的分析推理过程，然后在末尾用 JSON 格式输出结构化结论。

## 分析推理

请详细阐述你的分析过程，引用具体数据支撑每个判断。

## 结构化输出

在分析结束后，请输出如下 JSON（用 ```json 包裹）：

字段说明：
{chr(10).join(field_lines)}

注意：
- 金额单位统一为"亿元"
- 百分比用数值表示（如 7.06 表示 7.06%）
- 字符串字段请用中文填写
- 列表字段用中文描述"""


def _df_to_markdown_vertical(
    df, key_cols: list, n_periods: int = 4
) -> str:
    """将DataFrame转为竖向Markdown表格（报告期为列）"""
    if df.empty:
        return "（无数据）\n"

    df = df.copy()
    if 'end_date' in df.columns:
        df = df.drop_duplicates(subset=['end_date'], keep='last')
        df = df.sort_values('end_date', ascending=False).head(n_periods)
        df = df.sort_values('end_date')

    periods = df['end_date'].tolist() if 'end_date' in df.columns else []
    if not periods:
        return "（无数据）\n"

    lines = []
    header = "| 指标 | " + " | ".join(str(p) for p in periods) + " |"
    sep = "|------|" + "|".join(["------"] * len(periods)) + "|"
    lines.append(header)
    lines.append(sep)

    for col in key_cols:
        if col not in df.columns:
            continue
        row_vals = []
        for _, row in df.iterrows():
            val = row.get(col)
            if val is None or str(val) == 'nan':
                row_vals.append("N/A")
            elif isinstance(val, (int, float)) and abs(float(val)) >= 1e8:
                row_vals.append(f"{float(val)/1e8:.2f}亿")
            elif isinstance(val, (int, float)) and abs(float(val)) >= 1e4:
                row_vals.append(f"{float(val)/1e4:.2f}万")
            elif isinstance(val, float):
                row_vals.append(f"{val:.2f}")
            else:
                row_vals.append(str(val))
        lines.append(f"| {col} | " + " | ".join(row_vals) + " |")

    lines.append("")
    return "\n".join(lines)


def build_full_analysis_prompt(
    ts_code: str,
    cutoff_date: str,
    snapshot: StockSnapshot = None,
    blind_mode: bool = False,
    config: Optional["StrategyConfig"] = None,
) -> str:
    """
    构建完整的分析prompt（一次性给出所有框架）

    Args:
        ts_code: 股票代码
        cutoff_date: 截止日期
        snapshot: 数据快照（可选，不提供则自动生成）
        blind_mode: 盲测模式，隐藏公司名称和可识别信息
        config: 策略配置（可选）
    """
    if snapshot is None:
        snapshot = create_snapshot(ts_code, cutoff_date)

    chunks = load_all_chunks(config=config)
    if not chunks:
        raise RuntimeError("未找到框架章节，请先运行 framework_parser")

    version_string = _get_version_string(config)
    analyst_role = _get_analyst_role(config)
    synthesis_fields = _get_synthesis_fields(config)

    sections = []

    if blind_mode:
        sections.append(f"""# 匿名标的投资分析

## 分析任务

你是一位{analyst_role}，使用「{version_string}」框架，
对一家**匿名公司**在 **{snapshot.cutoff_date}** 时间截面下进行完整的深度分析。

## 盲测模式

- 公司名称和股票代码已被隐藏，你不知道分析的是哪家公司
- **禁止猜测公司身份**，仅基于提供的财务数据和指标进行分析
- 不得使用训练数据中对任何特定公司的既有认知

## 严格时间边界: {snapshot.cutoff_date}

- 禁止使用该日期之后的任何信息
- 提供的数据是完整的——未出现的信息代表当时不可获取
""")
    else:
        sections.append(f"""# {snapshot.stock_name}（{snapshot.ts_code}）投资分析

## 分析任务

你是一位{analyst_role}，使用「{version_string}」框架，
对 {snapshot.stock_name}（{snapshot.ts_code}）在 **{snapshot.cutoff_date}** 时间截面下进行完整的深度分析。

## 严格时间边界: {snapshot.cutoff_date}

- 禁止使用该日期之后的任何信息
- 提供的数据是完整的——未出现的信息代表当时不可获取
""")

    sections.append(snapshot_to_markdown(snapshot, blind_mode=blind_mode))

    sections.append(f"\n# 分析框架（{len(chunks)}章顺序执行）\n")
    sections.append(f"请按以下{len(chunks)}章顺序逐章分析，每章给出结论后进入下一章。\n")

    for chunk in chunks:
        sections.append(f"\n{'='*60}")
        sections.append(f"## 第{chunk.chapter}章: {chunk.title}")
        sections.append(f"**焦点**: {chunk.focus}")
        if chunk.dependencies:
            sections.append(f"**依赖**: 基于第{'、'.join(d.replace('ch0','').replace('ch','').split('_')[0] for d in chunk.dependencies)}章结论")
        sections.append(f"{'='*60}\n")
        sections.append(chunk.content)

    synthesis_text = "\n".join(f"{i+1}. **{field}**" for i, field in enumerate(synthesis_fields))
    sections.append(f"""

{'='*60}
# 最终输出要求
{'='*60}

完成{len(chunks)}章分析后，请输出**综合研判报告**，包含：

{synthesis_text}
""")

    return "\n".join(sections)


# ==================== CLI ====================

def main():
    import sys
    if len(sys.argv) < 4:
        print("用法: python -m src.analyzer.prompt_builder <ts_code> <cutoff_date> <chapter_id|all> [--blind] [--strategy <yaml>]")
        print("示例: python -m src.analyzer.prompt_builder 601288.SH 2024-06-30 all")
        print("      python -m src.analyzer.prompt_builder 601288.SH 2024-06-30 all --blind")
        sys.exit(1)

    ts_code = sys.argv[1]
    cutoff_date = sys.argv[2]
    chapter_arg = sys.argv[3]
    blind_mode = '--blind' in sys.argv

    config = None
    if '--strategy' in sys.argv:
        idx = sys.argv.index('--strategy')
        if idx + 1 < len(sys.argv):
            from src.engine.config import StrategyConfig
            config = StrategyConfig.from_yaml(sys.argv[idx + 1])
            print(f"使用策略: {config.name}")

    print(f"生成数据快照: {ts_code} @ {cutoff_date}...")
    if blind_mode:
        print("盲测模式: 已启用")
    snapshot = create_snapshot(ts_code, cutoff_date)

    chapter_defs = _get_chapter_defs(config)

    if chapter_arg == 'all':
        prompt = build_full_analysis_prompt(ts_code, cutoff_date, snapshot, blind_mode=blind_mode, config=config)
    else:
        chunk_id = chapter_arg
        if not chunk_id.startswith('ch'):
            chunk_id = f"ch{chunk_id}"
        matched = None
        for cdef in chapter_defs:
            if cdef["id"].startswith(chunk_id):
                matched = cdef["id"]
                break
        if not matched:
            print(f"未找到章节: {chapter_arg}")
            sys.exit(1)

        chunk = load_chunk(matched, config=config)
        if not chunk:
            print(f"章节文件不存在，请先运行 framework_parser")
            sys.exit(1)

        prompt = build_chapter_prompt(chunk, snapshot, blind_mode=blind_mode, config=config)

    print(prompt)
    print(f"\n--- Prompt 总长度: {len(prompt)} 字符 ---")


if __name__ == '__main__':
    main()
