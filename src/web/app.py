"""
投研分析工作台 — Streamlit Web App

核心功能:
  - 选择预设策略或自定义算子组合
  - 输入股票代码运行实时分析
  - 实时展示各章节执行进度
  - 展示完整分析报告

启动:
    streamlit run src/web/app.py
"""
import asyncio
import json
import sys
import time
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st
import pandas as pd

from src.engine.config import StrategyConfig
from src.engine.operators import OperatorRegistry

# ==================== 页面配置 ====================

st.set_page_config(page_title="投研分析工作台", page_icon="📊", layout="wide")


# ==================== 工具函数 ====================

def find_strategies() -> list:
    d = PROJECT_ROOT / "strategies"
    return sorted(str(p.relative_to(PROJECT_ROOT)) for p in d.rglob("strategy.yaml")) if d.exists() else []


def load_analysis_history(config: StrategyConfig) -> list:
    """加载 live/ 目录下的历史分析"""
    live_dir = config.strategy_dir / "live"
    if not live_dir.exists():
        return []
    results = []
    for d in sorted(live_dir.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        structured = d / f"{d.name}_structured.json"
        # 也尝试不带前缀的文件
        if not structured.exists():
            candidates = list(d.glob("*_structured.json"))
            structured = candidates[0] if candidates else None
        if structured and structured.exists():
            try:
                data = json.loads(structured.read_text(encoding='utf-8'))
                syn = data.get('synthesis', {})
                meta = data.get('metadata', {})
                results.append({
                    'dir': str(d),
                    'name': d.name,
                    'ts_code': meta.get('ts_code', ''),
                    'date': meta.get('cutoff_date', ''),
                    'score': syn.get('综合评分', ''),
                    'recommendation': syn.get('最终建议', ''),
                    'stream': syn.get('流派判定', ''),
                    'elapsed': meta.get('elapsed_seconds', 0),
                })
            except Exception:
                continue
    return results


# ==================== 侧边栏 ====================

st.sidebar.header("📊 投研分析工作台")

strategies = find_strategies()
if not strategies:
    st.error("未找到策略文件")
    st.stop()

selected_yaml = st.sidebar.selectbox("策略", strategies)
config = StrategyConfig.from_yaml(selected_yaml)
st.sidebar.caption(f"{config.name} v{config.version}")

# 加载算子注册表
registry = config.get_operator_registry()
all_ops = registry.list_all()
all_op_ids = [op.id for op in all_ops]

st.sidebar.divider()

# ==================== 主区域：两个 Tab ====================

tab_analyze, tab_history = st.tabs(["🔬 实时分析", "📋 历史记录"])


# ==================== Tab 1: 实时分析 ====================

with tab_analyze:

    # ---- 分析配置 ----
    col_left, col_right = st.columns([1, 2])

    with col_left:
        st.subheader("分析配置")

        # 股票代码
        ts_code = st.text_input("股票代码", value="601288.SH", placeholder="601288.SH")

        # 策略模式
        mode = st.radio("算子选择", ["预设策略", "自定义组合"], horizontal=True)

        if mode == "预设策略":
            chapters = config.get_chapter_defs()
            st.caption(f"使用 {config.name} 的 {len(chapters)} 章分析框架")
            # 展示各章算子
            for ch in chapters:
                with st.expander(f"Ch{ch.get('chapter', '?')} {ch.get('title', '')}"):
                    ops = ch.get('operators', [])
                    for op_id in ops:
                        op = registry.get(op_id)
                        if op:
                            st.markdown(f"- **{op.name}** (`{op.id}`)")
                        else:
                            st.markdown(f"- ~~{op_id}~~ (未找到)")
        else:
            # 自定义：从算子库勾选
            st.caption("从算子库中选择要使用的算子")
            all_tags = registry.all_tags()
            tag_filter = st.multiselect("按标签筛选", all_tags)

            if tag_filter:
                filtered = [op for op in all_ops if any(t in op.tags for t in tag_filter)]
            else:
                filtered = all_ops

            selected_ops = []
            for op in filtered:
                if st.checkbox(f"{op.name} (`{op.id}`)", value=True, key=f"op_{op.id}"):
                    selected_ops.append(op.id)
            st.caption(f"已选择 {len(selected_ops)} 个算子")

        # 运行按钮
        st.divider()
        blind = st.checkbox("盲测模式（隐藏公司名称）", value=False)
        run_btn = st.button("▶ 开始分析", type="primary", use_container_width=True)

    # ---- 分析过程 & 结果 ----
    with col_right:
        if run_btn:
            if not ts_code.strip():
                st.error("请输入股票代码")
                st.stop()

            st.subheader(f"分析: {ts_code}")

            # 进度容器
            progress_area = st.container()
            result_area = st.container()

            with progress_area:
                # Step 1: 获取数据
                with st.status("获取实时数据...", expanded=True) as status_data:
                    st.write("正在从公开数据源获取财务数据...")

                    from src.data.live_snapshot import create_live_snapshot
                    from src.data.snapshot import snapshot_to_markdown

                    snapshot = create_live_snapshot(ts_code.strip())
                    st.write(f"✓ 数据源: {', '.join(snapshot.data_sources)}")
                    st.write(f"✓ 最新报告期: {snapshot.latest_report_period}")
                    if snapshot.warnings:
                        for w in snapshot.warnings:
                            st.warning(w)
                    status_data.update(label=f"数据获取完成 ({len(snapshot.data_sources)} 个数据源)", state="complete")

                # Step 2: Agent 分析
                chapters = config.get_chapter_defs()
                chapter_statuses = {}

                # 创建章节状态占位
                st.divider()
                st.write("**Agent 分析进度:**")
                chapter_placeholders = {}
                for ch in chapters:
                    ch_id = ch['id']
                    chapter_placeholders[ch_id] = st.empty()
                    chapter_placeholders[ch_id].markdown(f"⏳ Ch{ch.get('chapter', '?')} {ch.get('title', '')}")

                synthesis_placeholder = st.empty()
                synthesis_placeholder.markdown("⏳ 综合研判")

                # 进度回调
                def on_progress(event, ch_id=None, data=None):
                    if event == "chapter_start" and ch_id in chapter_placeholders:
                        title = data.get("title", ch_id) if data else ch_id
                        chapter_placeholders[ch_id].markdown(f"🔄 Ch **{title}** — 分析中...")
                    elif event == "chapter_done" and ch_id in chapter_placeholders:
                        ch_def = next((c for c in chapters if c['id'] == ch_id), {})
                        title = ch_def.get('title', ch_id)
                        chapter_placeholders[ch_id].markdown(f"✅ Ch{ch_def.get('chapter', '?')} {title}")
                        chapter_statuses[ch_id] = data
                    elif event == "synthesis_start":
                        synthesis_placeholder.markdown("🔄 **综合研判** — 分析中...")
                    elif event == "synthesis_done":
                        synthesis_placeholder.markdown("✅ 综合研判完成")

                # 运行 Agent
                from src.agent.runtime import run_blind_analysis

                live_dir = config.strategy_dir / "live" / f"{ts_code.strip()}_{datetime.now().strftime('%Y-%m-%d')}"
                live_dir.mkdir(parents=True, exist_ok=True)

                # 保存原始数据
                raw_dir = live_dir / "raw_data"
                raw_dir.mkdir(exist_ok=True)
                for attr in ['price_history', 'balancesheet', 'income', 'cashflow',
                             'fina_indicator', 'dividend', 'top10_holders',
                             'news', 'fund_flow', 'index_daily', 'industry_summary']:
                    df = getattr(snapshot, attr, None)
                    if df is not None and not df.empty:
                        df.to_csv(raw_dir / f"{attr}.csv", index=False, encoding='utf-8-sig')

                cutoff_date = datetime.now().strftime('%Y-%m-%d')

                with st.spinner("Agent 分析运行中..."):
                    result = asyncio.run(
                        run_blind_analysis(
                            ts_code.strip(), cutoff_date, config, blind, live_dir,
                            on_progress=on_progress, snapshot=snapshot,
                        )
                    )

            # Step 3: 展示结果
            with result_area:
                st.divider()
                synthesis = result.get("synthesis", {})
                meta = result.get("metadata", {})

                if synthesis:
                    st.subheader("分析结论")

                    # 核心指标卡片
                    mc1, mc2, mc3, mc4 = st.columns(4)
                    mc1.metric("综合评分", synthesis.get('综合评分', '?'))
                    mc2.metric("最终建议", synthesis.get('最终建议', '?'))
                    mc3.metric("流派", synthesis.get('流派判定', '?'))
                    mc4.metric("信心", synthesis.get('信心水平', '?'))

                    # 买入逻辑
                    logic = synthesis.get('一句话买入逻辑（强制）', '')
                    if logic:
                        st.info(f"**买入逻辑**: {logic}")

                    # 关键风险
                    risks = synthesis.get('关键风险', [])
                    if risks:
                        with st.expander("关键风险", expanded=True):
                            for r in risks:
                                st.markdown(f"- {r}")

                    # 综合研判 JSON
                    with st.expander("结构化结论 (JSON)"):
                        st.json(synthesis)

                # 各章详情
                chapter_outputs = result.get("chapter_outputs", {})
                if chapter_outputs:
                    with st.expander("各章结构化结论"):
                        for ch in chapters:
                            ch_id = ch['id']
                            if ch_id in chapter_outputs:
                                st.markdown(f"**Ch{ch.get('chapter', '?')} {ch.get('title', '')}**")
                                st.json(chapter_outputs[ch_id])
                                st.markdown("---")

                # 完整报告
                report_files = list(live_dir.glob("*_report.md"))
                if report_files:
                    with st.expander("完整分析报告 (Markdown)"):
                        md_text = report_files[0].read_text(encoding='utf-8')
                        st.markdown(md_text)

                # 元数据
                st.caption(
                    f"耗时: {meta.get('elapsed_seconds', 0):.0f}s | "
                    f"模型: {meta.get('model', '')} | "
                    f"章节: {meta.get('chapters_completed', 0)} | "
                    f"输出: {live_dir}"
                )

        else:
            # 未点击运行时的占位内容
            st.subheader("使用说明")
            st.markdown("""
            1. 在左侧输入**股票代码**（如 `601288.SH`）
            2. 选择**预设策略**或**自定义算子组合**
            3. 点击 **▶ 开始分析**
            4. 实时查看各章节分析进度和最终结论

            分析过程约 5-10 分钟，使用免费公开数据，需要配置 LLM API Key。

            ```bash
            export LLM_API_KEY="your_key"
            export LLM_BASE_URL="https://api.deepseek.com"
            streamlit run src/web/app.py
            ```
            """)

            # 展示算子库概览
            st.subheader(f"算子库 ({len(all_ops)} 个)")
            op_rows = []
            for op in all_ops:
                op_rows.append({
                    'ID': op.id,
                    '名称': op.name,
                    '标签': ', '.join(op.tags),
                    '数据需求': ', '.join(op.data_needed),
                })
            st.dataframe(pd.DataFrame(op_rows), use_container_width=True, hide_index=True)


# ==================== Tab 2: 历史记录 ====================

with tab_history:
    history = load_analysis_history(config)

    if not history:
        st.info("暂无历史分析记录。运行一次实时分析后会在此显示。")
    else:
        st.subheader(f"历史分析 ({len(history)} 份)")

        # 汇总表
        hist_df = pd.DataFrame(history)
        display_cols = ['name', 'score', 'recommendation', 'stream', 'elapsed']
        col_rename = {'name': '分析', 'score': '评分', 'recommendation': '建议',
                      'stream': '流派', 'elapsed': '耗时(s)'}
        st.dataframe(
            hist_df[display_cols].rename(columns=col_rename),
            use_container_width=True, hide_index=True,
        )

        # 查看详情
        st.divider()
        selected_name = st.selectbox(
            "查看详情",
            [h['name'] for h in history],
        )

        if selected_name:
            selected = next(h for h in history if h['name'] == selected_name)
            detail_dir = Path(selected['dir'])

            # 读取 structured.json
            structured_files = list(detail_dir.glob("*_structured.json"))
            if structured_files:
                data = json.loads(structured_files[0].read_text(encoding='utf-8'))
                syn = data.get('synthesis', {})

                # 指标卡片
                dc1, dc2, dc3, dc4 = st.columns(4)
                dc1.metric("评分", syn.get('综合评分', ''))
                dc2.metric("建议", syn.get('最终建议', ''))
                dc3.metric("流派", syn.get('流派判定', ''))
                dc4.metric("信心", syn.get('信心水平', ''))

                logic = syn.get('一句话买入逻辑（强制）', '')
                if logic:
                    st.info(f"**买入逻辑**: {logic}")

                with st.expander("结构化结论"):
                    st.json(syn)

                # 各章结论
                ch_outputs = data.get('chapter_outputs', {})
                if ch_outputs:
                    with st.expander("各章结论"):
                        for ch_id, ch_data in ch_outputs.items():
                            st.markdown(f"**{ch_id}**")
                            st.json(ch_data)
                            st.markdown("---")

            # 完整报告
            report_files = list(detail_dir.glob("*_report.md"))
            if report_files:
                with st.expander("完整报告"):
                    st.markdown(report_files[0].read_text(encoding='utf-8'))

            # 原始数据文件列表
            raw_dir = detail_dir / "raw_data"
            if raw_dir.exists():
                with st.expander("原始数据文件"):
                    for f in sorted(raw_dir.glob("*.csv")):
                        st.caption(f.name)
