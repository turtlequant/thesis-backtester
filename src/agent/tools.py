"""
Tool 沙箱 — Agent 能访问的全部数据接口

设计原则：
  - Agent 只能通过这些 tools 获取信息，无文件系统/网络/代码执行
  - 所有数据查询都经过时间边界过滤（cutoff_date）
  - 盲测模式下公司名称自动匿名化
  - Tool 定义使用 OpenAI function calling 格式
"""
import json
import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from src.data.snapshot import StockSnapshot, _classify_holder

logger = logging.getLogger(__name__)


# ==================== Tool 定义（OpenAI 格式）====================

TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "query_financial_data",
            "description": (
                "查询公司财务数据。所有数据已按截止日期过滤，"
                "仅包含该时间点可获得的已公开信息。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "data_type": {
                        "type": "string",
                        "enum": [
                            "price_summary",
                            "valuation",
                            "balance_sheet",
                            "income",
                            "cashflow",
                            "financial_indicators",
                            "dividends",
                            "holders",
                            "float_holders",
                            "audit_opinion",
                            "business_composition",
                            "pledge",
                            "holder_count",
                            "holder_trade",
                            "share_unlock",
                            "repurchase",
                        ],
                        "description": (
                            "数据类型: "
                            "price_summary=行情概览, valuation=估值指标, "
                            "balance_sheet=资产负债表, income=利润表, "
                            "cashflow=现金流量表, financial_indicators=财务指标, "
                            "dividends=分红历史, holders=前十大股东, "
                            "float_holders=前十大流通股东, "
                            "audit_opinion=审计意见, "
                            "business_composition=主营业务构成, "
                            "pledge=股权质押, "
                            "holder_count=股东人数变化, "
                            "holder_trade=股东增减持, "
                            "share_unlock=限售解禁, "
                            "repurchase=股票回购"
                        ),
                    },
                    "periods": {
                        "type": "integer",
                        "description": "返回最近N期数据（默认4期，最多8期）",
                        "default": 4,
                    },
                },
                "required": ["data_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_financial_batch",
            "description": (
                "批量查询多种财务数据，一次返回多个数据类型的结果。"
                "比多次调用 query_financial_data 更高效。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "data_types": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [
                                "price_summary", "valuation",
                                "balance_sheet", "income", "cashflow",
                                "financial_indicators", "dividends",
                                "holders", "float_holders",
                                "audit_opinion", "business_composition",
                                "pledge", "holder_count", "holder_trade",
                                "share_unlock", "repurchase",
                            ],
                        },
                        "description": "要查询的数据类型列表",
                    },
                    "periods": {
                        "type": "integer",
                        "description": "返回最近N期数据（默认4期，最多8期）",
                        "default": 4,
                    },
                },
                "required": ["data_types"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_analysis_context",
            "description": (
                "获取分析上下文信息，包括截止日期、行业分类、可用数据源列表、"
                "各数据类型的字段名称等元数据。"
            ),
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    # ---- 实时增强数据工具（live-analyze 时可用）----
    {
        "type": "function",
        "function": {
            "name": "query_market_context",
            "description": (
                "查询市场环境信息：最新新闻、主力资金流向、大盘走势、行业板块表现。"
                "仅在实时分析模式下可用，回测模式下返回空。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "info_type": {
                        "type": "string",
                        "enum": ["news", "fund_flow", "market_index", "industry_overview"],
                        "description": (
                            "信息类型: "
                            "news=个股最新新闻, "
                            "fund_flow=近期主力资金流向, "
                            "market_index=大盘走势(沪深300), "
                            "industry_overview=所属行业板块表现"
                        ),
                    },
                },
                "required": ["info_type"],
            },
        },
    },
]


def get_tool_definitions(blind_mode: bool = True) -> List[Dict[str, Any]]:
    """Expose real-time context only outside strict historical/blind runs."""
    if not blind_mode:
        return TOOL_DEFINITIONS
    return [
        item
        for item in TOOL_DEFINITIONS
        if item.get("function", {}).get("name") != "query_market_context"
    ]


