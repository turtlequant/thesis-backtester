# Thesis Backtester — AI-Driven Investment Thesis Analysis & Backtesting Framework

> Turn investment analysis methodology into an executable process — let AI analyze investment theses step by step following a research framework, and validate results through historical backtesting.

Traditional quant backtesting validates numerical rules (e.g. "buy when PE < 10"). Thesis Backtester validates the questions closer to real investment research:

- Is this high dividend sustainable, or borrowing from the future?
- Is the low PE genuinely cheap, or a value trap?
- Is management creating value or doing financial engineering?
- Can this business model survive a downturn?

The analysis framework is decomposed into reusable steps, executed by the engine in dependency order, with each step building on the conclusions of the previous one — reducing the skipping, omission, and instability of single-prompt approaches.

## Flagship Case: V6 Value Investing Framework

Current V6 value investing case: 120 stocks × 12 half-year cross-sections × 5 years (2020–2025), 5-baseline comparison:

| Baseline | Samples | 6M Return | Win Rate | vs CSI300 |
|----------|---------|----------|----------|-----------|
| CSI300 | 12 | +0.9% | 42% | — |
| Screen Pool | 600 | +4.0% | 53% | +3.0pp |
| **Agent Buy** | **43** | **+8.1%** | **65%** | **+7.1pp** |

![Cumulative Return Chart](strategies/v6_value/backtest/backtest_chart_20260316_1448.png)

**Avoidance signals are even stronger**: 73% of stocks the Agent flagged "avoid" subsequently declined. Risk avoidance alpha (-14.8pp) significantly exceeds stock selection alpha (+6.4pp).

<details>
<summary>Alpha decomposition</summary>

```
CSI300          +0.9%
                  │ +3.0pp  screening alpha
Screen Pool     +4.0%
                  │ +4.1pp  Agent incremental alpha
Agent Buy       +8.1%    end-to-end alpha: +7.1pp
```

Risk avoidance alpha (-14.8pp) vs stock selection alpha (+6.4pp)

</details>

> [Full report](strategies/v6_value/backtest/backtest_report_20260316_1448.md) · [Structured data](strategies/v6_value/backtest/backtest_summary_20260316_1448.json) · [120 analysis reports](strategies/v6_value/backtest/agent_reports/)

## Try It in 3 Minutes

> After completing setup below, run:

```bash
# ① Analyze a single stock (free public data)
python -m src.engine.launcher strategies/v6_enhanced/strategy.yaml live-analyze 601288.SH

# ② Or launch the desktop analysis workbench
python src/desktop/main.py
```

![Analysis Workbench](docs/app_image/分析界面.png)

<details>
<summary>View more screenshots</summary>

![Reports](docs/app_image/报告.png)
![Operators](docs/app_image/算子.png)
![Frameworks](docs/app_image/编排.png)
![Data Sources](docs/app_image/数据.png)
![Settings](docs/app_image/设置.png)

</details>

5 preset frameworks:

| Framework | Chapters | Focus |
|-----------|----------|-------|
| V6 Value Investing | 6 | Backtest-validated (+7.1pp alpha) |
| **V6 Enhanced** | **8** | **Deep analysis + forward risk + consistency ruling** |
| Quick Scan | 3 | 10-15 min fast assessment |
| Income Focus | 5 | Dividend sustainability |
| Bank Analysis | 6 | Bank-specific operators + industry metrics |

## Why This Is Not Just Another AI Stock Analyzer

- **Not a one-shot Q&A** — follows a fixed research framework, analyzing chapter by chapter
- **Not loose multi-turn chat** — each step's conclusions are explicitly passed to the next
- **Not just a current opinion** — can be validated against historical data through backtesting

## Core Design

```
strategy.yaml                    All-in-one config: screening + framework + scoring + LLM
       │
       ▼
┌─── Engine ──────────────────────────────────────────────────────┐
│  StrategyConfig · Launcher · OperatorRegistry · FactorRegistry  │
└──────┬──────────────┬───────────────────┬───────────────────────┘
       │              │                   │
  ┌────▼────┐   ┌─────▼──────┐   ┌───────▼────────┐
  │Screener │   │   Agent    │   │   Backtest      │
  │         │   │ 37 ops DAG │   │  Pipeline       │
  │         │   │ 3-layer    │   │ screen → agent  │
  └────┬────┘   │ scoring    │   │   → eval        │
       │        └─────┬──────┘   └───────┬────────┘
┌──────▼──────────────▼─────────────────▼───────────────────────┐
│  Data Layer: Provider abstraction · Parquet · Snapshot · API   │
└───────────────────────────────────────────────────────────────┘
```

| Design | Approach |
|--------|----------|
| **Operator-driven** | 37 `.md` operators, strategies compose via YAML, no code needed |
| **Blind testing** | Company names hidden to eliminate AI brand bias |
| **Time boundary** | Data layer filtering + prompt injection + tool sandbox |
| **3-layer scoring** | Thinking steps → scoring rubric → decision thresholds |
| **5-baseline comparison** | CSI300 / screen pool / top tier / Agent buy / Agent top5 |

