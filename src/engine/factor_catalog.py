"""Unified catalog for native fields and derived factor definitions."""
from __future__ import annotations

import ast
import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from src.data.config import get_active_provider_name, get_provider_db_path
from src.data.field_catalog import SourceField, SourceFieldCatalog
from src.data.settings import FACTORS_ROOT
from src.engine.factor_dsl import FactorDslError, compile_expression


FACTOR_DEFINITIONS_DIR = FACTORS_ROOT
_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_CATEGORY_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
_FACTOR_TYPES = {"cross_section"}
_DIRECTIONS = {"higher_better", "lower_better", "neutral"}
_NULL_POLICIES = {"propagate"}
_POINT_IN_TIME_POLICIES = {"strict", "latest_only"}
_CATEGORY_LABELS = {
    "valuation": "估值",
    "size": "规模",
    "dividend": "分红",
    "quality": "质量",
    "growth": "成长",
    "solvency": "偿债",
    "technical": "技术",
    "other": "其他",
}
_CATEGORY_IDS = {label: category for category, label in _CATEGORY_LABELS.items()}


@dataclass(frozen=True)
class FactorDefinition:
    id: str
    name: str
    description: str
    category: str
    tags: Tuple[str, ...]
    factor_type: str
    grain: str
    engine: str
    inputs: Dict[str, str]
    input_columns: Dict[str, str]
    optional_inputs: Tuple[str, ...]
    expression: str
    output_dtype: str
    unit: str
    direction: str
    null_policy: str
    point_in_time_safe: bool
    enabled: bool
    source_path: Path
    source_kind: str = "dsl"
    data_needed: Tuple[str, ...] = ()
    definition_hash: str = ""
    execution_mode: str = "row"
    temporal_frequency: str = "annual"

    @property
    def editable(self) -> bool:
        return self.source_kind == "dsl"


@dataclass
class ProviderSnapshot:
    provider: str
    database_path: Path
    datasets: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    columns: Dict[str, set] = field(default_factory=dict)
    factor_materializations: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    ingestion_checkpoints: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def has_field(self, dataset: str, column: str) -> bool:
        return column in self.columns.get(dataset, set())


