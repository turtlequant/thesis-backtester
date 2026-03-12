# Developer Guide

## Project Overview

AI Agent-driven qualitative investment analysis tool. Configurable strategy instances for structured deep analysis of A-share stocks.
Core architecture: Engine (thesis-agnostic) + Instance (specific investment philosophy), driven by YAML config.

## Setup

```bash
pip install -e .
export TUSHARE_TOKEN="your_token_here"
```

## Architecture

```
src/engine/        # Engine: StrategyConfig + Launcher
src/data/          # Data: Tushare + Parquet + time-point snapshots
src/analyzer/      # Analyzer: framework parsing + prompt assembly + orchestration
src/screener/      # Screener: quantitative filtering + blind batch testing
src/backtest/      # Backtest: cross-section analysis + outcome collection + scoring

strategies/        # Strategy instances (one directory per investment thesis)
  v556_value/      # V5.5.6 Value Investing (turtle-grade)
    strategy.yaml  # Strategy config (filters, chapters, blind test params)
    output_schema.py  # Structured output definition
    chunks/        # Parsed chapter files
```

## Core Workflows

### Via Launcher (recommended)

```bash
# Quantitative screening
python -m src.engine.launcher strategies/v556_value/strategy.yaml screen 2024-06-30

# Single stock analysis (generate prompt)
python -m src.engine.launcher strategies/v556_value/strategy.yaml analyze 601288.SH 2024-06-30

# Blind test mode
python -m src.engine.launcher strategies/v556_value/strategy.yaml analyze 601288.SH 2024-06-30 --blind

# Batch blind test prompt generation
python -m src.engine.launcher strategies/v556_value/strategy.yaml blind-generate

# Validation report
python -m src.engine.launcher strategies/v556_value/strategy.yaml blind-report

# Parse investment template into chapters
python -m src.engine.launcher strategies/v556_value/strategy.yaml parse-template
```

### Direct module invocation (backward compatible)

```bash
python -m src.screener.quick_filter 2024-06-30
python -m src.analyzer.analysis_runner 601288.SH 2024-06-30
python -m src.screener.blind_batch generate
python -m src.screener.blind_batch report
```

All modules support `--strategy <yaml>` to specify strategy.

### Data Management

```bash
python -c "from src.data.updater import init_basic; init_basic()"
python -c "from src.data.updater import update_stock_all; update_stock_all('601288.SH')"
python -m src.data.snapshot 601288.SH 2024-06-30
```

### Cross-Section Backtest

```bash
python -m src.backtest.crosssection 601288.SH 2023-12-31,2024-06-30 plan
python -m src.backtest.outcome_collector 601288.SH 2024-06-30
```

## Creating a New Strategy Instance

1. Create `strategies/<name>/strategy.yaml` (reference v556_value)
2. Write investment thesis template `strategies/<name>/template.md`
3. Define output schema `strategies/<name>/output_schema.py`
4. Parse template: `python -m src.engine.launcher strategies/<name>/strategy.yaml parse-template`
5. Run screening and blind test validation

## Time Boundary Rules

All analysis strictly respects the cutoff date — no information after that date is used. Data layer enforces hard filtering by financial report announcement date (not reporting period).
