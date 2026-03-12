"""
每章结构化输出定义

Claude Code 直接执行分析，输出需要按这些结构填写，
以便存储、对比和后续章节引用。
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict


@dataclass
class Ch01Output:
    """第一章：数据核查与地缘政治排除"""
    # 地缘政治
    geo_risk_level: str = ""          # "极高/中等/低/极低"
    geo_risk_reason: str = ""
    geo_excluded: bool = False        # 是否一票否决

    # 快速初筛
    price_position_pct: float = 0     # 价格位置百分比 (0-100)
    has_interest_bearing_debt: bool = True
    debt_ratio_pct: float = 0         # 资产负债率
    cash_covers_debt: bool = False    # 现金能否覆盖有息负债
    consecutive_profit_years: int = 0  # 连续盈利年数

    # 数据置信度
    data_confidence: str = ""         # "高/中/低"
    data_warnings: List[str] = field(default_factory=list)

    # 初筛结论
    pass_screening: bool = False
    screening_notes: str = ""


@dataclass
class Ch02Output:
    """第二章：央国企筛选与流派识别"""
    # 国企判定
    is_soe: bool = False
    soe_type: str = ""                # "央企/地方国企/混合所有制/民营"
    soe_rating: int = 0               # 1-5星
    controlling_shareholder: str = ""

    # 流派分类
    investment_stream: str = ""       # "纯硬收息/价值发现/烟蒂股/关联方资源"
    stream_reasoning: str = ""
    stream_confidence: str = ""       # "高/中/低"

    # 穿透回报率初筛
    penetrating_return_pct: float = 0
    classification_notes: str = ""


@dataclass
class Ch03Output:
    """第三章：深度负债与周期分析"""
    # 负债结构
    interest_bearing_debt: float = 0   # 有息负债总额（亿）
    operating_liabilities: float = 0   # 经营性负债（亿）
    zero_interest_debt: bool = False   # 是否无有息负债
    debt_structure_assessment: str = "" # "健康/可接受/警惕/危险"

    # 周期判断
    is_cyclical: bool = False
    cycle_position: str = ""           # "顶部/下行/底部/上行/非周期"
    cycle_trough_signals: int = 0      # 周期底部信号数量（需>=3）

    # 管理人诚信
    management_integrity: str = ""     # "可信/存疑/不可信"
    integrity_red_flags: List[str] = field(default_factory=list)

    debt_notes: str = ""


@dataclass
class Ch04Output:
    """第四章：动态现金与周期拐点"""
    # 现金趋势
    cash_trend_5y: str = ""            # "持续增长/波动稳定/下降/急剧下降"
    latest_cash_balance: float = 0     # 最新现金余额（亿）
    cash_burn_rate: str = ""           # "正向积累/缓慢消耗/快速消耗"

    # 周期拐点
    cycle_inflection_detected: bool = False
    inflection_signals: List[str] = field(default_factory=list)

    # 非现金项目还原
    non_cash_adjustments: float = 0    # 非现金项目还原金额（亿）
    adjusted_profit: float = 0         # 还原后实际利润（亿）
    restoration_notes: str = ""

    cash_notes: str = ""


@dataclass
class Ch05Output:
    """第五章：极端情景测试"""
    # 压力测试结果
    revenue_after_3y_decline: float = 0    # 连续3年-10%后营收（亿）
    profit_after_stress: float = 0          # 压力下利润（亿）
    still_profitable: bool = False
    dividend_sustainable: bool = False      # 压力下分红是否可持续

    stress_test_result: str = ""            # "通过/勉强通过/不通过"
    stress_notes: str = ""


@dataclass
class Ch06Output:
    """第六章：估值与安全边际（核心章）"""
    # 估值方法选择
    valuation_method: str = ""         # "FCF/PE/混合"
    pe_trap_warning: bool = False      # PE陷阱警示
    pe_trap_reasons: List[str] = field(default_factory=list)

    # 所有者收益
    owner_earnings: float = 0          # 所有者收益（亿）
    owner_earnings_formula: str = ""   # 计算过程

    # FCF计算（V5.5.5规范）
    fcf: float = 0                     # 自由现金流（亿）
    fcf_calculation: str = ""          # 计算过程
    maintenance_capex: float = 0       # 维持性CAPEX（亿）

    # 剔除净现金FCF倍数（核心指标）
    net_cash: float = 0                # 净现金（亿）
    ev: float = 0                      # 企业价值 = 市值 - 净现金
    ev_fcf_multiple: float = 0         # EV/FCF倍数

    # 龟级评定
    turtle_rating: str = ""            # "金龟/银龟/铜龟/不达标"
    turtle_criteria: str = ""          # 达标依据

    # V2 债券视角
    v2_bond_price: float = 0           # V2估值（元/股）
    # V3 业主视角
    v3_normal_market_cap: float = 0    # V3正常市值（亿）
    v3_conservative_cap: float = 0     # V3保守市值（亿）
    # V3.5 FCEV
    v35_ev_fcf: float = 0              # V3.5 EV/FCF

    # 安全边际
    safety_margin_pct: float = 0       # 安全边际百分比
    market_condition: str = ""         # "牛市/熊市/震荡"

    # 综合估值区间
    fair_value_per_share: float = 0    # 合理估值（元/股）
    buy_point: float = 0              # 买入点（元/股）
    sell_point: float = 0             # 卖出点（元/股）

    valuation_notes: str = ""


@dataclass
class Ch07Output:
    """第七章：决策流程与持仓管理"""
    # 建议
    recommendation: str = ""           # "买入/加仓/持有/观望/减仓/卖出"
    position_type: str = ""            # "核心/卫星"
    suggested_position_pct: float = 0  # 建议仓位百分比

    # 试探建仓
    probe_entry_applicable: bool = False
    probe_entry_price: float = 0
    grid_levels: List[str] = field(default_factory=list)

    # 持仓状态标签
    position_label: str = ""           # "🟢正常持有/🔵回本/🟡高位/🟠观望/🔴历史遗留"

    # 退出纪律
    exit_conditions: List[str] = field(default_factory=list)

    decision_notes: str = ""


@dataclass
class Ch08Output:
    """第八章：高级烟蒂股分析框架"""
    # T级资产分层
    t0_cash: float = 0                 # T0 现金类（亿）
    t1_liquid: float = 0              # T1 流动金融资产（亿）
    t2_operating: float = 0           # T2 经营性资产（亿）
    t3_fixed: float = 0              # T3 固定资产（亿）
    asset_cushion_ratio: float = 0    # 资产垫比率

    # 债务偿还路径
    years_to_clear_debt: float = 0    # 清偿年限
    debt_clearance_feasible: bool = False

    # 三要义检查
    has_asset_cushion: bool = False
    has_low_maintenance_cost: bool = False
    has_clear_realization_path: bool = False

    cigar_butt_notes: str = ""


@dataclass
class Ch09Output:
    """第九章：估值修复框架"""
    # 苹果买卖模型
    apple_normal_price: str = ""       # 合理价（"1.5元"）
    apple_buy_price: str = ""          # 买入价（"0.3-0.4元"）
    apple_sell_price: str = ""         # 卖出价（"0.7-0.8元"）

    # 一句话买入逻辑（强制）
    buy_logic_statement: str = ""      # 核心投资论述

    # 修复目标
    repair_target: str = ""            # 修复目标（如 "PB 0.3→0.6"）
    repair_catalyst: str = ""          # 修复催化剂
    expected_repair_return_pct: float = 0  # 预期修复收益率

    repair_notes: str = ""


@dataclass
class Ch10Output:
    """第十章：特殊轻资产模式"""
    is_light_asset: bool = False
    business_model: str = ""           # 商业模式描述
    recurring_revenue_pct: float = 0   # 经常性收入占比
    capex_to_revenue_pct: float = 0    # CAPEX/营收比
    light_asset_notes: str = ""


@dataclass
class SynthesisOutput:
    """综合研判（所有章节汇总）"""
    ts_code: str = ""
    stock_name: str = ""
    cutoff_date: str = ""

    # 核心结论
    investment_stream: str = ""        # 流派
    turtle_rating: str = ""            # 龟级
    recommendation: str = ""           # 建议
    buy_logic_statement: str = ""      # 一句话买入逻辑

    # 关键指标
    ev_fcf_multiple: float = 0
    safety_margin_pct: float = 0
    fair_value: float = 0
    current_price: float = 0

    # 苹果模型
    apple_buy: str = ""
    apple_sell: str = ""

    # 风险
    key_risks: List[str] = field(default_factory=list)
    management_integrity: str = ""

    # 评分
    overall_score: float = 0           # 0-100
    confidence: str = ""               # "高/中/低"

    summary: str = ""                  # 综合评述