def _canonical_hash(payload: Dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _category_for_legacy(factor_id: str) -> str:
    if "dividend" in factor_id:
        return "dividend"
    if "growth" in factor_id:
        return "growth"
    if factor_id in {"current_ratio", "debt_to_assets", "interest_debt_ratio"}:
        return "solvency"
    if any(token in factor_id for token in ("roe", "margin", "ocf", "roic", "fcf")):
        return "quality"
    if factor_id in {"bp", "ep", "ps_ttm"}:
        return "valuation"
    if "mv" in factor_id or "cap" in factor_id:
        return "size"
    return "other"


def _read_literal_meta(path: Path) -> Optional[Dict[str, Any]]:
    """Read a module-level META literal without executing factor code."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "META" for target in node.targets):
            continue
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, SyntaxError):
            return None
        return value if isinstance(value, dict) else None
    return None


def _validate_definition_payload(
    payload: Dict[str, Any],
    source_fields: SourceFieldCatalog,
) -> Dict[str, Any]:
    normalized = dict(payload)
    factor_id = str(normalized.get("id", "")).strip()
    category = str(normalized.get("category", "other")).strip()
    if not _ID_RE.fullmatch(factor_id):
        raise ValueError("因子 ID 只能使用小写字母、数字和下划线，且必须以字母开头")
    if not _CATEGORY_RE.fullmatch(category):
        raise ValueError("分类只能使用小写字母、数字、下划线和连字符")
    if not str(normalized.get("name", "")).strip():
        raise ValueError("因子名称不能为空")

    factor_type = str(normalized.get("type", "cross_section"))
    if factor_type not in _FACTOR_TYPES:
        raise ValueError(f"不支持的因子类型: {factor_type}")
    if str(normalized.get("engine", "polars")) != "polars":
        raise ValueError("DSL 因子当前只支持 Polars 执行引擎")

    inputs = normalized.get("inputs") or {}
    if not isinstance(inputs, dict) or not inputs:
        raise ValueError("因子至少需要一个输入字段")
    input_columns: Dict[str, str] = {}
    for alias, semantic_id in inputs.items():
        alias = str(alias)
        if not _ID_RE.fullmatch(alias):
            raise ValueError(f"输入别名无效: {alias}")
        source = source_fields.get(str(semantic_id))
        if source is None:
            raise ValueError(f"未知语义字段: {semantic_id}")
        input_columns[alias] = source.column

    input_grains = {
        source_fields.require(str(semantic_id)).grain for semantic_id in inputs.values()
    }
    has_report_inputs = any(grain == "security_report" for grain in input_grains)
    has_daily_inputs = any(grain == "security_date" for grain in input_grains)
    if has_report_inputs and has_daily_inputs:
        raise ValueError("当前 DSL 暂不支持在同一因子中混合每日字段和财报字段")
    inferred_execution_mode = "point_in_time" if has_report_inputs else "row"
    execution = normalized.get("execution") or {}
    if not isinstance(execution, dict):
        raise ValueError("execution 必须是对象")
    execution_mode = str(execution.get("mode", inferred_execution_mode))
    if execution_mode != inferred_execution_mode:
        raise ValueError("execution.mode 与输入字段粒度不一致")
    temporal_frequency = str(execution.get("frequency", "annual"))
    if execution_mode == "point_in_time" and temporal_frequency != "annual":
        raise ValueError("财报时点 DSL 当前只支持 annual 频率")

    raw_optional_inputs = normalized.get("optional_inputs") or []
    if not isinstance(raw_optional_inputs, list):
        raise ValueError("optional_inputs 必须是输入别名列表")
    optional_inputs = [str(alias) for alias in raw_optional_inputs]
    unknown_optional = sorted(set(optional_inputs) - set(inputs))
    if unknown_optional:
        raise ValueError(f"可选输入未在 inputs 中声明: {', '.join(unknown_optional)}")

    output = normalized.get("output") or {}
    if not isinstance(output, dict):
        raise ValueError("output 必须是对象")
    direction = str(output.get("direction", "neutral"))
    if direction not in _DIRECTIONS:
        raise ValueError(f"不支持的因子方向: {direction}")
    expression = str(normalized.get("expression", "")).strip()
    if not expression:
        raise ValueError("因子表达式不能为空")
    output_dtype = str(output.get("dtype", "float64"))
    compile_expression(
        expression,
        input_columns,
        output_dtype=output_dtype,
        window_by=("ts_code",) if execution_mode == "point_in_time" else None,
    )

    policies = normalized.get("policies") or {}
    if not isinstance(policies, dict):
        raise ValueError("policies 必须是对象")
    null_policy = str(policies.get("null", "propagate"))
    if null_policy not in _NULL_POLICIES:
        raise ValueError(f"当前执行器不支持空值策略: {null_policy}")
    point_in_time = str(policies.get("point_in_time", "strict"))
    if point_in_time not in _POINT_IN_TIME_POLICIES:
        raise ValueError(f"不支持的时点策略: {point_in_time}")
    normalized.update(
        {
            "schema_version": 1,
            "id": factor_id,
            "name": str(normalized["name"]).strip(),
            "description": str(normalized.get("description", "")).strip(),
            "category": category,
            "tags": [str(tag).strip() for tag in normalized.get("tags", []) if str(tag).strip()],
            "type": factor_type,
            "grain": str(normalized.get("grain", "security_date")),
            "engine": "polars",
            "inputs": {str(alias): str(value) for alias, value in inputs.items()},
            "optional_inputs": optional_inputs,
            "expression": expression,
            "execution": {
                "mode": execution_mode,
                "frequency": temporal_frequency,
            },
            "output": {
                "dtype": output_dtype,
                "unit": str(output.get("unit", "")),
                "direction": direction,
            },
            "policies": {
                "null": null_policy,
                "point_in_time": point_in_time,
                "enabled": bool(policies.get("enabled", True)),
            },
        }
    )
    return normalized


def load_factor_definition(
    path: Path,
    source_fields: SourceFieldCatalog,
) -> FactorDefinition:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if int(payload.get("schema_version", 1)) != 1:
        raise ValueError(f"不支持的因子定义版本: {path}")
    payload = _validate_definition_payload(payload, source_fields)
    input_columns = {
        alias: source_fields.require(semantic_id).column
        for alias, semantic_id in payload["inputs"].items()
    }
    output = payload["output"]
    policies = payload["policies"]
    return FactorDefinition(
        id=payload["id"],
        name=payload["name"],
        description=payload["description"],
        category=payload["category"],
        tags=tuple(payload["tags"]),
        factor_type=payload["type"],
        grain=payload["grain"],
        engine="polars",
        inputs=dict(payload["inputs"]),
        input_columns=input_columns,
        optional_inputs=tuple(payload["optional_inputs"]),
        expression=payload["expression"],
        output_dtype=output["dtype"],
        unit=output["unit"],
        direction=output["direction"],
        null_policy=policies["null"],
        point_in_time_safe=policies["point_in_time"] == "strict",
        enabled=bool(policies["enabled"]),
        source_path=path,
        source_kind="dsl",
        definition_hash=_canonical_hash(payload),
        execution_mode=payload["execution"]["mode"],
        temporal_frequency=payload["execution"]["frequency"],
    )


def validate_factor_definition(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and normalize one user-authored DSL definition without writing it."""
    fields = SourceFieldCatalog()
    normalized = _validate_definition_payload(payload, fields)
    return {
        "valid": True,
        "definition": normalized,
        "definition_hash": _canonical_hash(normalized),
        "resolved_inputs": {
            alias: {
                "semantic_id": semantic_id,
                "column": fields.require(semantic_id).column,
            }
            for alias, semantic_id in normalized["inputs"].items()
        },
    }


def load_dsl_definitions(
    directory: Optional[Path] = None,
    source_fields: Optional[SourceFieldCatalog] = None,
) -> Tuple[List[FactorDefinition], List[Dict[str, str]]]:
    root = Path(directory or FACTOR_DEFINITIONS_DIR)
    fields = source_fields or SourceFieldCatalog()
    definitions: List[FactorDefinition] = []
    errors: List[Dict[str, str]] = []
    if not root.exists():
        return definitions, errors
    for path in sorted(root.rglob("*.factor.yaml")):
        try:
            definitions.append(load_factor_definition(path, fields))
        except (OSError, ValueError, yaml.YAMLError, FactorDslError) as exc:
            errors.append({"path": str(path), "error": str(exc)})
    return definitions, errors


def _inspect_provider(provider: str, database_path: Optional[Path] = None) -> ProviderSnapshot:
    path = Path(database_path or get_provider_db_path(provider))
    snapshot = ProviderSnapshot(provider=provider, database_path=path)
    if not path.exists():
        return snapshot
    uri = f"file:{path.as_posix()}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=2.0) as connection:
            rows = connection.execute(
                "SELECT category, sub, row_count, partition_count, latest_date, updated_at "
                "FROM _datasets"
            ).fetchall()
            for category, sub, rows_count, partitions, latest_date, updated_at in rows:
                dataset = f"{category}/{sub}" if sub else str(category)
                snapshot.datasets[dataset] = {
                    "row_count": int(rows_count or 0),
                    "partition_count": int(partitions or 0),
                    "latest_date": latest_date,
                    "updated_at": updated_at,
                }
                table = f"dataset_{category}_{sub or 'root'}".lower()
                snapshot.columns[dataset] = {
                    str(column[1])
                    for column in connection.execute(f'PRAGMA table_info("{table}")').fetchall()
                    if str(column[1]) != "_partition"
                }
            metadata_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='_factor_materializations'"
            ).fetchone()
            if metadata_table:
                factor_rows = connection.execute(
                    "SELECT factor_id, definition_hash, status, start_date, end_date, "
                    "row_count, updated_at, error FROM _factor_materializations"
                ).fetchall()
                snapshot.factor_materializations = {
                    str(row[0]): {
                        "definition_hash": str(row[1]),
                        "status": str(row[2]),
                        "start_date": row[3],
                        "end_date": row[4],
                        "row_count": int(row[5] or 0),
                        "updated_at": row[6],
                        "error": row[7],
                    }
                    for row in factor_rows
                }
            ingestion_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='_ingestion_commits'"
            ).fetchone()
            if ingestion_table:
                checkpoint_rows = connection.execute(
                    "SELECT dataset, commit_key, row_counts FROM _ingestion_commits "
                    "WHERE dataset='dividend_incremental_checkpoint' AND commit_key='all'"
                ).fetchall()
                for dataset, commit_key, payload in checkpoint_rows:
                    try:
                        snapshot.ingestion_checkpoints[
                            f"{dataset}/{commit_key}"
                        ] = json.loads(str(payload))
                    except json.JSONDecodeError:
                        continue
    except sqlite3.Error:
        return snapshot
    return snapshot


