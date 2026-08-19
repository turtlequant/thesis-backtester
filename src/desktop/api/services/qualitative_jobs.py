"""Persistent batch jobs for the structured-research workspace.

The product composes existing numerical screening strategies and qualitative
frameworks only for the duration of a run.  Neither side owns or mutates the
other.  Latest judgement and historical validation share the same analysis
contract, persistence, retry and pause boundaries.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import yaml

from src.data.settings import DATA_ROOT, STRATEGIES_ROOT
from src.desktop.runtime import DESKTOP_CONFIG_PATH
from src.engine.config import StrategyConfig
from src.engine.framework_validation import (
    audit_framework_definition,
    audit_synthesis_definition,
)

from . import screening_strategies


QUALITATIVE_RUNS_ROOT = DATA_ROOT / "qualitative_runs"
FRAMEWORKS_ROOT = STRATEGIES_ROOT
CURRENT_ONLY_DATA = {"news", "fund_flow", "industry_overview"}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _stable_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def screening_identity(strategy: Dict[str, Any]) -> str:
    """Internal identity of the final numerical definition (not a UI version)."""
    return _stable_hash(screening_strategies.normalize_definition(strategy["definition"]))


def _current_only_details(operator: Any) -> tuple[List[str], bool]:
    fields = sorted(CURRENT_ONLY_DATA.intersection(operator.data_needed))
    marker_hit = bool(re.search(r"query_market_context\s*\(", operator.content))
    return fields, marker_hit


def _operator_output_contract(operator: Any) -> List[tuple[str, str]]:
    return [(item.field, item.type) for item in operator.outputs]


def framework_snapshot(framework_id: str) -> Dict[str, Any]:
    """Return a framework summary plus a content identity and history blockers."""
    yaml_path = FRAMEWORKS_ROOT / framework_id / "strategy.yaml"
    if not yaml_path.exists():
        raise KeyError(framework_id)
    config = StrategyConfig.from_yaml(yaml_path)
    registry = config.get_operator_registry()
    chapters = []
    operator_payload = []
    operator_catalog: Dict[str, Dict[str, Any]] = {}
    unsafe = []
    adaptations = []
    seen_adaptations = set()
    seen_unsafe = set()

    integrity = audit_framework_definition(config.get_chapter_defs(), registry)
    integrity.extend(
        audit_synthesis_definition(
            config.get_synthesis_config(),
            config.get_synthesis_fields(),
            config.get_chapter_defs(),
        )
    )

    for chapter in config.get_chapter_defs():
        ids = list(chapter.get("operators", []))
        chapters.append(
            {
                "id": chapter["id"],
                "chapter": chapter.get("chapter", 0),
                "title": chapter.get("title", ""),
                "operators": ids,
                "dependencies": list(chapter.get("dependencies", [])),
            }
        )
        for operator_id in ids:
            operator = registry.get(operator_id)
            if operator is None:
                operator_payload.append({"id": operator_id, "missing": True})
                operator_catalog[operator_id] = {
                    "id": operator_id,
                    "name": operator_id,
                    "data_needed": [],
                    "gate": False,
                    "missing": True,
                }
                continue
            operator_payload.append(
                {
                    "id": operator.id,
                    "data_needed": operator.data_needed,
                    "gate": operator.gate,
                    "history_variant": operator.history_variant,
                    "outputs": [vars(item) for item in operator.outputs],
                    "content": operator.content,
                }
            )
            operator_catalog[operator_id] = {
                "id": operator.id,
                "name": operator.name,
                "data_needed": list(operator.data_needed),
                "gate": bool(operator.gate),
                "gate_config": operator.gate,
                "outputs": [vars(item) for item in operator.outputs],
                "missing": False,
                "history_variant": operator.history_variant,
            }
            current_fields, marker_hit = _current_only_details(operator)
            if (current_fields or marker_hit) and operator.id not in seen_unsafe:
                history_operator = (
                    registry.get(operator.history_variant) if operator.history_variant else None
                )
                history_fields, history_marker = (
                    _current_only_details(history_operator)
                    if history_operator is not None
                    else ([], False)
                )
                contract_matches = (
                    history_operator is not None
                    and _operator_output_contract(history_operator)
                    == _operator_output_contract(operator)
                )
                if (
                    history_operator is not None
                    and not history_fields
                    and not history_marker
                    and contract_matches
                ):
                    adaptation = {
                        "source_id": operator.id,
                        "source_name": operator.name,
                        "history_id": history_operator.id,
                        "history_name": history_operator.name,
                    }
                    if operator.id not in seen_adaptations:
                        adaptations.append(adaptation)
                        seen_adaptations.add(operator.id)
                    operator_catalog[operator_id].update(
                        history_adapted=True,
                        history_variant_name=history_operator.name,
                    )
                    operator_payload[-1]["history_variant_payload"] = {
                        "id": history_operator.id,
                        "data_needed": history_operator.data_needed,
                        "outputs": [vars(item) for item in history_operator.outputs],
                        "content": history_operator.content,
                    }
                    continue
                if history_operator is not None and not contract_matches:
                    reason = "历史适配算子的输出字段或类型与原算子不一致"
                    kind = "invalid_history_adapter"
                else:
                    reason = (
                        f"依赖仅当前时点可用的数据：{', '.join(current_fields)}"
                        if current_fields
                        else "正文要求调用仅实时分析可用的市场上下文"
                    )
                    kind = "current_only_data" if current_fields else "current_only_context"
                unsafe.append(
                    {
                        "id": operator.id,
                        "name": operator.name,
                        "kind": kind,
                        "data_needed": current_fields,
                        "reason": reason,
                        "remediation": "为该算子声明具备相同输出契约的 history_variant",
                    }
                )
                seen_unsafe.add(operator.id)

    snapshot = {
        "id": framework_id,
        "name": config.name,
        "version": config.version,
        "chapter_count": len(chapters),
        "operator_count": sum(len(item["operators"]) for item in chapters),
        "operators_dir": config.get_operators_dir() or "operators/v2",
        "analyst_role": config.get_analyst_role(),
        "chapters": chapters,
        "operator_catalog": operator_catalog,
        "synthesis": config.get_synthesis_config(),
        "synthesis_fields": config.get_synthesis_fields(),
        "integrity_blockers": integrity,
        "history_adaptations": adaptations,
        "history_blockers": unsafe,
    }
    snapshot["identity"] = _stable_hash(
        {
            "raw": config.raw,
            "chapters": chapters,
            "operators": operator_payload,
        }
    )
    return snapshot


def normalize_synthesis(
    result: Dict[str, Any],
    decision_thresholds: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Normalize framework-specific synthesis keys to one batch result contract."""
    synthesis = result.get("synthesis", {}) or {}

    def first(*keys: str, default: Any = "") -> Any:
        for key in keys:
            value = synthesis.get(key)
            if value not in (None, "", [], {}):
                return value
        return default

    raw_score = first("综合评分", "总体评分", "score", "overall_score", default=None)
    score = None
    if isinstance(raw_score, (int, float)):
        score = float(raw_score)
    elif raw_score is not None:
        match = re.search(r"-?\d+(?:\.\d+)?", str(raw_score))
        if match:
            score = float(match.group())

    recommendation = str(first("最终建议", "投资建议", "recommendation", default=""))
    positive = any(word in recommendation for word in ("买入", "建仓", "值得深入"))
    avoid = any(word in recommendation for word in ("回避", "跳过", "卖出"))
    label_bucket = "positive" if positive else ("avoid" if avoid else "watch")
    thresholds = decision_thresholds or {}
    buy_threshold = float(thresholds.get("buy", 70))
    avoid_threshold = float(thresholds.get("avoid", 29))
    score_bucket = None
    if score is not None:
        score_bucket = "positive" if score >= buy_threshold else ("avoid" if score <= avoid_threshold else "watch")
    bucket = score_bucket or label_bucket
    warnings = []
    if score_bucket is not None and score_bucket != label_bucket:
        warnings.append("评分与最终建议不符合框架决策边界，批量分组已按评分阈值处理")
    risks = first("关键风险", "风险提示", "主要风险", "risks", default=[])
    if isinstance(risks, str):
        risk_text = risks
    else:
        risk_text = "；".join(str(item) for item in risks) if isinstance(risks, list) else str(risks or "")

    return {
        "score": score,
        "recommendation": recommendation,
        "recommendation_bucket": bucket,
        "recommendation_label_bucket": label_bucket,
        "core_logic": str(
            first(
                "核心逻辑",
                "一句话买入逻辑（强制）",
                "一句话买入逻辑",
                "buy_logic",
                default="",
            )
        ),
        "risks": risk_text,
        "confidence": str(first("信心水平", "置信度", "confidence", default="")),
        "contract_complete": score is not None and bool(recommendation) and not warnings,
        "contract_warnings": warnings,
        "synthesis_fields": copy.deepcopy(synthesis),
    }


