# Developer Guide

## Project Overview

AI Agent-driven qualitative investment analysis tool. Configurable strategy instances for structured deep analysis of A-share stocks.
Core architecture: Engine (thesis-agnostic) + Instance (specific investment philosophy), driven by YAML config + operator composition.

## Setup

```bash
pip install -e .
export TUSHARE_TOKEN="your_token_here"
```

## Architecture

```
src/engine/        # Engine: StrategyConfig + Launcher + OperatorRegistry + Tracker
src/data/          # Data layer: Provider abstraction + Parquet storage + snapshots
  provider.py      #   DataProvider protocol (data source abstraction)
  tushare/         #   Tushare provider implementation (subfolder)
  storage.py       #   Parquet read/write (monthly partitions)
  updater.py       #   DataUpdater class (bulk fetch + incremental)
  factor_store.py  #   Factor pre-computation (截面 + 时序)
  api.py           #   Public query interface (read-only)
  snapshot.py      #   Time-point snapshot generation
src/agent/         # Agent: LLM-driven blind analysis (OpenAI-compatible tool_use)
src/screener/      # Screener: quantitative filtering (reads pre-computed factors)
src/backtest/      # Backtest: batch backtest + cross-section + outcome + scoring
src/web/           # Web: Streamlit strategy tuning dashboard

factors/           # Quantitative factor definitions (.py files, 截面+时序)
operators/         # Qualitative analysis operators (.md files, with YAML frontmatter)
  screening/       #   Data quality, geopolitical, quick screen, SOE identification
  fundamental/     #   Debt, cycle, cash trend, management, stream classification
  valuation/       #   FCF, dividend, PE trap, safety margin, owner earnings, repair
  decision/        #   Apple model, position management, stress test
  special/         #   Cigar butt, light asset model
strategies/        # Strategy instances (one directory per investment thesis)
  v6_value/        # V6 Value Investing (operator-driven)
    strategy.yaml  # Strategy config (filters, scoring, LLM, backtest)
    chapters.yaml  # Chapter definitions + operator composition

data/tushare/      # Parquet storage
  basic/           #   stock_list, trade_calendar
  daily/raw/       #   OHLCV by month (2019-01.parquet ...)
  daily/indicator/ #   PE/PB/DV/市值 by month
  daily/adj_factor/#   复权因子 by month
  daily/factors/   #   截面因子 by month (dv, ep, market_cap_yi, ...)
  daily/ts_factors/#   时序因子 (latest.parquet, 每股票一行)
data/financial/    #   财报 by stock (balancesheet/, income/, cashflow/, ...)
```

## Core Workflows

### Via Launcher (recommended)

```bash
# Quantitative screening
python -m src.engine.launcher strategies/v6_value/strategy.yaml screen 2024-06-30

# Agent-driven analysis (requires LLM_API_KEY + LLM_BASE_URL)
python -m src.engine.launcher strategies/v6_value/strategy.yaml agent-analyze 601288.SH 2024-06-30

# Batch: screen + auto agent analysis on top candidates
python -m src.engine.launcher strategies/v6_value/strategy.yaml batch-analyze 2024-06-30
```

### Direct module invocation

```bash
python -m src.screener.quick_filter 2024-06-30
python -m src.agent.runtime strategies/v6_value/strategy.yaml 601288.SH 2024-06-30
```

### Web Dashboard (strategy tuning)

```bash
streamlit run src/web/app.py
```

### Data Management (via Launcher)