class FactorCatalog:
    """Provider-aware view over native fields, DSL factors and legacy factors."""

    def __init__(
        self,
        provider: Optional[str] = None,
        factors_dir: Optional[Path] = None,
        field_catalog: Optional[SourceFieldCatalog] = None,
        database_path: Optional[Path] = None,
    ):
        self.provider = (provider or get_active_provider_name()).lower()
        self.factors_dir = Path(factors_dir or FACTOR_DEFINITIONS_DIR)
        self.fields = field_catalog or SourceFieldCatalog()
        self.snapshot = _inspect_provider(self.provider, database_path)
        self.errors: List[Dict[str, str]] = []
        self._definitions: Dict[str, FactorDefinition] = {}
        self._load_definitions()

    def _load_definitions(self) -> None:
        definitions, errors = load_dsl_definitions(self.factors_dir, self.fields)
        self.errors.extend(errors)
        for definition in definitions:
            if definition.id in self._definitions:
                self.errors.append(
                    {"path": str(definition.source_path), "error": f"重复因子 ID: {definition.id}"}
                )
                continue
            self._definitions[definition.id] = definition

        for path in sorted(self.factors_dir.glob("*.py")):
            if path.name.startswith("_"):
                continue
            meta = _read_literal_meta(path)
            if not meta:
                continue
            factor_id = str(meta.get("id", path.stem))
            if factor_id in self._definitions or self.fields.get(factor_id):
                continue
            factor_type = str(meta.get("type", "cross_section"))
            payload = {"meta": meta, "source": str(path)}
            self._definitions[factor_id] = FactorDefinition(
                id=factor_id,
                name=str(meta.get("name", factor_id)),
                description=str(meta.get("description", "")),
                category=_category_for_legacy(factor_id),
                tags=(),
                factor_type=factor_type,
                grain="security_date" if factor_type == "cross_section" else "security_latest",
                engine="python",
                inputs={},
                input_columns={},
                optional_inputs=(),
                expression="",
                output_dtype="float64",
                unit="",
                direction=(
                    "lower_better"
                    if factor_id in {"debt_to_assets", "interest_debt_ratio", "roe_stability_3y"}
                    else "higher_better"
                ),
                null_policy="legacy",
                point_in_time_safe=False,
                enabled=True,
                source_path=path,
                source_kind="legacy_python",
                data_needed=tuple(str(value) for value in meta.get("data_needed", [])),
                definition_hash=_canonical_hash(payload),
                execution_mode="latest_snapshot",
            )

    def list_definitions(self) -> List[FactorDefinition]:
        return list(self._definitions.values())

    def get_definition(self, factor_id: str) -> Optional[FactorDefinition]:
        return self._definitions.get(factor_id)

    def _native_provider_state(self, source: SourceField) -> Dict[str, Any]:
        binding = source.binding_for(self.provider)
        if binding is None:
            return {
                "compatibility": "unavailable",
                "available": False,
                "dataset": "",
                "field": "",
                "note": "当前数据源未提供该语义字段",
            }
        if binding.compatibility == "unavailable":
            return {
                "compatibility": "unavailable",
                "available": False,
                "dataset": binding.dataset,
                "field": binding.field,
                "note": binding.note or "当前数据源未提供该语义字段",
            }
        return {
            "compatibility": binding.compatibility,
            "available": True,
            "dataset": binding.dataset,
            "field": binding.field,
            "note": binding.note,
        }

    def _factor_provider_state(self, definition: FactorDefinition) -> Dict[str, Any]:
        if definition.source_kind == "legacy_python":
            if self.provider == "tushare":
                return {
                    "compatibility": "exact",
                    "available": True,
                    "dataset": "legacy",
                    "field": "",
                    "note": "旧版 Python 因子；尚未迁移到时点安全 DSL",
                }
            return {
                "compatibility": "unavailable",
                "available": False,
                "dataset": "legacy",
                "field": "",
                "note": "旧版财务因子只认可 Tushare 口径",
            }

        states = {
            alias: self._native_provider_state(self.fields.require(reference))
            for alias, reference in definition.inputs.items()
        }
        required_states = [
            state for alias, state in states.items() if alias not in definition.optional_inputs
        ]
        optional_states = [
            state for alias, state in states.items() if alias in definition.optional_inputs
        ]
        required_missing = any(not state["available"] for state in required_states)
        all_optional_missing = not required_states and optional_states and not any(
            state["available"] for state in optional_states
        )
        if required_missing or all_optional_missing:
            return {
                "compatibility": "unavailable",
                "available": False,
                "dataset": "derived",
                "field": definition.id,
                "note": "当前数据源缺少精确输入字段",
            }
        used_states = required_states + [state for state in optional_states if state["available"]]
        compatibility = (
            "approximate"
            if any(state["compatibility"] == "approximate" for state in used_states)
            else "exact"
        )
        return {
            "compatibility": compatibility,
            "available": True,
            "dataset": "derived",
            "field": definition.id,
            "note": "" if compatibility == "exact" else "至少一个输入字段为近似口径",
        }

    def _native_materialization(self, source: SourceField, state: Dict[str, Any]) -> Dict[str, Any]:
        dataset = state.get("dataset", "")
        metadata = self.snapshot.datasets.get(dataset, {})
        ready = bool(state.get("available")) and self.snapshot.has_field(
            dataset, state.get("field", "")
        )
        return {
            "status": "ready" if ready else "not_materialized",
            "row_count": int(metadata.get("row_count", 0)),
            "partition_count": int(metadata.get("partition_count", 0)),
            "latest_date": metadata.get("latest_date"),
            "start_date": None,
            "updated_at": metadata.get("updated_at"),
            "definition_version_verified": True,
            "materialized_definition_hash": None,
            "error": None,
            "usable": ready,
        }

    def _factor_materialization(self, definition: FactorDefinition) -> Dict[str, Any]:
        dataset = (
            "daily/factors"
            if definition.factor_type == "cross_section"
            else "daily/ts_factors"
        )
        metadata = self.snapshot.datasets.get(dataset, {})
        column_ready = self.snapshot.has_field(dataset, definition.id)
        record = self.snapshot.factor_materializations.get(definition.id)
        verified = bool(
            record
            and record["definition_hash"] == definition.definition_hash
            and record["status"] == "ready"
            and column_ready
        )
        if verified:
            status = "ready"
        elif record and record["definition_hash"] != definition.definition_hash:
            status = "stale"
        elif record and record["status"] in {"pending", "computing", "stale", "failed"}:
            status = record["status"]
        elif column_ready:
            status = "ready_unverified"
        else:
            status = "not_materialized"
        return {
            "status": status,
            "row_count": int(record["row_count"] if record else metadata.get("row_count", 0))
            if column_ready or record
            else 0,
            "partition_count": int(metadata.get("partition_count", 0)) if column_ready else 0,
            "latest_date": (record.get("end_date") if record else metadata.get("latest_date"))
            if column_ready or record
            else None,
            "start_date": record.get("start_date") if record else None,
            "updated_at": (record.get("updated_at") if record else metadata.get("updated_at"))
            if column_ready or record
            else None,
            "definition_version_verified": verified if column_ready or record else None,
            "materialized_definition_hash": record.get("definition_hash") if record else None,
            "error": record.get("error") if record else None,
            "usable": status in {"ready", "ready_unverified"},
        }

    def _factor_materialization_blockers(
        self,
        definition: FactorDefinition,
        state: Dict[str, Any],
    ) -> List[str]:
        blockers: List[str] = []
        if state["compatibility"] != "exact":
            blockers.append(state.get("note") or "当前数据源缺少精确输入口径")
        indicator = self.snapshot.datasets.get("daily/indicator", {})
        if not int(indicator.get("row_count", 0)):
            blockers.append("尚未下载每日指标历史")

        needs_dividend_baseline = any(
            semantic_id.startswith("financial.dividend.")
            for semantic_id in definition.inputs.values()
        )
        dividend_checkpoint = self.snapshot.ingestion_checkpoints.get(
            "dividend_incremental_checkpoint/all",
            {},
        )
        if (
            self.provider == "tushare"
            and needs_dividend_baseline
            and dividend_checkpoint.get("status") != "ready"
        ):
            blockers.append("分红历史基线尚未完整下载")

        required_available = []
        optional_available = []
        for alias, semantic_id in definition.inputs.items():
            source = self.fields.require(semantic_id)
            input_state = self._native_provider_state(source)
            locally_ready = bool(input_state["available"]) and self.snapshot.has_field(
                input_state.get("dataset", ""),
                input_state.get("field", ""),
            )
            if alias in definition.optional_inputs:
                optional_available.append(locally_ready)
            else:
                required_available.append(locally_ready)
                if not locally_ready:
                    blockers.append(f"缺少输入数据 {semantic_id}")
        if not required_available and optional_available and not any(optional_available):
            blockers.append("所有可选输入数据均未下载")
        return list(dict.fromkeys(blockers))

    def _native_asset(self, source: SourceField) -> Dict[str, Any]:
        state = self._native_provider_state(source)
        materialization = self._native_materialization(source, state)
        exact = state["compatibility"] == "exact"
        blockers = []
        if not exact:
            blockers.append(state.get("note") or "当前数据源不支持该字段")
        elif not materialization["usable"]:
            blockers.append("当前数据集尚未落地该字段")
        return {
            "id": source.id,
            "semantic_id": source.semantic_id,
            "name": source.name,
            "description": source.description,
            "category": source.category,
            "category_id": _CATEGORY_IDS.get(source.category, "other"),
            "tags": [],
            "asset_kind": "native",
            "type": "native",
            "grain": source.grain,
            "engine": "provider",
            "unit": source.unit,
            "direction": (
                "lower_better" if source.preferred_direction == "asc" else "higher_better"
            ),
            "preferred_direction": source.preferred_direction,
            "inputs": {},
            "optional_inputs": [],
            "data_needed": [state["dataset"]] if state["dataset"] else [],
            "expression": "",
            "point_in_time_safe": True,
            "enabled": True,
            "editable": False,
            "source_path": str(self.fields.path),
            "definition_hash": "",
            "provider": state,
            "materialization": materialization,
            "screening_catalogued": "screening" in source.roles,
            "screening_eligible": exact and "screening" in source.roles,
            "capabilities": {
                "current_screen": exact
                and "screening" in source.roles
                and materialization["usable"],
                "historical_screen": exact
                and "screening" in source.roles
                and materialization["usable"],
            },
            "materialization_blockers": blockers,
            "research_status": "eligible" if exact else "unavailable",
        }

    def _factor_asset(self, definition: FactorDefinition) -> Dict[str, Any]:
        state = self._factor_provider_state(definition)
        materialization = self._factor_materialization(definition)
        blockers = self._factor_materialization_blockers(definition, state)
        exact = state["compatibility"] == "exact"
        research_safe = exact and definition.point_in_time_safe and definition.enabled
        online_safe = definition.execution_mode == "row" and not blockers
        stored_safe = materialization["usable"] and not blockers
        return {
            "id": definition.id,
            "semantic_id": f"factor.{definition.id}",
            "name": definition.name,
            "description": definition.description,
            "category": _CATEGORY_LABELS.get(definition.category, definition.category),
            "category_id": definition.category,
            "tags": list(definition.tags),
            "asset_kind": "derived",
            "type": definition.factor_type,
            "grain": definition.grain,
            "engine": definition.engine,
            "execution_mode": definition.execution_mode,
            "temporal_frequency": definition.temporal_frequency,
            "unit": definition.unit,
            "direction": definition.direction,
            "preferred_direction": (
                "asc" if definition.direction == "lower_better" else "desc"
            ),
            "inputs": dict(definition.inputs),
            "optional_inputs": list(definition.optional_inputs),
            "data_needed": list(definition.data_needed) or list(definition.inputs.values()),
            "expression": definition.expression,
            "point_in_time_safe": definition.point_in_time_safe,
            "enabled": definition.enabled,
            "editable": definition.editable,
            "source_path": str(definition.source_path),
            "definition_hash": definition.definition_hash,
            "provider": state,
            "materialization": materialization,
            "screening_catalogued": definition.factor_type == "cross_section"
            and definition.enabled,
            "screening_eligible": research_safe and definition.factor_type == "cross_section",
            "capabilities": {
                "current_screen": research_safe
                and definition.factor_type == "cross_section"
                and (online_safe or stored_safe),
                "historical_screen": research_safe
                and definition.factor_type == "cross_section"
                and (online_safe or stored_safe),
            },
            "materialization_blockers": blockers,
            "research_status": (
                "eligible"
                if research_safe
                else "live_only"
                if exact and not definition.point_in_time_safe
                else "unavailable"
            ),
        }

    def list_assets(self) -> List[Dict[str, Any]]:
        assets = [self._native_asset(source) for source in self.fields.list_all()]
        assets.extend(self._factor_asset(definition) for definition in self._definitions.values())
        return sorted(
            assets,
            key=lambda item: (
                0 if item["asset_kind"] == "native" else 1,
                item["category"],
                item["name"],
            ),
        )

    def get_asset(self, factor_id: str) -> Optional[Dict[str, Any]]:
        source = self.fields.get(factor_id)
        if source and source.id == factor_id:
            return self._native_asset(source)
        definition = self._definitions.get(factor_id)
        return self._factor_asset(definition) if definition else None

    def payload(self) -> Dict[str, Any]:
        assets = self.list_assets()
        summary = {
            "total": len(assets),
            "native": sum(item["asset_kind"] == "native" for item in assets),
            "derived": sum(item["asset_kind"] == "derived" for item in assets),
            "dsl": sum(item["engine"] == "polars" for item in assets),
            "eligible": sum(item["research_status"] == "eligible" for item in assets),
            "materialized": sum(item["materialization"].get("usable", False) for item in assets),
            "unavailable": sum(not item["provider"]["available"] for item in assets),
        }
        return {
            "provider": self.provider,
            "database_path": str(self.snapshot.database_path),
            "summary": summary,
            "categories": sorted({item["category"] for item in assets}),
            "items": assets,
            "errors": self.errors,
        }


def save_factor_definition(
    payload: Dict[str, Any],
    factors_dir: Optional[Path] = None,
    existing_id: Optional[str] = None,
) -> FactorDefinition:
    root = Path(factors_dir or FACTOR_DEFINITIONS_DIR)
    fields = SourceFieldCatalog()
    normalized = _validate_definition_payload(payload, fields)
    catalog = FactorCatalog(factors_dir=root, field_catalog=fields)
    factor_id = normalized["id"]

    if fields.get(factor_id):
        raise ValueError(f"因子 ID 与原生字段冲突: {factor_id}")

    if existing_id is None:
        if catalog.get_definition(factor_id) is not None:
            raise FileExistsError(f"因子已存在: {factor_id}")
        path = root / "definitions" / normalized["category"] / f"{factor_id}.factor.yaml"
    else:
        existing = catalog.get_definition(existing_id)
        if existing is None:
            raise KeyError(f"因子不存在: {existing_id}")
        if not existing.editable:
            raise ValueError("旧版 Python 因子不可在 DSL 编辑器中修改")
        if factor_id != existing_id:
            raise ValueError("因子 ID 创建后不可修改")
        path = existing.source_path

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(normalized, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return load_factor_definition(path, fields)
