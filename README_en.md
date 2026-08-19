# Thesis Backtester

> A structured investment research engine that turns investment theses into reusable operators, deterministic research workflows, and testable historical experiments.

Thesis Backtester is a local-first application focused on A-share research. It keeps numerical screening, qualitative analysis, historical validation, and report management on one explicit data boundary. LLMs assist inside the research pipeline; they do not replace it with open-ended chat.

## Core model

- **Operators** define bounded, reusable research methods with required data, steps, outputs, and decision constraints.
- **Frameworks** group multiple operators into research chapters and connect those chapters through a fixed DAG.
- **The engine** executes the DAG deterministically and persists chapter evidence, structured outputs, and synthesis.
- **The research assistant** reads the current page state and uses the same existing APIs as manual operations, subject to user confirmation.
- **Historical validation** freezes the data cutoff, screening strategy, framework, and run parameters. Current-only operators are replaced with contract-compatible historical variants; a run is blocked only when no safe equivalent exists.

```text
Provider → isolated SQLite → native fields / derived factors
                               │
             ┌─────────────────┴──────────────────┐
             ▼                                    ▼
   numerical screening                    operators → chapters → DAG
      │          │                                  │
      ▼          ▼                                  ▼
 current picks  historical test        single-stock / batch research
      │                                             │
      └────────────→ framework validation ←─────────┘
                               │
                               ▼
                    reports, evidence, performance
```

Numerical screening never depends on qualitative conclusions. Structured research may reference a saved screening strategy or candidate set in one direction.

## Desktop application

![Research framework and chapter DAG](docs/app_image/研究框架-DAG.png)

The native desktop window and browser UI expose three workspaces:

| Workspace | Capabilities |
|---|---|
| **Infrastructure** | Data maintenance, factor library, operator library, frameworks, system settings |
| **Cross-section screening** | Rule construction, dated stock selection, multi-period historical validation |
| **Structured research** | Single-stock analysis, latest batch judgement, framework validation, reports |

Each function page has an independent assistant context and conversation history. The assistant is open by default but cannot mutate a running DAG.

<details>
<summary>View key workflow screens</summary>

### Strategy construction

![Cross-section strategy construction](docs/app_image/截面筛选-策略构建.png)

### Historical validation

![Cross-section historical validation](docs/app_image/截面筛选-历史验证.png)

### Latest batch research

![Latest structured research](docs/app_image/结构化投研-最新研判.png)

### Analysis reports

![Structured research reports](docs/app_image/结构化投研-分析报告.png)

</details>

[View the complete application gallery](docs/SCREENSHOTS.md), covering infrastructure, cross-section screening, and structured research.

## Data boundaries

This is one application with independent provider adapters, not separate community and internal editions.

| Provider | Role | Local history | Boundary |
|---|---|---:|---|
| **BaoStock (default)** | Free historical market and basic valuation baseline | Yes | Quotes, adjustment factors, basic valuation, and limited quarterly indicators; not a complete financial-statement source |
| **Tushare Pro** | Subscription historical baseline | Yes | Quotes, valuation, statements, and governance coverage depend on account permissions |
| **AKShare** | Free current-time analysis | No | Current public pages, news, and market context; never used to silently fill strict historical databases |

BaoStock and Tushare use separate `workspace/data/providers/<provider>/market.db` files. A single analysis or backtest reads one provider only. Daily market bundles are committed atomically, financial downloads use resumable checkpoints, and interrupted jobs can continue safely.

See the [data-layer design](docs/design/data_layer.md) for details.

## Quick start

Requires Python 3.9+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/turtlequant/thesis-backtester.git
cd thesis-backtester

# Create or synchronize the project-local .venv
uv sync

# Launch the desktop application
uv run python -m src.desktop.main
```

The same application is available in a local browser at:

```text
http://127.0.0.1:18721
```

First-run workflow:

1. Select a provider in **Infrastructure → System Settings** and configure a Tushare token when applicable.
2. Initialize the stock list, calendar, market data, and required financial data in **Data Maintenance**.
3. Configure an OpenAI-compatible endpoint, model, and API key for structured LLM research.
4. Build and validate numerical rules in **Cross-section Screening**, then reference candidates from **Structured Research** when needed.

LLM configuration is not required for data maintenance, factor management, dated stock selection, or numerical historical validation.

## LAN access

LAN access is disabled by default. To access the application from a trusted laptop or tablet on the same network:

1. Open **Infrastructure → System Settings → Network Access**.
2. Enable LAN access, save, and copy the one-time access token.
3. Restart the application so it binds to `0.0.0.0` instead of `127.0.0.1`.
4. Open the displayed LAN URL on the other device and enter the token.

Loopback access does not require login. Remote HTTP APIs and WebSockets share the same authenticated session. Resetting the token immediately invalidates previous remote sessions. An authenticated remote user has the same research and configuration permissions as the local user, so enable this only on a trusted private network.

## CLI

The desktop application covers the primary workflows. The CLI is useful for automation and reproducible experiments. Run every command through the project environment:

```bash
# Data status and maintenance
uv run python -m src.engine.launcher data status
uv run python -m src.engine.launcher data init-basic
uv run python -m src.engine.launcher data init-market 2020-01-01
uv run python -m src.engine.launcher data update-financials
uv run python -m src.engine.launcher data daily-update

