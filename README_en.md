# Thesis Backtester — AI-Powered Investment Analysis Framework

> Strategy config → Quantitative screening → LLM multi-chapter deep analysis → Multi-baseline backtest validation

**Thesis Backtester** is an open-source engine that backtests *qualitative* investment ideas using LLM-powered blind analysis. Unlike traditional quant backtesting (which only works with numeric rules like "buy when PE < 10"), this tool validates the kind of judgment calls real investors make:

- "Is this high dividend sustainable or a trap?"
- "Is this low PE genuinely cheap or a value trap?"
- "Does management have integrity?"
- "Can this business model survive a downturn?"

## Backtest Results: 5-Year Blind Test on 120 Stocks

Validated a value investing strategy (low PE + low PB + high dividend + AI deep analysis) across **12 half-year cross-sections from 2020-2025, screening 600 candidates and analyzing 120 stocks**.

### 5-Baseline Performance Comparison (6-Month Forward Return)

| Baseline | Samples | Avg Return | Win Rate | vs CSI300 |
|----------|---------|-----------|----------|-----------|
| CSI300 Index | 12 | +0.9% | 42% | — |
| Screen Pool (equal-weight) | 600 | +4.0% | 53% | +3.0pp |
| Screen Top (Gold Tier) | 56 | +4.0% | 57% | +3.0pp |
| **Agent Buy** | **43** | **+8.1%** | **65%** | **+7.1pp** |
| Agent Top5 | 60 | +6.7% | 65% | +5.7pp |

### Cumulative Return Curve

![Cumulative Return Chart](strategies/v6_value/backtest/backtest_chart_20260316_1448.png)

### Alpha Decomposition

```
CSI300 Index    +0.9%    ← Market baseline
                  │ +3.0pp  ← Screening alpha
Screen Pool     +4.0%
                  │ +4.1pp  ← Agent incremental alpha
Agent Buy       +8.1%    ← End-to-end alpha: +7.1pp
```

- **Quantitative screening works**: Low valuation + high dividend beats CSI300 by 3.0pp, 53% win rate
- **Agent adds incremental value**: +4.1pp on top of screening, win rate from 53% → 65%
- **Stronger at longer horizon**: Agent Buy 12M avg return +13.9% (vs CSI300 +1.1%, alpha +12.8pp)
- **Avoid signals are effective**: Stocks the Agent avoided performed worse

> Full report: [backtest_report](strategies/v6_value/backtest/backtest_report_20260316_1448.md) | Structured data: [backtest_summary](strategies/v6_value/backtest/backtest_summary_20260316_1448.json)

## How It Works

```
Traditional backtest:  numeric rule  →  historical prices  →  P&L
Thesis backtest:       investment philosophy  →  AI blind analysis  →  compare with actual outcomes
```

### 3-Step Independent Pipeline

```bash
# Step 1: Generate cross-section dates + screen + save CSV (seconds)
python -m src.engine.launcher strategies/v6_value/strategy.yaml backtest-screen

# Step 2: Concurrent agent analysis + progress/retry/incremental (hours)
python -m src.engine.launcher strategies/v6_value/strategy.yaml backtest-agent
python -m src.engine.launcher strategies/v6_value/strategy.yaml backtest-agent --dry-run

# Step 3: Collect forward returns + 5-baseline evaluation + return chart (minutes)
python -m src.engine.launcher strategies/v6_value/strategy.yaml backtest-eval
```

Each step is independent — can be interrupted and resumed. Agent automatically skips completed analyses.

### Single Analysis

```bash
# Quantitative screening
python -m src.engine.launcher strategies/v6_value/strategy.yaml screen 2024-06-30

# Single stock agent analysis (requires LLM_API_KEY + LLM_BASE_URL)
python -m src.engine.launcher strategies/v6_value/strategy.yaml agent-analyze 601288.SH 2024-06-30

# Batch: screen + agent analysis
python -m src.engine.launcher strategies/v6_value/strategy.yaml batch-analyze 2024-06-30
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Strategy Instance                        │
│  strategy.yaml (screening + chapters + operators + scoring + LLM)│
└─────────────────────────┬───────────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────────┐
│                      Engine Layer (src/engine/)                  │
│  StrategyConfig · Launcher · FactorRegistry · OperatorRegistry  │
└──────┬──────────┬──────────┬────────────────────────────────────┘
       │          │          │
┌──────▼───┐ ┌───▼────┐ ┌──▼────────────────────────────────────┐
│ Screener │ │ Agent  │ │ Backtest Pipeline                      │
│          │ │ (Blind)│ │ screen → agent → eval (3 steps)        │
└──────┬───┘ └───┬────┘ └──┬────────────────────────────────────┘
       │         │         │
┌──────▼─────────▼─────────▼─────────────────────────────────────┐
│                      Data Layer (src/data/)                      │
│  Provider (abstract) · Parquet Storage · Snapshot · API          │
└─────────────────────────────────────────────────────────────────┘
```