# ==================== Tool 沙箱 ====================

class ToolSandbox:
    """
    Tool 执行沙箱

    持有一个 StockSnapshot，所有 tool 调用都从中提取数据。
    数据已在 snapshot 创建时按 cutoff_date 过滤。
    """

    def __init__(self, snapshot: StockSnapshot, blind_mode: bool = True):
        self.snapshot = snapshot
        self.blind_mode = blind_mode

    def execute(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """
        执行 tool 调用，返回字符串结果

        Args:
            tool_name: 工具名称
            arguments: 工具参数

        Returns:
            JSON 字符串格式的结果
        """
        try:
            if tool_name == "query_financial_data":
                return self._query_financial_data(**arguments)
            elif tool_name == "query_financial_batch":
                return self._query_financial_batch(**arguments)
            elif tool_name == "get_analysis_context":
                return self._get_analysis_context()
            elif tool_name == "query_market_context":
                if self.blind_mode:
                    return json.dumps(
                        {"error": "严格历史模式禁止查询实时市场上下文"},
                        ensure_ascii=False,
                    )
                return self._query_market_context(**arguments)
            else:
                return json.dumps({"error": f"未知工具: {tool_name}"}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Tool execution error: {tool_name} - {e}")
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def _get_analysis_context(self) -> str:
        """返回分析上下文元数据"""
        ctx = {
            "cutoff_date": self.snapshot.cutoff_date,
            "industry": self.snapshot.industry,
            "area": self.snapshot.area,
            "list_date": self.snapshot.list_date,
            "latest_report_period": self.snapshot.latest_report_period,
            "available_data": self.snapshot.data_sources,
            "warnings": self.snapshot.warnings,
            "blind_mode": self.blind_mode,
            "data_fields": {
                "balance_sheet": [
                    "total_assets", "total_liab", "total_hldr_eqy_exc_min_int",
                    "money_cap(货币资金)", "accounts_receiv", "inventories",
                    "fix_assets", "lt_borr(长期借款)", "st_borr(短期借款)",
                    "bond_payable(应付债券)", "notes_payable", "accounts_payable",
                    "contract_liab",
                ],
                "income": [
                    "revenue", "oper_cost", "operate_profit", "n_income",
                    "n_income_attr_p(归母净利润)", "basic_eps",
                    "finance_exp(财务费用)", "sell_exp", "admin_exp", "rd_exp",
                    "impair_ttl_am(资产减值)", "non_oper_income", "non_oper_exp",
                ],
                "cashflow": [
                    "n_cashflow_act(经营现金流)", "n_cashflow_inv_act(投资现金流)",
                    "n_cash_flows_fnc_act(筹资现金流)",
                    "c_pay_acq_const_fixa(购建固定资产CAPEX)",
                    "c_paid_invest", "c_recp_borrow",
                    "c_pay_dist_dpcp_int_exp(派息+偿息)",
                ],
                "financial_indicators": [
                    "roe", "roe_dt(扣非ROE)", "grossprofit_margin(毛利率)",
                    "netprofit_margin(净利率)", "debt_to_assets(负债率)",
                    "current_ratio", "quick_ratio", "ocfps(每股经营现金流)",
                    "bps(每股净资产)", "eps",
                ],
            },
        }
        if not self.blind_mode:
            ctx["stock_name"] = self.snapshot.stock_name
            ctx["ts_code"] = self.snapshot.ts_code
        return json.dumps(ctx, ensure_ascii=False, indent=2)

    def _query_financial_batch(self, data_types: List[str], periods: int = 4) -> str:
        """批量查询多种数据"""
        periods = min(max(periods, 1), 8)
        results = {}
        for dt in data_types:
            try:
                raw = self._query_financial_data(dt, periods)
                results[dt] = json.loads(raw)
            except Exception as e:
                results[dt] = {"error": str(e)}
        return json.dumps(results, ensure_ascii=False, indent=2)

    def _query_market_context(self, info_type: str) -> str:
        """查询市场环境信息（实时增强数据）"""
        snap = self.snapshot

        if info_type == "news":
            if snap.news.empty:
                return json.dumps({"info": "当前模式下无新闻数据"}, ensure_ascii=False)
            records = []
            for _, row in snap.news.iterrows():
                records.append({
                    "title": str(row.get("title", "")),
                    "content": str(row.get("content", ""))[:300],
                    "datetime": str(row.get("datetime", "")),
                    "source": str(row.get("source", "")),
                })
            return json.dumps({"news": records}, ensure_ascii=False, indent=2)

        elif info_type == "fund_flow":
            if snap.fund_flow.empty:
                return json.dumps({"info": "当前模式下无资金流数据"}, ensure_ascii=False)
            records = []
            for _, row in snap.fund_flow.tail(10).iterrows():
                record = {}
                for col in ["trade_date", "close", "pct_chg", "main_net_inflow",
                             "main_net_inflow_pct", "xl_net_inflow", "lg_net_inflow"]:
                    val = row.get(col)
                    if pd.notna(val):
                        record[col] = round(float(val), 4) if isinstance(val, float) else str(val)
                records.append(record)
            return json.dumps({"fund_flow": records}, ensure_ascii=False, indent=2)

        elif info_type == "market_index":
            if snap.index_daily.empty:
                return json.dumps({"info": "当前模式下无大盘数据"}, ensure_ascii=False)
            recent = snap.index_daily.tail(10)
            records = []
            for _, row in recent.iterrows():
                records.append({
                    "trade_date": str(row.get("trade_date", "")),
                    "close": round(float(row.get("close", 0)), 2),
                })
            # 计算近期涨跌
            summary = {}
            if len(snap.index_daily) >= 20:
                d20 = float(snap.index_daily.iloc[-20]["close"])
                d_now = float(snap.index_daily.iloc[-1]["close"])
                summary["change_20d_pct"] = round((d_now - d20) / d20 * 100, 2)
            if len(snap.index_daily) >= 5:
                d5 = float(snap.index_daily.iloc[-5]["close"])
                d_now = float(snap.index_daily.iloc[-1]["close"])
                summary["change_5d_pct"] = round((d_now - d5) / d5 * 100, 2)
            return json.dumps({"index": "沪深300", "recent": records, "summary": summary},
                              ensure_ascii=False, indent=2)

        elif info_type == "industry_overview":
            if snap.industry_summary.empty:
                return json.dumps({"info": "当前模式下无行业数据"}, ensure_ascii=False)
            # 找本股所属行业
            result = {"all_industries_count": len(snap.industry_summary)}
            if snap.industry:
                ind_name = snap.industry.replace('Ⅱ', '').replace('Ⅲ', '').strip()
                matched = snap.industry_summary[
                    snap.industry_summary['industry'].str.contains(ind_name, na=False)
                ]
                if not matched.empty:
                    row = matched.iloc[0]
                    result["current_industry"] = {
                        "name": str(row.get("industry", "")),
                        "pct_chg": str(row.get("pct_chg", "")),
                        "net_inflow": str(row.get("net_inflow", "")),
                        "up_count": str(row.get("up_count", "")),
                        "down_count": str(row.get("down_count", "")),
                    }
            # Top 5 涨幅行业
            top5 = snap.industry_summary.nlargest(5, 'pct_chg') if 'pct_chg' in snap.industry_summary.columns else pd.DataFrame()
            if not top5.empty:
                result["top5_industries"] = [
                    {"name": str(r.get("industry", "")), "pct_chg": str(r.get("pct_chg", ""))}
                    for _, r in top5.iterrows()
                ]
            return json.dumps(result, ensure_ascii=False, indent=2)

        return json.dumps({"error": f"未知信息类型: {info_type}"}, ensure_ascii=False)

    def _query_financial_data(self, data_type: str, periods: int = 4) -> str:
        """统一数据查询入口"""
        periods = min(max(periods, 1), 8)

        handlers = {
            "price_summary": self._get_price_summary,
            "valuation": self._get_valuation,
            "balance_sheet": self._get_balance_sheet,
            "income": self._get_income,
            "cashflow": self._get_cashflow,
            "financial_indicators": self._get_financial_indicators,
            "dividends": self._get_dividends,
            "holders": self._get_holders,
            "float_holders": self._get_float_holders,
            "audit_opinion": self._get_audit_opinion,
            "business_composition": self._get_business_composition,
            "pledge": self._get_pledge,
            "holder_count": self._get_holder_count,
            "holder_trade": self._get_holder_trade,
            "share_unlock": self._get_share_unlock,
            "repurchase": self._get_repurchase,
        }

        handler = handlers.get(data_type)
        if not handler:
            return json.dumps({"error": f"未知数据类型: {data_type}"}, ensure_ascii=False)

        return handler(periods)

    def _get_price_summary(self, periods: int) -> str:
        """行情概览"""
        ph = self.snapshot.price_history
        if ph.empty:
            return json.dumps({"error": "无行情数据"}, ensure_ascii=False)

        latest = ph.iloc[-1]
        close = float(latest.get("close", 0))
        high_52w = float(ph.tail(250)["high"].max() if len(ph) >= 250 else ph["high"].max())
        low_52w = float(ph.tail(250)["low"].min() if len(ph) >= 250 else ph["low"].min())
        position = (close - low_52w) / (high_52w - low_52w) * 100 if high_52w > low_52w else 50

        result = {
            "latest_close": close,
            "latest_date": str(latest.get("trade_date", "")),
            "high_52w": high_52w,
            "low_52w": low_52w,
            "price_position_pct": round(position, 1),
        }

        # 最近N个月月度收盘价
        monthly = ph.copy()
        monthly["trade_date"] = pd.to_datetime(monthly["trade_date"])
        monthly = monthly.set_index("trade_date").resample("ME").last()
        monthly = monthly.tail(periods * 3)  # 给更多月度数据
        if not monthly.empty:
            result["monthly_close"] = {
                str(idx.date()): round(float(row["close"]), 2)
                for idx, row in monthly.iterrows()
                if pd.notna(row.get("close"))
            }

        return json.dumps(result, ensure_ascii=False, indent=2)

    def _get_valuation(self, periods: int) -> str:
        """估值指标"""
        di = self.snapshot.daily_indicators
        if di.empty:
            return json.dumps({"error": "无估值数据"}, ensure_ascii=False)

        latest = di.iloc[-1]
        result = {}
        for col, label in [
            ("pe_ttm", "pe_ttm"),
            ("pb", "pb"),
            ("ps_ttm", "ps_ttm"),
            ("dv_ratio", "dividend_yield_pct"),
            ("dv_ttm", "dividend_yield_ttm_pct"),
            ("total_mv", "total_market_cap_wan"),
            ("circ_mv", "circulating_market_cap_wan"),
        ]:
            val = latest.get(col)
            if pd.notna(val):
                result[label] = round(float(val), 4)

        # 总市值转亿
        if "total_market_cap_wan" in result:
            result["total_market_cap_yi"] = round(result["total_market_cap_wan"] / 10000, 2)
        if "circulating_market_cap_wan" in result:
            result["circulating_market_cap_yi"] = round(result["circulating_market_cap_wan"] / 10000, 2)

        return json.dumps(result, ensure_ascii=False, indent=2)

    def _get_balance_sheet(self, periods: int) -> str:
        """资产负债表"""
        return self._format_financial_df(
            self.snapshot.balancesheet,
            key_cols=[
                "total_assets", "total_liab", "total_hldr_eqy_exc_min_int",
                "money_cap", "accounts_receiv", "inventories", "fix_assets",
                "lt_borr", "st_borr", "bond_payable", "notes_payable",
                "accounts_payable", "contract_liab",
            ],
            periods=periods,
            name="资产负债表",
        )

    def _get_income(self, periods: int) -> str:
        """利润表"""
        return self._format_financial_df(
            self.snapshot.income,
            key_cols=[
                "revenue", "oper_cost", "operate_profit", "n_income",
                "n_income_attr_p", "basic_eps", "finance_exp",
                "sell_exp", "admin_exp", "rd_exp",
                "impair_ttl_am", "non_oper_income", "non_oper_exp",
            ],
            periods=periods,
            name="利润表",
        )

    def _get_cashflow(self, periods: int) -> str:
        """现金流量表"""
        return self._format_financial_df(
            self.snapshot.cashflow,
            key_cols=[
                "n_cashflow_act", "n_cashflow_inv_act", "n_cash_flows_fnc_act",
                "c_pay_acq_const_fixa", "c_paid_invest",
                "c_recp_borrow", "c_pay_dist_dpcp_int_exp",
            ],
            periods=periods,
            name="现金流量表",
        )

    def _get_financial_indicators(self, periods: int) -> str:
        """财务指标"""
        return self._format_financial_df(
            self.snapshot.fina_indicator,
            key_cols=[
                "roe", "roe_dt", "grossprofit_margin", "netprofit_margin",
                "debt_to_assets", "current_ratio", "quick_ratio",
                "ocfps", "bps", "eps",
            ],
            periods=periods,
            name="财务指标",
        )

    def _get_dividends(self, periods: int) -> str:
        """分红历史"""
        div = self.snapshot.dividend
        if div.empty:
            return json.dumps({"error": "无分红数据"}, ensure_ascii=False)

        records = []
        for _, row in div.tail(periods * 2).iterrows():
            cash_div = row.get("cash_div", 0)
            if pd.notna(cash_div) and float(cash_div) > 0:
                records.append({
                    "year": str(row.get("end_date", ""))[:4],
                    "cash_dividend_per_share": round(float(cash_div), 4),
                    "announcement_date": str(row.get("ann_date", "")),
                    "ex_date": str(row.get("ex_date", "")),
                })

        return json.dumps({"dividends": records}, ensure_ascii=False, indent=2)

    def _get_holders(self, periods: int) -> str:
        """前十大股东（盲测模式自动匿名化）"""
        holders_df = self.snapshot.top10_holders
        if holders_df.empty:
            return json.dumps({"error": "无股东数据"}, ensure_ascii=False)

        latest_period = holders_df["end_date"].max()
        holders = holders_df[holders_df["end_date"] == latest_period]

        records = []
        for i, (_, row) in enumerate(holders.head(10).iterrows(), 1):
            name = row.get("holder_name", "")
            ratio = row.get("hold_ratio", 0)
            amount = row.get("hold_amount", 0)

            record = {
                "rank": i,
                "hold_ratio_pct": round(float(ratio), 2) if pd.notna(ratio) else 0,
                "hold_amount": int(float(amount)) if pd.notna(amount) else 0,
            }

            if self.blind_mode:
                record["holder_type"] = _classify_holder(name)
            else:
                record["holder_name"] = name

            records.append(record)

        return json.dumps(
            {"report_period": str(latest_period), "top10_holders": records},
            ensure_ascii=False,
            indent=2,
        )

    def _get_float_holders(self, periods: int) -> str:
        """前十大流通股东"""
        df = self.snapshot.top10_floatholders
        if df.empty:
            return json.dumps({"error": "无流通股东数据"}, ensure_ascii=False)

        latest_period = df["end_date"].max()
        holders = df[df["end_date"] == latest_period]

        records = []
        for i, (_, row) in enumerate(holders.head(10).iterrows(), 1):
            name = row.get("holder_name", "")
            record = {
                "rank": i,
                "hold_amount": int(float(row.get("hold_amount", 0))) if pd.notna(row.get("hold_amount")) else 0,
            }
            if self.blind_mode:
                record["holder_type"] = _classify_holder(name)
            else:
                record["holder_name"] = name
            records.append(record)

        return json.dumps(
            {"report_period": str(latest_period), "top10_float_holders": records},
            ensure_ascii=False, indent=2,
        )

    def _get_audit_opinion(self, periods: int) -> str:
        """审计意见"""
        df = self.snapshot.fina_audit
        if df.empty:
            return json.dumps({"error": "无审计意见数据"}, ensure_ascii=False)

        df = df.drop_duplicates(subset=["end_date"], keep="last")
        df = df.sort_values("end_date", ascending=False).head(periods)

        records = []
        for _, row in df.iterrows():
            record = {"end_date": str(row.get("end_date", ""))}
            for col in ["audit_result", "audit_agency", "audit_sign"]:
                val = row.get(col)
                if pd.notna(val):
                    record[col] = str(val)
            records.append(record)

        return json.dumps({"audit_opinions": records}, ensure_ascii=False, indent=2)

    def _get_business_composition(self, periods: int) -> str:
        """主营业务构成"""
        df = self.snapshot.fina_mainbz
        if df.empty:
            return json.dumps({"error": "无主营业务构成数据"}, ensure_ascii=False)

        # 取最近一期
        latest_period = df["end_date"].max()
        latest = df[df["end_date"] == latest_period].copy()

        records = []
        for _, row in latest.iterrows():
            record = {"item": str(row.get("bz_item", ""))}
            for col in ["bz_sales", "bz_profit", "bz_cost", "curr_type"]:
                val = row.get(col)
                if pd.notna(val):
                    record[col] = round(float(val), 2) if isinstance(val, (int, float)) else str(val)
            # 计算毛利率
            sales = row.get("bz_sales")
            cost = row.get("bz_cost")
            if pd.notna(sales) and pd.notna(cost) and float(sales) > 0:
                record["gross_margin_pct"] = round((1 - float(cost) / float(sales)) * 100, 2)
            records.append(record)

        return json.dumps(
            {"report_period": str(latest_period), "segments": records},
            ensure_ascii=False, indent=2,
        )

    def _get_pledge(self, periods: int) -> str:
        """股权质押统计"""
        df = self.snapshot.pledge_stat
        if df.empty:
            return json.dumps({"error": "无股权质押数据"}, ensure_ascii=False)

        df = df.sort_values("end_date", ascending=False).head(periods)

        records = []
        for _, row in df.iterrows():
            record = {"end_date": str(row.get("end_date", ""))}
            for col in ["pledge_count", "unrest_pledge", "rest_pledge",
                         "total_share", "pledge_ratio"]:
                val = row.get(col)
                if pd.notna(val):
                    record[col] = round(float(val), 4) if isinstance(val, float) else val
            records.append(record)

        return json.dumps({"pledge_stats": records}, ensure_ascii=False, indent=2)

    def _get_holder_count(self, periods: int) -> str:
        """股东人数变化"""
        df = self.snapshot.stk_holdernumber
        if df.empty:
            return json.dumps({"error": "无股东人数数据"}, ensure_ascii=False)

        df = df.drop_duplicates(subset=["end_date"], keep="last")
        df = df.sort_values("end_date", ascending=False).head(periods)

        records = []
        for _, row in df.iterrows():
            record = {"end_date": str(row.get("end_date", ""))}
            for col in ["holder_num", "holder_num_change", "holder_num_ratio"]:
                val = row.get(col)
                if pd.notna(val):
                    record[col] = round(float(val), 4) if isinstance(val, float) else int(val)
            records.append(record)

        return json.dumps({"holder_counts": records}, ensure_ascii=False, indent=2)

    def _get_holder_trade(self, periods: int) -> str:
        """股东增减持"""
        df = self.snapshot.stk_holdertrade
        if df.empty:
            return json.dumps({"error": "无股东增减持数据"}, ensure_ascii=False)

        df = df.sort_values("ann_date", ascending=False).head(periods * 3) if "ann_date" in df.columns else df.tail(periods * 3)

        records = []
        for _, row in df.iterrows():
            record = {}
            if self.blind_mode:
                holder_name = row.get("holder_name", "")
                record["holder_type"] = _classify_holder(holder_name)
            else:
                record["holder_name"] = str(row.get("holder_name", ""))

            for col in ["ann_date", "begin_date", "close_date", "in_de",
                         "change_vol", "change_ratio", "after_share", "after_ratio"]:
                val = row.get(col)
                if pd.notna(val):
                    if isinstance(val, float):
                        record[col] = round(val, 4)
                    else:
                        record[col] = str(val)
            records.append(record)

        return json.dumps({"holder_trades": records}, ensure_ascii=False, indent=2)

    def _get_share_unlock(self, periods: int) -> str:
        """限售解禁"""
        df = self.snapshot.share_float
        if df.empty:
            return json.dumps({"error": "无限售解禁数据"}, ensure_ascii=False)

        # 取最近和未来的解禁
        df = df.sort_values("float_date", ascending=False).head(periods * 3) if "float_date" in df.columns else df.tail(periods * 3)

        records = []
        for _, row in df.iterrows():
            record = {}
            for col in ["float_date", "float_share", "float_ratio"]:
                val = row.get(col)
                if pd.notna(val):
                    record[col] = round(float(val), 4) if isinstance(val, float) else str(val)

            holder_name = row.get("holder_name", "")
            if self.blind_mode:
                record["holder_type"] = _classify_holder(holder_name)
            else:
                record["holder_name"] = str(holder_name)

            records.append(record)

        return json.dumps({"share_unlocks": records}, ensure_ascii=False, indent=2)

    def _get_repurchase(self, periods: int) -> str:
        """股票回购"""
        df = self.snapshot.repurchase
        if df.empty:
            return json.dumps({"error": "无回购数据"}, ensure_ascii=False)

        df = df.sort_values("ann_date", ascending=False).head(periods * 2) if "ann_date" in df.columns else df.tail(periods * 2)

        records = []
        for _, row in df.iterrows():
            record = {}
            for col in ["ann_date", "exp_date", "vol", "amount",
                         "high_limit", "low_limit", "proc"]:
                val = row.get(col)
                if pd.notna(val):
                    if isinstance(val, float):
                        record[col] = round(val, 4)
                    else:
                        record[col] = str(val)
            records.append(record)

        return json.dumps({"repurchases": records}, ensure_ascii=False, indent=2)

    def _format_financial_df(
        self,
        df: pd.DataFrame,
        key_cols: List[str],
        periods: int,
        name: str,
    ) -> str:
        """通用财报 DataFrame → JSON 格式化"""
        if df.empty:
            return json.dumps({"error": f"无{name}数据"}, ensure_ascii=False)

        df = df.copy()
        if "end_date" in df.columns:
            df = df.drop_duplicates(subset=["end_date"], keep="last")
            df = df.sort_values("end_date", ascending=False).head(periods)
            df = df.sort_values("end_date")

        result = {"name": name, "periods": []}

        for _, row in df.iterrows():
            period_data = {"end_date": str(row.get("end_date", ""))}
            for col in key_cols:
                if col in df.columns:
                    val = row.get(col)
                    if pd.notna(val):
                        period_data[col] = round(float(val), 4) if isinstance(val, float) else val
            result["periods"].append(period_data)

        return json.dumps(result, ensure_ascii=False, indent=2)