```bash
# View data status
python -m src.engine.launcher data status

# Initialize basic data (stock list + trade calendar)
python -m src.engine.launcher data init-basic

# Initialize market data (daily quotes + indicators + factors)
python -m src.engine.launcher data init-market 2020-01-01

# Daily incremental update (quotes + indicators + factors)
python -m src.engine.launcher data daily-update

# Update specific data types
python -m src.engine.launcher data update-daily
python -m src.engine.launcher data update-indicator
python -m src.engine.launcher data update-factors

# Financial statements — bulk (cross-section by period, fast)
python -m src.engine.launcher data update-financials

# Financial statements — specific stocks (per-stock, all 15 tables incl. dividend/holders)
python -m src.engine.launcher data update-financials 601288.SH 000001.SZ

# Full recalculation of all cross-section factors
python -m src.engine.launcher data recalc-factors

# Time-series factors (per-stock attributes like 5y profit growth)
python -m src.engine.launcher data update-ts-factors
python -m src.engine.launcher data recalc-ts-factors

# Full update (basic + market + financials + factors)
python -m src.engine.launcher data full-update 2020-01-01 601288.SH 000001.SZ

# Snapshot generation
python -m src.data.snapshot 601288.SH 2024-06-30
```

### Cross-Section Backtest

```bash
python -m src.backtest.crosssection 601288.SH 2023-12-31,2024-06-30 plan
python -m src.backtest.outcome_collector 601288.SH 2024-06-30
```

## Module Responsibilities

- **data/provider.py**: DataProvider protocol — abstract interface for data sources
- **data/tushare/**: Tushare implementation of DataProvider
- **data/storage.py**: Parquet persistence layer (monthly partitions, merge/overwrite)
- **data/updater.py**: DataUpdater — bulk fetch, incremental updates, factor trigger
- **data/factor_store.py**: Factor pre-computation — compute all factors, store as parquet
- **data/api.py**: Public query interface (read-only, includes `get_factors()`)
- **data/snapshot.py**: Time-point snapshot generation for analysis
- **engine/config.py**: StrategyConfig — loads YAML, provides all strategy parameters
- **engine/factors.py**: FactorRegistry — discover and load Python factor files
- **engine/operators.py**: OperatorRegistry — discover and load Markdown analysis operators (with auto-schema)
- **engine/tracker.py**: Manage analysis run lifecycle (create, record, query, save reports)
- **engine/launcher.py**: CLI entry point — strategy commands + data management commands
- **agent/**: LLM agent runtime (client, tools sandbox, DAG scheduler, schemas)
- **screener/quick_filter.py**: Quantitative screening (reads pre-computed factors)
- **backtest/**: Batch backtest, cross-section, outcome, quality scoring

## Creating a New Strategy Instance

1. Create `strategies/<name>/strategy.yaml` (reference v6_value)
2. Create `strategies/<name>/chapters.yaml` — define chapters and select operators
3. Run screening: `python -m src.engine.launcher strategies/<name>/strategy.yaml screen 2024-06-30`
4. Run analysis: `python -m src.engine.launcher strategies/<name>/strategy.yaml agent-analyze 601288.SH 2024-06-30`

Output schema is auto-generated from operator `outputs` definitions. No `output_schema.py` needed.

## Design Principles

- **Operator-driven**: Analysis logic lives in operators (.md files with YAML frontmatter). Strategies compose operators via YAML chapters config
- **Three-layer scoring**: Operators solve "what to look at", chapters encode analysis ordering, synthesis prompt solves "how to think". Final scoring stays with LLM judgment — no explicit scoring formulas (see docs/design/scoring.md)
- **Structured synthesis**: synthesis config in strategy.yaml includes thinking_steps (cognitive path), scoring_rubric (calibration anchors), decision_thresholds (score-to-recommendation mapping)
- **Config-driven**: All strategy-specific values live in strategy.yaml, never hardcoded in engine
- **StrategyConfig required**: Engine functions require StrategyConfig — no fallback defaults
- **Time boundary**: All analysis strictly respects cutoff date. Data layer enforces hard filtering by announcement date (ann_date)
- **Provider abstraction**: Data acquisition decoupled from storage via DataProvider protocol. Swap Tushare for AKShare/CSV by implementing the protocol
- **Factor pre-computation**: Two types of factors, both pre-computed:
  - Cross-section (截面): computed per trading day, stored in `daily/factors/`. Run `data recalc-factors` after adding new definitions
  - Time-series (时序): computed once per stock from historical data, stored in `daily/ts_factors/`. Run `data recalc-ts-factors` after adding new definitions