### Key Design Decisions

- **Operator-driven**: 21 analysis operators (`.md` files), strategies compose via YAML, output schema auto-generated
- **6-chapter analysis framework**: Data verification → Fundamentals → Cash flow → Valuation → Stress test → Decision
- **Blind testing**: Company names hidden to eliminate AI brand bias and memory contamination
- **3-layer scoring**: Thinking steps guide reasoning + scoring rubric calibrates + decision thresholds enforce consistency
- **5-baseline comparison**: CSI300 + Screen pool + Gold tier + Agent buy + Agent top5
- **Time-boundary enforcement**: Data layer hard filtering + prompt injection + agent tool sandbox
- **Strategy-as-config**: `strategy.yaml` defines everything, no code needed

## Quick Start

### Prerequisites

```bash
pip install -e .
export TUSHARE_TOKEN="your_token_here"    # Tushare Pro account
export LLM_API_KEY="your_key_here"        # OpenAI-compatible API
export LLM_BASE_URL="https://api.deepseek.com"  # Recommended: DeepSeek
```

### Data Initialization

```bash
python -m src.engine.launcher data init-basic              # Stock list + trade calendar
python -m src.engine.launcher data init-market 2020-01-01  # Daily quotes + indicators + factors
python -m src.engine.launcher data daily-update            # Daily incremental update
```

### Creating Your Own Strategy

1. Create `strategies/<name>/strategy.yaml` (reference the [fully annotated v6_value config](strategies/v6_value/strategy.yaml))
2. Define quantitative screening in `screening` section
3. Compose operators in `framework.chapters` (or create new operators in `operators/`)
4. Run `backtest-screen` → `backtest-agent` → `backtest-eval`

No code required. Output schema auto-generated from operator `outputs` definitions.

## Project Structure

```
src/
├── engine/        # Engine: config + launcher + registries
├── data/          # Data: Provider + Parquet + snapshot
│   └── tushare/   #   Tushare Provider implementation
├── agent/         # Agent: LLM blind analysis (DAG + tool_use)
├── screener/      # Screener: declarative quantitative filtering
├── backtest/      # Backtest: 3-step pipeline + 5-baseline eval
└── web/           # Web: Streamlit workbench

factors/           # Quantitative factor definitions (.py)
operators/         # Qualitative analysis operators (.md, 26 total)
strategies/        # Strategy instances
└── v6_value/      #   V6 Value Investing (with full backtest data)
    ├── strategy.yaml       # Config (fully annotated)
    └── backtest/           # Backtest results
        ├── agent_reports/  #   120 agent analysis reports
        ├── screen_results/ #   12 cross-section screening CSVs
        └── backtest_chart_*.png  # Return curve chart
```

## Documentation

- [Architecture](docs/design/architecture.md) — System layers and module responsibilities
- [Agent Runtime](docs/design/agent.md) — DAG scheduling, prompt assembly, tool sandbox
- [Data Layer](docs/design/data_layer.md) — Provider abstraction, Parquet storage, snapshots
- [Operators & Factors](docs/design/operators.md) — 21 operator catalog, auto-schema, industry gates
- [Screener](docs/design/screener.md) — Declarative quantitative screening engine
- [Backtest](docs/design/backtest.md) — 3-step pipeline, 5-baseline evaluation
- [Scoring Design](docs/design/scoring.md) — 3-layer scoring philosophy
- [Scaling Plan](docs/scaling_plan.md) — Roadmap from 120 to 600+ samples

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.9+ |
| Storage | Parquet (zstd compression) |
| LLM Interface | OpenAI-compatible API (async, tool_use) |
| Data Source | Tushare Pro API (Provider abstraction) |
| Web | Streamlit |

## Contributing

Early stage project. Contributions welcome:

- **New strategy instances** — bring your own investment thesis
- **New analysis operators** — add `.md` files to `operators/`
- **Data source adapters** — implement `DataProvider` Protocol for US/HK markets
- **Multi-model comparison** — DeepSeek / GPT / Gemini benchmarks

## License

Apache License 2.0

## Disclaimer

This tool is for **investment methodology research and validation only**. It does not constitute investment advice. Past backtest results do not guarantee future performance. Always do your own due diligence.

---

[中文文档](README.md)
