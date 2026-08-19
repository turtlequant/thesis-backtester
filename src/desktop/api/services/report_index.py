"""SQLite-backed index over immutable structured analysis report files.

The JSON/Markdown artifacts remain the source of truth.  SQLite only stores
the fields needed to browse and filter reports without reparsing every file on
each page load.  A lightweight reconciliation pass picks up files created by
single-stock analysis, latest-judgement batches and read-only historical
backtest samples.
"""
from __future__ import annotations

import csv
import json
import logging
import sqlite3
import threading
import math
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from src.data.settings import DATA_ROOT, WORKSPACE_ROOT
from src.desktop.runtime import DESKTOP_RUNTIME_DIR
from src.engine.config import StrategyConfig

logger = logging.getLogger(__name__)

REPORT_DB_PATH = DESKTOP_RUNTIME_DIR / "research.db"
QUALITATIVE_RUNS_ROOT = DATA_ROOT / "qualitative_runs"
_INDEX_LOCK = threading.RLock()


def _connect(path: Optional[Path] = None) -> sqlite3.Connection:
    path = Path(path or REPORT_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS report_index (
            report_id TEXT PRIMARY KEY,
            structured_path TEXT NOT NULL UNIQUE,
            report_md_path TEXT,
            framework_id TEXT NOT NULL,
            framework_name TEXT NOT NULL,
            framework_version TEXT,
            stock_code TEXT NOT NULL,
            stock_name TEXT,
            analysis_date TEXT NOT NULL,
            model TEXT,
            elapsed_seconds REAL,
            score REAL,
            recommendation TEXT,
            confidence TEXT,
            core_logic TEXT,
            risks TEXT,
            origin TEXT NOT NULL DEFAULT 'individual',
            origin_run_id TEXT,
            file_mtime_ns INTEGER NOT NULL,
            file_size INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            indexed_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_report_stock_date ON report_index(stock_code, analysis_date)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_report_framework ON report_index(framework_id)"
    )
    return connection


def _first(mapping: Dict[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", [], {}):
            return value
    return default


def _score(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        import re

        match = re.search(r"-?\d+(?:\.\d+)?", str(value))
        return float(match.group()) if match else None


def _text(value: Any) -> str:
    if isinstance(value, list):
        return "；".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value or "")


def _framework_meta(strategy_dir: Path) -> Dict[str, Any]:
    framework_id = strategy_dir.name
    try:
        config = StrategyConfig.from_yaml(strategy_dir / "strategy.yaml")
        chapters = config.get_chapter_defs()
        return {
            "id": framework_id,
            "name": config.name or framework_id,
            "version": str(config.version or ""),
            "chapter_titles": {
                item["id"]: item.get("title") or item["id"] for item in chapters
            },
            "chapter_order": [item["id"] for item in chapters],
        }
    except Exception as exc:
        logger.warning("Failed to load report framework %s: %s", framework_id, exc)
        return {
            "id": framework_id,
            "name": framework_id,
            "version": "",
            "chapter_titles": {},
            "chapter_order": [],
        }


def _latest_origins(root: Path) -> Dict[str, Dict[str, str]]:
    origins: Dict[str, Dict[str, str]] = {}
    if not root.exists():
        return origins
    for run_path in root.glob("*/run.json"):
        try:
            run = json.loads(run_path.read_text(encoding="utf-8"))
            if run.get("kind") != "latest_judgement":
                continue
            for row in run.get("rows", []):
                path = row.get("report_path")
                if path:
                    origin = {
                        "origin": "latest_judgement",
                        "origin_run_id": str(run.get("id", "")),
                    }
                    report_path = Path(path)
                    origins[str(report_path.resolve()).casefold()] = origin
                    parts = report_path.parts
                    strategies_at = next(
                        (
                            index
                            for index, part in enumerate(parts)
                            if part.casefold() == "strategies"
                        ),
                        None,
                    )
                    if strategies_at is not None:
                        portable = Path(*parts[strategies_at:]).as_posix().casefold()
                        origins[portable] = origin
        except (OSError, ValueError, TypeError):
            continue
    return origins


def _iter_reports(project_root: Path) -> Iterable[tuple[Path, Path, Dict[str, str]]]:
    strategies_dir = project_root / "strategies"
    if not strategies_dir.exists():
        return
    for strategy_dir in sorted(strategies_dir.iterdir()):
        if not strategy_dir.is_dir():
            continue
        live_dir = strategy_dir / "live"
        if live_dir.exists():
            for path in live_dir.rglob("*_structured.json"):
                yield strategy_dir, path, {"origin": "individual", "origin_run_id": ""}
        backtest_dir = strategy_dir / "backtest" / "agent_reports"
        if backtest_dir.exists():
            for path in backtest_dir.glob("*_structured.json"):
                yield strategy_dir, path, {
                    "origin": "historical_backtest",
                    "origin_run_id": f"legacy:{strategy_dir.name}",
                }


def _backtest_stock_names(strategy_dir: Path) -> Dict[tuple[str, str], str]:
    """Recover names omitted by legacy blind-analysis JSON from screen CSVs."""
    names: Dict[tuple[str, str], str] = {}
    screen_dir = strategy_dir / "backtest" / "screen_results"
    if not screen_dir.exists():
        return names
    for path in screen_dir.glob("screen_*.csv"):
        cutoff_date = path.stem.removeprefix("screen_")
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    code = str(row.get("ts_code") or "").strip()
                    name = str(row.get("stock_name") or "").strip()
                    if code and name:
                        names[(code, cutoff_date)] = name
        except (OSError, UnicodeError, csv.Error):
            continue
    return names


def _read_index_record(
    strategy_dir: Path,
    structured_path: Path,
    *,
    origin: Optional[Dict[str, str]] = None,
    framework: Optional[Dict[str, Any]] = None,
    stock_names: Optional[Dict[tuple[str, str], str]] = None,
) -> Dict[str, Any]:
    data = json.loads(structured_path.read_text(encoding="utf-8"))
    metadata = data.get("metadata") or {}
    synthesis = data.get("synthesis") or {}
    framework = framework or _framework_meta(strategy_dir)
    stat = structured_path.stat()
    report_md = structured_path.with_name(
        structured_path.name.replace("_structured.json", "_report.md")
    )
    origin = origin or {"origin": "individual", "origin_run_id": ""}
    inferred = structured_path.name.removesuffix("_structured.json")
    inferred_code, _, inferred_date = inferred.partition("_")
    analysis_date = str(metadata.get("cutoff_date") or inferred_date)
    stock_code = str(metadata.get("ts_code") or inferred_code)
    historical = origin.get("origin") == "historical_backtest"
    return {
        "report_id": (
            f"{strategy_dir.name}__historical_backtest__{structured_path.stem}"
            if historical
            else f"{strategy_dir.name}__{structured_path.stem}"
        ),
        "structured_path": str(structured_path.resolve()),
        "report_md_path": str(report_md.resolve()) if report_md.exists() else "",
        "framework_id": framework["id"],
        "framework_name": framework["name"],
        "framework_version": str(metadata.get("framework_version") or framework["version"]),
        "stock_code": stock_code,
        "stock_name": str(
            metadata.get("stock_name")
            or (stock_names or {}).get((stock_code, analysis_date), "")
        ),
        "analysis_date": analysis_date,
        "model": str(metadata.get("model") or ""),
        "elapsed_seconds": float(metadata.get("elapsed_seconds") or 0),
        "score": _score(_first(synthesis, "综合评分", "总体评分", "score", "overall_score", default=None)),
        "recommendation": str(_first(synthesis, "最终建议", "投资建议", "recommendation")),
        "confidence": str(_first(synthesis, "信心水平", "置信度", "confidence")),
        "core_logic": str(
            _first(
                synthesis,
                "核心逻辑",
                "一句话买入逻辑（强制）",
                "一句话买入逻辑",
                "one_line_logic",
            )
        ),
        "risks": _text(_first(synthesis, "关键风险", "风险提示", "主要风险", "risks")),
        "origin": origin.get("origin", "individual"),
        "origin_run_id": origin.get("origin_run_id", ""),
        "file_mtime_ns": stat.st_mtime_ns,
        "file_size": stat.st_size,
        "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "indexed_at": datetime.now().isoformat(timespec="seconds"),
    }


_UPSERT_COLUMNS = (
    "report_id", "structured_path", "report_md_path", "framework_id",
    "framework_name", "framework_version", "stock_code", "stock_name",
    "analysis_date", "model", "elapsed_seconds", "score", "recommendation",
    "confidence", "core_logic", "risks", "origin", "origin_run_id",
    "file_mtime_ns", "file_size", "created_at", "indexed_at",
)


def _upsert(connection: sqlite3.Connection, record: Dict[str, Any]) -> None:
    placeholders = ", ".join("?" for _ in _UPSERT_COLUMNS)
    updates = ", ".join(
        f"{column}=excluded.{column}"
        for column in _UPSERT_COLUMNS
        if column != "report_id"
    )
    connection.execute(
        f"""
        INSERT INTO report_index ({', '.join(_UPSERT_COLUMNS)})
        VALUES ({placeholders})
        ON CONFLICT(report_id) DO UPDATE SET {updates}
        """,
        tuple(record[column] for column in _UPSERT_COLUMNS),
    )


def sync_report_index(
    project_root: Path = WORKSPACE_ROOT,
    *,
    db_path: Optional[Path] = None,
    qualitative_runs_root: Optional[Path] = None,
) -> Dict[str, int]:
    """Reconcile report files with SQLite, parsing only new or changed files."""
    project_root = Path(project_root)
    origins = _latest_origins(Path(qualitative_runs_root or QUALITATIVE_RUNS_ROOT))
    counts = {"indexed": 0, "unchanged": 0, "removed": 0, "errors": 0}
    with _INDEX_LOCK, closing(_connect(db_path)) as connection, connection:
        existing = {
            str(row["structured_path"]).casefold(): dict(row)
            for row in connection.execute("SELECT * FROM report_index")
        }
        seen = set()
        framework_cache: Dict[str, Dict[str, Any]] = {}
        stock_name_cache: Dict[str, Dict[tuple[str, str], str]] = {}
        for strategy_dir, path, default_origin in _iter_reports(project_root):
            resolved = str(path.resolve())
            key = resolved.casefold()
            seen.add(key)
            stat = path.stat()
            portable_key = path.relative_to(project_root).as_posix().casefold()
            origin = origins.get(key) or origins.get(portable_key) or default_origin
            cached = existing.get(key)
            if (
                cached
                and cached["file_mtime_ns"] == stat.st_mtime_ns
                and cached["file_size"] == stat.st_size
                and cached["origin"] == origin["origin"]
                and (cached["origin_run_id"] or "") == origin["origin_run_id"]
            ):
                counts["unchanged"] += 1
                continue
            try:
                framework = framework_cache.get(strategy_dir.name)
                if framework is None:
                    framework = _framework_meta(strategy_dir)
                    framework_cache[strategy_dir.name] = framework
                stock_names = stock_name_cache.get(strategy_dir.name)
                if stock_names is None:
                    stock_names = _backtest_stock_names(strategy_dir)
                    stock_name_cache[strategy_dir.name] = stock_names
                _upsert(
                    connection,
                    _read_index_record(
                        strategy_dir,
                        path,
                        origin=origin,
                        framework=framework,
                        stock_names=stock_names,
                    ),
                )
                counts["indexed"] += 1
            except Exception as exc:
                counts["errors"] += 1
                logger.warning("Failed to index report %s: %s", path, exc)
                if cached:
                    connection.execute(
                        "DELETE FROM report_index WHERE report_id = ?",
                        (cached["report_id"],),
                    )

        for key, row in existing.items():
            if key not in seen:
                deleted = connection.execute(
                    "DELETE FROM report_index WHERE report_id = ? AND structured_path = ?",
                    (row["report_id"], row["structured_path"]),
                )
                counts["removed"] += max(deleted.rowcount, 0)
    return counts


def _serialize_row(row: sqlite3.Row) -> Dict[str, Any]:
    item = dict(row)
    return {
        "id": item["report_id"],
        "file_path": item["structured_path"],
        "report_path": item["report_md_path"] or None,
        "strategy": item["framework_id"],
        "framework_name": item["framework_name"],
        "framework_version": item["framework_version"],
        "ts_code": item["stock_code"],
        "stock_name": item["stock_name"],
        "cutoff_date": item["analysis_date"],
        "model": item["model"],
        "elapsed_seconds": item["elapsed_seconds"],
        "score": item["score"],
        "recommendation": item["recommendation"],
        "confidence": item["confidence"],
        "core_logic": item["core_logic"],
        "risks": item["risks"],
        "origin": item["origin"],
        "origin_run_id": item["origin_run_id"],
        "read_only": item["origin"] == "historical_backtest",
        "created_at": item["created_at"].replace("T", " "),
    }


def list_reports(
    project_root: Path = WORKSPACE_ROOT,
    db_path: Optional[Path] = None,
    qualitative_runs_root: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    sync_report_index(
        project_root,
        db_path=db_path,
        qualitative_runs_root=qualitative_runs_root,
    )
    with closing(_connect(db_path)) as connection:
        rows = connection.execute(
            "SELECT * FROM report_index ORDER BY analysis_date DESC, created_at DESC"
        ).fetchall()
    return [_serialize_row(row) for row in rows]


def _escape_like(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_reports(
    project_root: Path = WORKSPACE_ROOT,
    db_path: Optional[Path] = None,
    qualitative_runs_root: Optional[Path] = None,
    *,
    page: int = 1,
    page_size: int = 20,
    query: str = "",
    framework: str = "",
    recommendation: str = "",
    origin: str = "",
    start_date: str = "",
    end_date: str = "",
    refresh: bool = False,
) -> Dict[str, Any]:
    """Search the SQLite index and return only one report-list page."""
    if refresh:
        sync_report_index(
            project_root,
            db_path=db_path,
            qualitative_runs_root=qualitative_runs_root,
        )

    clauses: List[str] = []
    parameters: List[Any] = []
    query = str(query or "").strip()
    if query:
        pattern = f"%{_escape_like(query)}%"
        clauses.append(
            "(" + " OR ".join(
                f"COALESCE({column}, '') LIKE ? ESCAPE '\\'"
                for column in (
                    "stock_code",
                    "stock_name",
                    "framework_id",
                    "framework_name",
                    "core_logic",
                )
            ) + ")"
        )
        parameters.extend([pattern] * 5)
    if framework:
        clauses.append("framework_id = ?")
        parameters.append(framework)
    if recommendation:
        clauses.append("COALESCE(recommendation, '') LIKE ? ESCAPE '\\'")
        parameters.append(f"%{_escape_like(recommendation)}%")
    if origin:
        clauses.append("origin = ?")
        parameters.append(origin)
    if start_date:
        clauses.append("analysis_date >= ?")
        parameters.append(start_date)
    if end_date:
        clauses.append("analysis_date <= ?")
        parameters.append(end_date)

    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    page_size = max(1, min(int(page_size), 100))
    requested_page = max(1, int(page))
    with closing(_connect(db_path)) as connection:
        total = int(
            connection.execute(
                f"SELECT COUNT(*) FROM report_index{where}", parameters
            ).fetchone()[0]
        )
        index_total = int(
            connection.execute("SELECT COUNT(*) FROM report_index").fetchone()[0]
        )
        total_pages = max(1, math.ceil(total / page_size))
        effective_page = min(requested_page, total_pages)
        rows = connection.execute(
            f"SELECT * FROM report_index{where} "
            "ORDER BY analysis_date DESC, created_at DESC LIMIT ? OFFSET ?",
            [*parameters, page_size, (effective_page - 1) * page_size],
        ).fetchall()
        frameworks = connection.execute(
            "SELECT framework_id, framework_name, COUNT(*) AS report_count "
            "FROM report_index GROUP BY framework_id, framework_name "
            "ORDER BY framework_name, framework_id"
        ).fetchall()

    return {
        "items": [_serialize_row(row) for row in rows],
        "total": total,
        "index_total": index_total,
        "page": effective_page,
        "page_size": page_size,
        "pages": total_pages,
        "frameworks": [
            {
                "id": row["framework_id"],
                "name": row["framework_name"] or row["framework_id"],
                "count": int(row["report_count"]),
            }
            for row in frameworks
        ],
    }


def get_report(
    report_id: str,
    project_root: Path = WORKSPACE_ROOT,
    db_path: Optional[Path] = None,
    qualitative_runs_root: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    sync_report_index(
        project_root,
        db_path=db_path,
        qualitative_runs_root=qualitative_runs_root,
    )
    with closing(_connect(db_path)) as connection:
        row = connection.execute(
            "SELECT * FROM report_index WHERE report_id = ?", (report_id,)
        ).fetchone()
    if row is None:
        return None
    report = _serialize_row(row)
    structured_path = Path(report["file_path"])
    if not structured_path.exists():
        return None
    data = json.loads(structured_path.read_text(encoding="utf-8"))
    report_text = ""
    if report.get("report_path") and Path(report["report_path"]).exists():
        report_text = Path(report["report_path"]).read_text(encoding="utf-8")
    framework = _framework_meta(project_root / "strategies" / report["strategy"])
    return {
        **report,
        "full_data": data,
        "report_text": report_text,
        "chapter_titles": framework["chapter_titles"],
        "chapter_order": framework["chapter_order"],
    }


def load_report_source_text(
    report_id: str,
    project_root: Path = WORKSPACE_ROOT,
    db_path: Optional[Path] = None,
    qualitative_runs_root: Optional[Path] = None,
) -> str:
    """Load the complete source text for one indexed report.

    Markdown is the preferred source because it is the same complete report the
    reader shows.  Structured JSON is used as a lossless fallback when a legacy
    report has no Markdown artifact.  Existing index rows avoid a reconciliation
    pass on every assistant message; a missing row triggers one retry after sync.
    """

    def find_row() -> Optional[sqlite3.Row]:
        with closing(_connect(db_path)) as connection:
            return connection.execute(
                "SELECT report_md_path, structured_path FROM report_index "
                "WHERE report_id = ?",
                (report_id,),
            ).fetchone()

    row = find_row()
    if row is None:
        sync_report_index(
            project_root,
            db_path=db_path,
            qualitative_runs_root=qualitative_runs_root,
        )
        row = find_row()
    if row is None:
        return ""

    reports_root = (Path(project_root) / "strategies").resolve()
    for source_type, raw_path in (
        ("markdown", row["report_md_path"]),
        ("structured", row["structured_path"]),
    ):
        if not raw_path:
            continue
        path = Path(raw_path).resolve()
        if not path.is_relative_to(reports_root) or not path.is_file():
            continue
        if source_type == "markdown":
            return path.read_text(encoding="utf-8")
        data = json.loads(path.read_text(encoding="utf-8"))
        return json.dumps(data, ensure_ascii=False, indent=2)
    return ""


def delete_report(
    report_id: str,
    project_root: Path = WORKSPACE_ROOT,
    db_path: Optional[Path] = None,
) -> bool:
    with _INDEX_LOCK, closing(_connect(db_path)) as connection, connection:
        row = connection.execute(
            "SELECT * FROM report_index WHERE report_id = ?", (report_id,)
        ).fetchone()
        if row is None:
            return False
        if row["origin"] == "historical_backtest":
            return False
        reports_root = (Path(project_root) / "strategies").resolve()
        targets = [Path(row["structured_path"])]
        if row["report_md_path"]:
            targets.append(Path(row["report_md_path"]))
        try:
            for path in targets:
                resolved = path.resolve()
                if not resolved.is_relative_to(reports_root):
                    raise ValueError(f"报告路径超出策略目录: {resolved}")
                resolved.unlink(missing_ok=True)
            connection.execute(
                "DELETE FROM report_index WHERE report_id = ?", (report_id,)
            )
            return True
        except Exception as exc:
            logger.error("Failed to delete report %s: %s", report_id, exc)
            return False