# Single-stock structured analysis
uv run python -m src.engine.launcher \
  workspace/strategies/v6_enhanced/strategy.yaml live-analyze 601288.SH

# Numerical screening
uv run python -m src.engine.launcher \
  workspace/strategies/v6_value/strategy.yaml screen 2024-06-30

# Interruptible three-step historical experiment
uv run python -m src.engine.launcher \
  workspace/strategies/v6_value/strategy.yaml backtest-screen
uv run python -m src.engine.launcher \
  workspace/strategies/v6_value/strategy.yaml backtest-agent
uv run python -m src.engine.launcher \
  workspace/strategies/v6_value/strategy.yaml backtest-eval
```

## Included research sample

Development included a V6 Value Investing historical experiment covering 120 stocks, 12 half-year cross-sections, and 2020–2025.

| Portfolio | Samples | 6M return | Win rate | vs CSI 300 |
|---|---:|---:|---:|---:|
| CSI 300 | 12 | +0.9% | 42% | — |
| Equal-weight screened pool | 600 | +4.0% | 53% | +3.0pp |
| **Agent buy** | **43** | **+8.1%** | **65%** | **+7.1pp** |

Detailed reports, structured outputs, and analysis samples are runtime artifacts and are not included in the public source or standard application package. This is a research sample, not evidence that the software, framework, or model will remain effective in the future.

## Project structure

```text
src/
├── desktop/       # FastAPI, Vue 3, pywebview, authenticated LAN access
├── data/          # Providers, SQLite, jobs, factor materialization, snapshots
├── engine/        # Strategy config, registries, CLI
├── agent/         # Fixed DAG scheduler, LLM client, bounded tools, output contracts
├── screener/      # Pure numerical screening
└── backtest/      # Cross-section experiments, forward returns, benchmarks

workspace/         # Portable research workspace
├── factors/       # Declarative derived-factor definitions
├── operators/v1/ # Frozen operators tied to retained research results
├── operators/v2/ # Current operators, industry operators, internal history variants
├── screening_strategies/ # Independent numerical screening strategies
├── strategies/    # Frameworks, reports, and backtest artifacts
└── data/          # Local databases and runtime state; not source code
docs/              # Product, architecture, and research documentation
```

## Development

```bash
uv run pytest -q
uv run ruff check src tests
```

Frameworks, operators, factors, reports, runtime settings, chat history, and local databases live under `workspace/`. Copy that directory as one unit for backup or migration. Frontend dependencies are vendored and do not require a CDN at startup.

### Windows distribution

Build a Nuitka standalone directory, run its packaged-runtime check, and create a ZIP archive:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1 -Clean
```

Standard artifacts are written to `dist/ThesisBacktester-<stage>-v<version>-windows-x64/`. The same build can also create a credential-free private Tushare baseline archive without BaoStock data. The release version is maintained only in `src/version.py`; see [Windows packaging and release](docs/PACKAGING.md) for the complete process.

## Documentation

- [Documentation index](docs/README.md)
- [Product guide](docs/PRODUCT_GUIDE.md)
- [Architecture](docs/design/architecture.md)
- [Data layer](docs/design/data_layer.md)
- [Factor library](docs/design/factor_library.md)
- [Operators and orchestration](docs/design/operators.md)
- [Backtesting](docs/design/backtest.md)
- [Windows packaging and release](docs/PACKAGING.md)

## Current boundaries

- The current focus is A-share research, not a universal cross-market trading platform.
- The project does not place live orders or provide high-frequency or automated asset-management features.
- Data quality, scope, and stability remain bounded by each provider.
- Structured-analysis effectiveness is a research hypothesis that requires continued validation within explicit samples and time boundaries.

## License

[AGPL-3.0-or-later](LICENSE)

## Disclaimer

This software and its outputs are for research and backtesting only and do not constitute investment advice. Data and analysis may contain errors; users must exercise independent judgment and assume their own risk. Historical backtest results do not represent future performance.

---

[中文文档](README.md)
