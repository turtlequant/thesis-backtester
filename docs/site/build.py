#!/usr/bin/env python3
"""
Build script for the thesis-backtester showcase site.

Reads operators and strategies, generates JSON index files.
Must be run from the project root directory.

Usage:
    uv run python docs/site/build.py
"""

import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml is required. Run the script through the project environment: uv run python docs/site/build.py")
    sys.exit(1)


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
WORKSPACE_ROOT = PROJECT_ROOT / "workspace"
OPERATORS_DIR = WORKSPACE_ROOT / "operators" / "v2"
STRATEGIES_DIR = WORKSPACE_ROOT / "strategies"
OUTPUT_DIR = Path(__file__).resolve().parent / "data"


def parse_frontmatter(md_path: Path) -> dict | None:
    """Parse YAML frontmatter from a markdown file (between --- markers)."""
    try:
        text = md_path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"  WARN: cannot read {md_path}: {e}")
        return None

    if not text.startswith("---"):
        return None

    end = text.find("---", 3)
    if end == -1:
        return None

    try:
        fm = yaml.safe_load(text[3:end])
        if not isinstance(fm, dict):
            return None
        return fm
    except yaml.YAMLError as e:
        print(f"  WARN: bad YAML in {md_path}: {e}")
        return None


def build_operators() -> dict:
    """Scan workspace/operators/v2/**/*.md and build the operators index."""
    categories: dict[str, list] = {}
    total = 0

    if not OPERATORS_DIR.exists():
        print(f"  WARN: operators dir not found: {OPERATORS_DIR}")
        return {"total": 0, "categories": {}}

    for md_path in sorted(OPERATORS_DIR.rglob("*.md")):
        # Skip README files
        if md_path.name.lower() == "readme.md":
            continue

        fm = parse_frontmatter(md_path)
        if fm is None or "id" not in fm:
            print(f"  SKIP: {md_path.relative_to(PROJECT_ROOT)} (no valid frontmatter)")
            continue
        if fm.get("execution_mode") == "history_adapter":
            continue
        if "test" in fm.get("tags", []):
            continue

        # Determine category from directory name or frontmatter
        dir_category = md_path.parent.name
        category = fm.get("category", dir_category)

        # Relative path for GitHub raw URL
        rel_path = str(md_path.relative_to(PROJECT_ROOT))

        entry = {
            "id": fm["id"],
            "name": fm.get("name", fm["id"]),
            "category": category,
            "dir_category": dir_category,
            "tags": fm.get("tags", []),
            "data_needed": fm.get("data_needed", []),
            "outputs": fm.get("outputs", []),
            "file_path": rel_path,
        }

        # Include gate info if present
        if "gate" in fm:
            entry["gate"] = fm["gate"]
        if fm.get("history_variant"):
            entry["history_variant"] = fm["history_variant"]

        categories.setdefault(dir_category, []).append(entry)
        total += 1

    print(f"  Found {total} operators in {len(categories)} categories")
    return {"total": total, "categories": categories}


def build_strategies() -> list:
    """Scan workspace/strategies/*/strategy.yaml and build the strategies index."""
    strategies = []

    if not STRATEGIES_DIR.exists():
        print(f"  WARN: strategies dir not found: {STRATEGIES_DIR}")
        return []

    for yaml_path in sorted(STRATEGIES_DIR.glob("*/strategy.yaml")):
        strategy_name = yaml_path.parent.name
        try:
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  WARN: cannot parse {yaml_path}: {e}")
            continue

        if not isinstance(data, dict):
            print(f"  SKIP: {yaml_path} (not a dict)")
            continue

        meta = data.get("meta", {})
        if not meta:
            # Some strategies use top-level name/version
            meta = {
                "name": data.get("name", strategy_name),
                "version": data.get("version", ""),
            }

        framework = data.get("framework", {})
        chapters_raw = framework.get("chapters", [])
        synthesis = framework.get("synthesis", {})
        backtest = data.get("backtest", {})

        chapters = []
        for ch in chapters_raw:
            if not isinstance(ch, dict):
                continue
            chapters.append({
                "id": ch.get("id", ""),
                "chapter": ch.get("chapter", 0),
                "title": ch.get("title", ""),
                "operators": ch.get("operators", []),
                "dependencies": ch.get("dependencies", []),
            })

        # Extract decision thresholds
        thresholds = synthesis.get("decision_thresholds", {})

        entry = {
            "name": strategy_name,
            "display_name": meta.get("name", strategy_name),
            "version": str(meta.get("version", "")),
            "analyst_role": framework.get("analyst_role", ""),
            "chapters": chapters,
            "buy_threshold": thresholds.get("buy"),
            "avoid_threshold": thresholds.get("avoid"),
            "operators_dir": framework.get("operators_dir", ""),
        }

        # Add backtest config if present
        if backtest:
            entry["backtest"] = {
                "start_date": backtest.get("start_date", ""),
                "end_date": backtest.get("end_date", ""),
                "interval": backtest.get("cross_section_interval", ""),
            }

        strategies.append(entry)

    print(f"  Found {len(strategies)} strategies")
    return strategies


def main():
    print("Building showcase site data...")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("\n[1/2] Building operators.json")
    operators = build_operators()
    ops_path = OUTPUT_DIR / "operators.json"
    ops_path.write_text(json.dumps(operators, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  Written to {ops_path.relative_to(PROJECT_ROOT)}")

    print("\n[2/2] Building strategies.json")
    strategies = build_strategies()
    strat_path = OUTPUT_DIR / "strategies.json"
    strat_path.write_text(json.dumps(strategies, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  Written to {strat_path.relative_to(PROJECT_ROOT)}")

    print("\nDone.")


if __name__ == "__main__":
    main()
