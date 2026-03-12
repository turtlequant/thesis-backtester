# Thesis Backtester — Backtest Any Investment Thesis with AI

> Can AI validate whether an investment philosophy actually works — before you risk real money?

**Thesis Backtester** is an open-source engine that backtests *qualitative* investment ideas using LLM-powered blind analysis. Unlike traditional quant backtesting (which only works with numeric rules like "buy when PE < 10"), this tool validates the kind of judgment calls real investors make:

- "Is this high dividend sustainable or a trap?"
- "Is this low PE genuinely cheap or a value trap?"
- "Does management have integrity?"
- "Can this business model survive a downturn?"

## The Core Idea

```
Traditional backtest:  numeric rule  →  historical prices  →  P&L
Thesis backtest:       investment philosophy  →  AI blind analysis  →  compare with actual outcomes
```

**How it works:**

1. **Define** your investment thesis as a structured analysis framework (YAML config + chapter templates)
2. **Screen** historical cross-sections: at each past date, find stocks that match your quantitative filters
3. **Blind-test**: feed the AI only the financial data available *up to that date*, with company names hidden
4. **Validate**: compare AI's buy/avoid recommendations against actual forward returns

The key insight: **any investment idea that can be described in words can be backtested this way.**

## Proof of Concept: 6-Year Blind Test

We validated a value investing thesis (turtle-grade screening: low PE + low PB + high dividend yield + FCF quality) across **60 stocks over 12 half-year cross-sections from 2019 to 2024**.

### Results

| Strategy | Samples | Avg 6-Month Return | Win Rate |
|----------|---------|-------------------|----------|
| Quantitative screening only | 60 | +7.5% | — |
| Quant + AI filtering (buy signals only) | 9 | **+24.1%** | **67%** |
| **AI filtering alpha** | — | **+16.6 pp** | — |

### What AI Does Well

| Strength | Evidence |
|----------|----------|
| Identifying leveraged value traps | 16 of 18 real estate stocks flagged as "avoid", avg return -10% |
| High-conviction buy signals | 6 stocks scored ≥70 with "buy": avg +41.5%, 83% win rate |
| Knowing when NOT to invest | No buy signals in 2019 & 2024 = cash preservation during downturns |

### Where AI Struggles

| Weakness | Evidence |
|----------|----------|
| Cyclical bottom reversals | Scored 25 on a stock that returned +73% |
| Too conservative in bull markets | "Avoid" signals averaged +30.6% return in 2020 |

### Year-by-Year Performance

| Year | Quant Only | AI High-Conviction | Notable Picks |
|------|-----------|-------------------|---------------|
| 2019 | -9.9% | Cash (no signal) | — |
| 2020 | +28.4% | -13.3% | 1 miss (bank stock) |
| 2021 | +7.7% | +21.4% | China Shenhua +46% |
| 2022 | +0.9% | +28.7% | PetroChina +50% |
| 2023 | +9.5% | +48.4% | 3 coal/bank picks, avg +48% |
| 2024 | +8.8% | Cash (no signal) | — |

> Full details: [strategies/v556_value/backtest/validation_report.md](strategies/v556_value/backtest/validation_report.md)

## Architecture

```
┌─────────────────────────────────────────────────┐
│              Thesis Backtester Engine            │
├─────────────────────────────────────────────────┤
│                                                 │
│  Strategy Instance (YAML-driven)                │
│  ┌───────────┐ ┌───────────┐ ┌───────────┐     │
│  │ Framework  │ │ Screener  │ │ Snapshot   │     │
│  │ Parser     │ │ & Sampler │ │ Generator  │     │
│  │            │ │           │ │            │     │
│  │ thesis →   │ │ filters → │ │ date →     │     │
│  │ chapters → │ │ pool →    │ │ data pack →│     │
│  │ prompts    │ │ samples   │ │ blind mask │     │
│  └─────┬─────┘ └─────┬─────┘ └─────┬─────┘     │
│        └──────────┬───┘─────────────┘           │
│                   ▼                             │
│  ┌─────────────────────────────────────────┐    │
│  │         AI Blind Analysis Engine         │    │
│  │  framework prompt + data snapshot → LLM  │    │
│  │  → structured score + recommendation     │    │
│  └───────────────────┬─────────────────────┘    │
│                      ▼                          │
│  ┌─────────────────────────────────────────┐    │
│  │       Validation & Attribution Engine    │    │
│  │  AI judgment vs actual returns           │    │
│  │  → accuracy, alpha, capability boundary  │    │
│  └─────────────────────────────────────────┘    │
│                                                 │
└─────────────────────────────────────────────────┘
```