<details>
<summary>Agent analysis flow (DAG dependency graph)</summary>

```mermaid
graph LR
    CH1[Ch1 Data Verification]
    CH2[Ch2 Fundamentals]
    CH3[Ch3 Cash Flow]
    CH4[Ch4 Valuation]
    CH5[Ch5 Stress Test]
    CH6[Ch6 Decision]
    SYN[Synthesis]

    CH1 --> CH2 & CH3
    CH2 --> CH3 & CH4
    CH3 --> CH4 & CH5
    CH4 --> CH5 & CH6
    CH5 --> CH6
    CH6 --> SYN

    style SYN fill:#ff6b35,color:#fff
    style CH1 fill:#4a90d9,color:#fff
    style CH2 fill:#4a90d9,color:#fff
    style CH3 fill:#4a90d9,color:#fff
    style CH4 fill:#4a90d9,color:#fff
    style CH5 fill:#4a90d9,color:#fff
    style CH6 fill:#4a90d9,color:#fff
```

</details>

<details>
<summary>Backtest pipeline (3 independent steps)</summary>

```bash
python -m src.engine.launcher strategies/v6_value/strategy.yaml backtest-screen   # ① Screen (seconds)
python -m src.engine.launcher strategies/v6_value/strategy.yaml backtest-agent    # ② Agent (hours)
python -m src.engine.launcher strategies/v6_value/strategy.yaml backtest-eval     # ③ Evaluate (minutes)
```

Each step is independent — can be interrupted and resumed. Agent automatically skips completed analyses.

</details>

## Setup

```bash
pip install -e .
export LLM_API_KEY="your_key"
export LLM_BASE_URL="https://api.deepseek.com"
```

<details>
<summary>Backtest mode (requires Tushare)</summary>

```bash
export TUSHARE_TOKEN="your_token"

python -m src.engine.launcher data init-basic
python -m src.engine.launcher data init-market 2020-01-01
python -m src.engine.launcher strategies/v6_value/strategy.yaml backtest-screen
python -m src.engine.launcher strategies/v6_value/strategy.yaml backtest-agent
python -m src.engine.launcher strategies/v6_value/strategy.yaml backtest-eval
```

</details>

<details>
<summary>Create your own strategy</summary>

1. Create `strategies/<name>/strategy.yaml` (reference [v6_value](strategies/v6_value/strategy.yaml))
2. Define screening conditions (`screening`)
3. Compose operators into chapters (`framework.chapters`)
4. Run `backtest-screen` → `backtest-agent` → `backtest-eval`

No code required. Output schema auto-generated from operator `outputs` definitions.

</details>

<details>
<summary>Project structure</summary>

```
src/
├── engine/        # Engine: config + launcher + registries
├── data/          # Data: Provider + Parquet + snapshot + free crawler
├── agent/         # Agent: LLM analysis (DAG scheduling + tool_use)
├── screener/      # Screener: declarative quantitative filtering
├── backtest/      # Backtest: 3-step pipeline + 5-baseline eval
└── desktop/       # Desktop: FastAPI + Vue 3 analysis workbench

operators/v1/      # Operator library v1 (21, frozen, tied to backtest results)
operators/v2/      # Operator library v2 (37, including forward risk + industry-specific operators)
strategies/        # Strategy instances (5 presets + custom)
```

</details>

## Who Is This For

- Anyone wanting to structure investment analysis methodology into a reusable, executable process
- Researchers testing whether AI can stably analyze stocks following a research framework
- Developers looking to reproduce thesis backtesting approaches

**Not for**: high-frequency trading, general-purpose quant backtesting platforms, or zero-config live trading.

## Current Boundaries

The most thoroughly validated case is V6 Value Investing; other preset frameworks are more exploratory analysis tools that have not yet achieved equivalent backtest validation. Results are primarily based on A-share value investing scenarios — cross-market and cross-model generalization is still under continuous validation.

## Roadmap

| Timeline | Plan |
|----------|------|
| **2026 Q2** | Mock portfolio: full CSI300 Agent evaluation → Top 15 holdings → public release → year-end accountability |
| **2026 H2** | 3-layer production: earnings-driven analysis (quarterly) + price monitoring (daily) + news verification (on-trigger) |
| **Ongoing** | Operator refinement · sample expansion (120 → 500+) · multi-strategy comparison |

## Tech Directions

- Engine-level gate enforcement (currently declarative only)
- Same-day result caching
- Multi-LLM comparison (DeepSeek / GPT / Claude)
- More free data sources (full announcements, research report summaries)

## Docs

- [Architecture](docs/design/architecture.md) · [Agent](docs/design/agent.md) · [Data Layer](docs/design/data_layer.md) · [Operators](docs/design/operators.md) · [Screener](docs/design/screener.md) · [Backtest](docs/design/backtest.md) · [Scoring](docs/design/scoring.md) · [Live Analysis](docs/design/live_analysis.md)

## License

AGPL-3.0 License

## Disclaimer

This tool is for **investment methodology research and validation only**. It does not constitute investment advice. Past backtest results do not guarantee future performance.

---

[中文文档](README.md)