def build_composed_config(
    framework_id: str,
    screening_strategy: Dict[str, Any],
    *,
    start_date: str,
    end_date: str,
    interval: str,
    top_n: int,
    concurrency: int,
    run_dir: Path,
) -> StrategyConfig:
    """Compose independent framework and screening inputs for one historical run."""
    yaml_path = FRAMEWORKS_ROOT / framework_id / "strategy.yaml"
    framework = StrategyConfig.from_yaml(yaml_path)
    runtime_path = Path(run_dir) / "runtime_strategy.yaml"
    if runtime_path.exists():
        raw = yaml.safe_load(runtime_path.read_text(encoding="utf-8")) or {}
        return StrategyConfig(
            name=str(raw.get("meta", {}).get("name") or framework.name),
            version=str(raw.get("meta", {}).get("version") or framework.version),
            yaml_path=yaml_path,
            raw=raw,
        )

    raw = copy.deepcopy(framework.raw)
    registry = framework.get_operator_registry()
    chapters = copy.deepcopy(framework.get_chapter_defs())
    applied_adaptations = []
    for chapter in chapters:
        resolved = []
        for operator_id in chapter.get("operators", []):
            operator = registry.get(operator_id)
            if operator is None:
                raise ValueError(f"框架引用了不存在的算子: {operator_id}")
            current_fields, marker_hit = _current_only_details(operator)
            if not current_fields and not marker_hit:
                resolved.append(operator_id)
                continue
            history_operator = (
                registry.get(operator.history_variant) if operator.history_variant else None
            )
            if history_operator is None:
                raise ValueError(f"算子缺少严格历史适配: {operator_id}")
            history_fields, history_marker = _current_only_details(history_operator)
            if history_fields or history_marker:
                raise ValueError(f"算子的历史适配仍依赖当前时点数据: {operator_id}")
            if _operator_output_contract(history_operator) != _operator_output_contract(operator):
                raise ValueError(f"算子的历史适配输出契约不一致: {operator_id}")
            resolved.append(history_operator.id)
            applied_adaptations.append(
                {
                    "chapter_id": chapter.get("id"),
                    "source_id": operator.id,
                    "history_id": history_operator.id,
                }
            )
        chapter["operators"] = resolved
    raw.setdefault("framework", {})["chapters"] = chapters
    raw.setdefault("paths", {})["chapters"] = "__runtime_inline_chapters__.yaml"
    raw["screening"] = screening_strategies.to_engine_screening(
        screening_strategy["definition"]
    )
    raw["screening"]["agent_batch"] = {"ratio": 1.0, "max": int(top_n)}
    raw["backtest"] = {
        "start_date": start_date,
        "end_date": end_date,
        "cross_section_interval": interval,
        "top_n": int(top_n),
        "agent_concurrency": int(concurrency),
        "forward_periods": [
            {"months": 1, "label": "1个月"},
            {"months": 3, "label": "3个月"},
            {"months": 6, "label": "6个月"},
            {"months": 12, "label": "12个月"},
        ],
    }
    raw.setdefault("paths", {})["backtest_dir"] = str(run_dir.resolve())
    raw["runtime"] = {
        "mode": "strict_history",
        "source_framework_id": framework_id,
        "history_adaptations": applied_adaptations,
    }
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.write_text(
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return StrategyConfig(
        name=framework.name,
        version=framework.version,
        yaml_path=yaml_path,
        raw=raw,
    )


def _apply_llm_settings() -> None:
    if not DESKTOP_CONFIG_PATH.exists():
        return
    try:
        settings = json.loads(DESKTOP_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    mapping = {
        "llm_api_key": "LLM_API_KEY",
        "llm_base_url": "LLM_BASE_URL",
        "llm_model": "LLM_MODEL",
        "temperature": "LLM_TEMPERATURE",
        "max_tokens": "LLM_MAX_TOKENS",
    }
    for key, environment_key in mapping.items():
        value = settings.get(key)
        if value not in (None, ""):
            os.environ[environment_key] = str(value)


class QualitativeJobManager:
    """One observable, resumable structured-research batch at a time."""

    def __init__(self, root: Path = QUALITATIVE_RUNS_ROOT):
        self.root = Path(root)
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._active_id: Optional[str] = None
        self._pause_events: Dict[str, threading.Event] = {}

    def start(self, kind: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if kind not in {"latest_judgement", "framework_validation"}:
            raise ValueError(f"未知结构化投研任务: {kind}")
        with self._lock:
            self._assert_idle()
            job_id = uuid.uuid4().hex[:16]
            job = {
                "id": job_id,
                "kind": kind,
                "status": "queued",
                "stage": "queued",
                "message": "等待执行",
                "params": copy.deepcopy(params),
                "progress": {"total": 0, "completed": 0, "failed": 0},
                "rows": [],
                "created_at": _now(),
                "started_at": None,
                "finished_at": None,
                "error": None,
                "result": None,
            }
            self._jobs[job_id] = job
            self._active_id = job_id
            self._pause_events[job_id] = threading.Event()
            self._persist(job)
        self._launch(job_id)
        return self.get_job(job_id)

    def _assert_idle(self) -> None:
        if not self._active_id:
            return
        active = self._jobs.get(self._active_id)
        if active and active.get("status") in {"queued", "running", "pause_requested"}:
            raise ValueError("已有结构化投研批量任务正在执行")

    def _launch(self, job_id: str) -> None:
        threading.Thread(
            target=self._run,
            args=(job_id,),
            name=f"qualitative-{job_id[:6]}",
            daemon=True,
        ).start()

    def _run(self, job_id: str) -> None:
        try:
            _apply_llm_settings()
            job = self.get_job(job_id)
            self._update(
                job_id,
                status="running",
                started_at=job.get("started_at") or _now(),
                error=None,
            )
            if job["kind"] == "latest_judgement":
                self._run_latest(job_id)
            else:
                self._run_validation(job_id)
        except Exception as exc:
            self._update(
                job_id,
                status="failed",
                stage="failed",
                message="任务失败",
                error=str(exc)[:4000],
                finished_at=_now(),
            )
        finally:
            with self._lock:
                current = self._jobs.get(job_id, {})
                if self._active_id == job_id and current.get("status") not in {
                    "queued",
                    "running",
                    "pause_requested",
                }:
                    self._active_id = None

    def _run_latest(self, job_id: str) -> None:
        from src.screener.quick_filter import screen_at_date

        job = self.get_job(job_id)
        params = job["params"]
        run_dir = self.root / job_id
        screening_strategy = params["screening_strategy_snapshot"]
        self._update(job_id, stage="screening", message="正在生成最新截面候选")
        config = screening_strategies.build_config(
            screening_strategy,
            start_date=params["cutoff_date"],
            end_date=params["cutoff_date"],
            interval="1m",
            top_n=int(params["top_n"]),
            run_dir=run_dir,
        )
        screened = screen_at_date(params["cutoff_date"], config, int(params["top_n"]))
        candidates = screened.candidates.head(int(params["top_n"])).copy()
        candidates.to_csv(run_dir / "candidates.csv", index=False, encoding="utf-8-sig")
        rows = asyncio.run(
            self._analyze_candidates(
                job_id,
                candidates,
                screened.effective_date,
                params["framework_id"],
                int(params["concurrency"]),
                blind_mode=False,
                report_root=FRAMEWORKS_ROOT / params["framework_id"] / "live",
            )
        )
        if self._finish_if_paused(job_id):
            return
        rows.sort(key=lambda item: item.get("score") if item.get("score") is not None else -1, reverse=True)
        recommendation_counts: Dict[str, int] = {}
        for row in rows:
            label = row.get("recommendation") or "未形成建议"
            recommendation_counts[label] = recommendation_counts.get(label, 0) + 1
        completed = sum(1 for row in rows if row.get("status") == "completed")
        self._update(
            job_id,
            status="completed",
            stage="completed",
            message="最新批量研判完成",
            rows=rows,
            result={
                "requested_date": params["cutoff_date"],
                "effective_date": screened.effective_date,
                "universe": screened.total_stocks,
                "after_filters": screened.after_basic_filter,
                "selected": len(candidates),
                "completed": completed,
                "failed": len(rows) - completed,
                "recommendation_counts": recommendation_counts,
            },
            finished_at=_now(),
        )

    def _run_validation(self, job_id: str) -> None:
        from src.backtest.pipeline import (
            load_screen_csv,
            step_eval,
            step_screen,
        )

        job = self.get_job(job_id)
        params = job["params"]
        run_dir = self.root / job_id
        config = build_composed_config(
            params["framework_id"],
            params["screening_strategy_snapshot"],
            start_date=params["start_date"],
            end_date=params["end_date"],
            interval=params["interval"],
            top_n=int(params["top_n"]),
            concurrency=int(params["concurrency"]),
            run_dir=run_dir,
        )
        self._update(job_id, stage="screening", message="正在生成严格历史截面")
        dates = step_screen(config)
        screen_dir = run_dir / "screen_results"
        frames = []
        for cutoff_date in dates:
            frame = load_screen_csv(cutoff_date, screen_dir)
            if frame is None or frame.empty:
                continue
            selected = frame.head(int(params["top_n"])).copy()
            selected["_cutoff_date"] = cutoff_date
            frames.append(selected)
        candidates = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        analysis_rows = asyncio.run(
            self._analyze_candidates(
                job_id,
                candidates,
                "",
                params["framework_id"],
                int(params["concurrency"]),
                blind_mode=True,
                report_root=run_dir / "agent_reports",
                config=config,
            )
        )
        if self._finish_if_paused(job_id):
            return
        if candidates.empty:
            raise RuntimeError("历史筛选没有产生候选，无法验证研究框架")
        completed = sum(1 for row in analysis_rows if row.get("status") == "completed")
        failed = len(analysis_rows) - completed
        if completed == 0:
            raise RuntimeError("历史截面分析全部失败，未生成可用于评估的框架结论")
        self._update(job_id, stage="evaluation", message="正在采集前瞻收益并评估框架")
        report_path = step_eval(config, numeric_only=False)
        summaries = sorted(run_dir.glob("backtest_summary_*.json"))
        if not summaries:
            raise RuntimeError("框架验证完成，但没有生成结构化结果")
        summary_path = summaries[-1]
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        self._update(
            job_id,
            status="completed",
            stage="completed",
            message="框架历史验证完成",
            result={
                "outcome_schema_version": summary.get("outcome_schema_version", 1),
                "evaluation_semantics": summary.get("evaluation_semantics", "legacy"),
                "dates": summary.get("dates", dates),
                "interval": summary.get("interval", params["interval"]),
                "slices": summary.get("slices", []),
                "performance": summary.get("performance", {}),
                "analysis_total": len(analysis_rows),
                "analysis_completed": completed,
                "analysis_failed": failed,
                "report_path": str(report_path),
                "summary_path": str(summary_path),
            },
            finished_at=_now(),
        )

    async def _analyze_candidates(
        self,
        job_id: str,
        candidates: pd.DataFrame,
        default_cutoff_date: str,
        framework_id: str,
        concurrency: int,
        *,
        blind_mode: bool,
        report_root: Path,
        config: Optional[StrategyConfig] = None,
    ) -> List[Dict[str, Any]]:
        from src.agent.runtime import run_blind_analysis
        from src.data.config import get_active_provider_name
        from src.data.snapshot import create_snapshot
        from src.desktop.api.services.data_service import create_snapshot_for_analysis

        if config is None:
            config = StrategyConfig.from_yaml(FRAMEWORKS_ROOT / framework_id / "strategy.yaml")
        report_root.mkdir(parents=True, exist_ok=True)
        records = candidates.to_dict(orient="records") if not candidates.empty else []
        existing_rows = {
            (row.get("ts_code"), row.get("cutoff_date")): row
            for row in self.get_job(job_id).get("rows", [])
            if row.get("status") == "completed"
        }
        total = len(records)
        self._update(
            job_id,
            stage="analysis",
            message="正在按固定章节 DAG 批量分析",
            progress={"total": total, "completed": len(existing_rows), "failed": 0},
        )

        async def analyze_one(record: Dict[str, Any]) -> Dict[str, Any]:
            ts_code = str(record.get("ts_code", ""))
            cutoff_date = str(record.get("_cutoff_date") or default_cutoff_date)
            key = (ts_code, cutoff_date)
            if key in existing_rows:
                return existing_rows[key]
            if blind_mode:
                output_dir = report_root
            else:
                output_dir = report_root / f"{ts_code}_{cutoff_date}"
            structured_path = output_dir / f"{ts_code}_{cutoff_date}_structured.json"
            try:
                if structured_path.exists():
                    result = json.loads(structured_path.read_text(encoding="utf-8"))
                else:
                    snapshot = None
                    actual_cutoff = cutoff_date
                    if not blind_mode:
                        if get_active_provider_name() == "akshare":
                            snapshot, valid, errors, _ = await asyncio.to_thread(
                                create_snapshot_for_analysis,
                                ts_code,
                                str(FRAMEWORKS_ROOT / framework_id / "strategy.yaml"),
                            )
                            if not valid:
                                raise RuntimeError("；".join(errors))
                            actual_cutoff = snapshot.cutoff_date
                        else:
                            snapshot = await asyncio.to_thread(create_snapshot, ts_code, cutoff_date)
                    result = await run_blind_analysis(
                        ts_code=ts_code,
                        cutoff_date=actual_cutoff,
                        config=config,
                        blind_mode=blind_mode,
                        output_dir=output_dir,
                        snapshot=snapshot,
                    )
                normalized = normalize_synthesis(result, config.get_decision_thresholds())
                return {
                    "ts_code": ts_code,
                    "stock_name": str(record.get("stock_name", "")),
                    "industry": str(record.get("industry", "")),
                    "cutoff_date": cutoff_date,
                    "status": "completed",
                    "report_path": str(structured_path),
                    **normalized,
                }
            except Exception as exc:
                return {
                    "ts_code": ts_code,
                    "stock_name": str(record.get("stock_name", "")),
                    "industry": str(record.get("industry", "")),
                    "cutoff_date": cutoff_date,
                    "status": "failed",
                    "error": str(exc)[:1000],
                    "score": None,
                    "recommendation": "",
                    "recommendation_bucket": "",
                    "recommendation_label_bucket": "",
                    "core_logic": "",
                    "risks": "",
                    "confidence": "",
                    "contract_complete": False,
                    "contract_warnings": [],
                    "synthesis_fields": {},
                }

        rows_by_key = dict(existing_rows)
        pending = [
            record
            for record in records
            if (
                str(record.get("ts_code", "")),
                str(record.get("_cutoff_date") or default_cutoff_date),
            )
            not in rows_by_key
        ]
        chunk_size = max(1, min(int(concurrency), 10))
        for offset in range(0, len(pending), chunk_size):
            if self._pause_events[job_id].is_set():
                break
            chunk = pending[offset : offset + chunk_size]
            chunk_rows = await asyncio.gather(*(analyze_one(item) for item in chunk))
            for row in chunk_rows:
                rows_by_key[(row["ts_code"], row["cutoff_date"])] = row
            rows = list(rows_by_key.values())
            completed = sum(1 for row in rows if row["status"] == "completed")
            failed = sum(1 for row in rows if row["status"] == "failed")
            self._update(
                job_id,
                rows=rows,
                progress={"total": total, "completed": completed, "failed": failed},
                message=f"已完成 {completed + failed}/{total}，成功 {completed}，失败 {failed}",
            )
        return list(rows_by_key.values())

    def _finish_if_paused(self, job_id: str) -> bool:
        if not self._pause_events[job_id].is_set():
            return False
        self._update(
            job_id,
            status="paused",
            stage="paused",
            message="已暂停，可继续补齐未完成分析",
        )
        return True

    def pause(self, job_id: str) -> Dict[str, Any]:
        job = self.get_job(job_id)
        if job.get("status") not in {"queued", "running", "pause_requested"}:
            raise ValueError("当前任务不在运行中")
        event = self._pause_events.setdefault(job_id, threading.Event())
        event.set()
        self._update(job_id, status="pause_requested", message="将在当前并发批次结束后暂停")
        return self.get_job(job_id)

    def resume(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            self._assert_idle()
            job = self.get_job(job_id)
            if job.get("status") not in {"paused", "failed", "interrupted"}:
                raise ValueError("当前任务不能继续")
            self._pause_events[job_id] = threading.Event()
            self._active_id = job_id
            self._update(
                job_id,
                status="queued",
                stage="queued",
                message="等待继续执行",
                error=None,
                finished_at=None,
            )
        self._launch(job_id)
        return self.get_job(job_id)

    def _persist(self, job: Dict[str, Any]) -> None:
        run_dir = self.root / str(job["id"])
        run_dir.mkdir(parents=True, exist_ok=True)
        target = run_dir / "run.json"
        temporary = run_dir / "run.json.tmp"
        temporary.write_text(
            json.dumps(job, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        temporary.replace(target)

    def _update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.update(fields)
            self._persist(job)

    def get_job(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            if job_id in self._jobs:
                return copy.deepcopy(self._jobs[job_id])
        path = self.root / job_id / "run.json"
        if not path.exists():
            raise KeyError(job_id)
        job = json.loads(path.read_text(encoding="utf-8"))
        with self._lock:
            self._jobs[job_id] = job
        return copy.deepcopy(job)

    def list_jobs(self, kind: str, limit: int = 20) -> List[Dict[str, Any]]:
        jobs: Dict[str, Dict[str, Any]] = {}
        if self.root.exists():
            paths = sorted(
                self.root.glob("*/run.json"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            for path in paths[: max(limit * 2, 20)]:
                try:
                    item = json.loads(path.read_text(encoding="utf-8"))
                    if item.get("status") in {"queued", "running", "pause_requested"} and str(item.get("id")) not in self._jobs:
                        item.update(
                            status="interrupted",
                            stage="interrupted",
                            message="应用退出时任务尚未完成，可继续执行",
                        )
                        self._persist(item)
                    jobs[str(item["id"])] = item
                except (OSError, ValueError, KeyError):
                    continue
        with self._lock:
            for item in self._jobs.values():
                jobs[str(item["id"])] = copy.deepcopy(item)
        selected = [item for item in jobs.values() if item.get("kind") == kind]
        selected.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
        return selected[: max(1, min(int(limit), 100))]

    def shutdown(self) -> None:
        for event in self._pause_events.values():
            event.set()


qualitative_job_manager = QualitativeJobManager()