### Key Design Decisions

- **Blind testing**: Company names are hidden to eliminate AI brand bias and memory contamination
- **Time-boundary enforcement**: 3-layer protection ensures no future data leakage (announcement date filtering, prompt injection, output scanning)
- **Strategy-as-config**: The engine is thesis-agnostic; each investment philosophy is a separate YAML-driven instance
- **Standardized output**: Every analysis produces a comparable score (0-100) and recommendation (buy/hold/avoid)

## Project Structure

```
src/
├── engine/        # Core: StrategyConfig + Launcher (thesis-agnostic)
├── data/          # Data layer: Tushare + Parquet + time-point snapshots
├── analyzer/      # Framework parser + prompt builder + orchestration
├── screener/      # Quantitative screening + blind batch testing
└── backtest/      # Cross-section analysis + outcome collection + scoring

strategies/
└── v556_value/    # Example: V5.5.6 Value Investing (turtle-grade)
    ├── strategy.yaml      # Full strategy configuration
    ├── chunks/            # Parsed analysis chapters (10 chapters)
    ├── output_schema.py   # Structured output definition
    └── backtest/          # 120 blind test reports + validation
```

## Quick Start

### Prerequisites

- Python 3.9+
- [Tushare Pro](https://tushare.pro/) API token (for A-share market data)
- An LLM API (Claude recommended; the framework prompts are in Chinese)

### Installation

```bash
pip install -e .

# Configure your Tushare token
export TUSHARE_TOKEN="your_token_here"
```

### Usage

All commands go through the unified launcher:

```bash
# Screen stocks at a specific date
python -m src.engine.launcher strategies/v556_value/strategy.yaml screen 2024-06-30

# Analyze a single stock (generates structured prompt)
python -m src.engine.launcher strategies/v556_value/strategy.yaml analyze 601288.SH 2024-06-30

# Blind test mode (company name hidden)
python -m src.engine.launcher strategies/v556_value/strategy.yaml analyze 601288.SH 2024-06-30 --blind

# Batch generate blind test prompts
python -m src.engine.launcher strategies/v556_value/strategy.yaml blind-generate

# Generate validation report
python -m src.engine.launcher strategies/v556_value/strategy.yaml blind-report
```

### Creating Your Own Strategy

1. Create `strategies/<name>/strategy.yaml` (see [v556_value](strategies/v556_value/strategy.yaml) for reference)
2. Write your investment thesis template
3. Define the output schema
4. Parse template: `python -m src.engine.launcher strategies/<name>/strategy.yaml parse-template`
5. Run screening and blind tests

## What Can Be Backtested?

Any investment philosophy that can be described in words:

| Thesis | Core Question | Status |
|--------|--------------|--------|
| Turtle-grade value investing | "Is this cheap stock genuinely undervalued?" | **Validated: +16.6pp alpha** |
| Dividend trap identification | "Is this high yield sustainable?" | Planned |
| Distressed turnaround | "Will this fallen angel recover?" | Planned |
| Cyclical timing | "Where are we in the cycle?" | Planned |
| Growth at reasonable price | "Can high growth justify high PE?" | Planned |
| SOE value rerating | "Does state reform translate to returns?" | Planned |

## How It Differs from Existing Tools

| Category | Examples | What They Test | What We Test |
|----------|---------|---------------|-------------|
| Quant backtesting | Zipline, Backtrader | Numeric trading rules | **Qualitative judgment** |
| AI stock screeners | Various | Factor scoring | **Structured thesis validation** |
| Research platforms | Wind, Bloomberg | Information retrieval | **Decision verification** |
| Robo-advisors | Wealthfront | Portfolio allocation | **Investment methodology** |

## Documentation

- [Product Design](docs/investment_thesis_backtester.md) — Full product vision and architecture
- [Data Roadmap](docs/data_dimensions_roadmap.md) — Planned data expansion
- [Framework Evolution](docs/framework_evolution.md) — Auto-improvement mechanisms
- [Scaling Plan](docs/scaling_plan.md) — Blind test scaling strategy

## Contributing

This project is in early stage. Contributions welcome in:

- **New strategy instances** — bring your own investment thesis
- **Data source adapters** — US/HK market data providers
- **Validation metrics** — Sharpe ratio, max drawdown, etc.
- **Multi-model support** — GPT, Gemini, Llama comparison

## License

Apache License 2.0 — see [LICENSE](LICENSE).

## Disclaimer

This tool is for **investment methodology research and validation only**. It does not constitute investment advice. Past backtest results do not guarantee future performance. Always do your own due diligence.

---

[中文文档](README.md)