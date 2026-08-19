"""
Operator management endpoints — list, view, edit, create operators.
"""
import logging
import re
from typing import Dict, List, Optional

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.data.settings import WORKSPACE_ROOT
from src.engine.operators import Operator, OperatorRegistry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/operators", tags=["operators"])

DEFAULT_OPERATOR_VERSION = "v2"


def _available_operator_versions() -> List[dict]:
    """Discover versioned operator libraries without accepting arbitrary paths."""
    root = WORKSPACE_ROOT / "operators"
    versions = []
    if not root.exists():
        return versions
    for path in root.iterdir():
        if not path.is_dir() or not re.fullmatch(r"v\d+", path.name):
            continue
        registry = OperatorRegistry(operators_dir=f"operators/{path.name}")
        public = registry.list_all()
        all_operators = registry.list_all(include_internal=True)
        versions.append(
            {
                "id": path.name,
                "operators_dir": f"operators/{path.name}",
                "label": f"{path.name}（{'当前版本' if path.name == DEFAULT_OPERATOR_VERSION else '历史版本'}）",
                "operator_count": len(public),
                "internal_count": len(all_operators) - len(public),
                "current": path.name == DEFAULT_OPERATOR_VERSION,
            }
        )
    versions.sort(key=lambda item: int(item["id"][1:]), reverse=True)
    return versions


def _normalize_version(version: str = DEFAULT_OPERATOR_VERSION) -> tuple[str, str]:
    raw = str(version or DEFAULT_OPERATOR_VERSION).strip().replace("\\", "/")
    version_id = raw.split("/", 1)[1] if raw.startswith("operators/") else raw
    available = {item["id"]: item for item in _available_operator_versions()}
    if version_id not in available:
        raise HTTPException(status_code=404, detail=f"Operator library not found: {raw}")
    return version_id, available[version_id]["operators_dir"]


def _get_registry(version: str = DEFAULT_OPERATOR_VERSION) -> tuple[OperatorRegistry, str, str]:
    """Create a fresh operator registry."""
    version_id, operators_dir = _normalize_version(version)
    return OperatorRegistry(operators_dir=operators_dir), version_id, operators_dir


def _operator_to_dict(op: Operator, version_id: str, operators_dir: str) -> dict:
    """Serialize an Operator to a JSON-friendly dict."""
    # Derive category from source_path subdirectory
    category = ""
    if op.source_path:
        rel = op.source_path.relative_to(WORKSPACE_ROOT / operators_dir)
        if len(rel.parts) > 1:
            category = rel.parts[0]

    return {
        "id": op.id,
        "name": op.name,
        "category": category,
        "tags": op.tags,
        "outputs": [
            {"field": o.field, "type": o.type, "desc": o.desc}
            for o in op.outputs
        ],
        "gate": op.gate,
        "data_needed": op.data_needed,
        "weight": op.weight,
        "score_range": op.score_range,
        "history_variant": op.history_variant,
        "execution_mode": op.execution_mode,
        "selectable": op.execution_mode != "history_adapter",
        "library_version": version_id,
        "operators_dir": operators_dir,
        "file_path": str(op.source_path) if op.source_path else "",
    }


@router.get("")
async def list_operators(
    version: str = DEFAULT_OPERATOR_VERSION,
    include_internal: bool = False,
):
    """List all operators grouped by category."""
    registry, version_id, operators_dir = _get_registry(version)
    operators = registry.list_all(include_internal=include_internal)

    grouped: Dict[str, List[dict]] = {}
    for op in operators:
        d = _operator_to_dict(op, version_id, operators_dir)
        cat = d["category"] or "uncategorized"
        grouped.setdefault(cat, []).append(d)

    # Sort within groups
    for cat in grouped:
        grouped[cat].sort(key=lambda x: x["id"])

    return {
        "categories": sorted(grouped.keys()),
        "operators": grouped,
        "total": len(operators),
        "version": version_id,
        "operators_dir": operators_dir,
        "available_versions": _available_operator_versions(),
        "include_internal": include_internal,
    }


@router.get("/versions")
async def list_operator_versions():
    """List operator library versions available to the desktop editor."""
    return {
        "default": DEFAULT_OPERATOR_VERSION,
        "versions": _available_operator_versions(),
    }


@router.get("/{op_id}")
async def get_operator(op_id: str, version: str = DEFAULT_OPERATOR_VERSION):
    """Get full operator detail including markdown content."""
    registry, version_id, operators_dir = _get_registry(version)
    op = registry.get(op_id)
    if not op:
        raise HTTPException(status_code=404, detail=f"Operator not found: {op_id}")

    d = _operator_to_dict(op, version_id, operators_dir)

    # Read full raw content from file
    raw_content = ""
    if op.source_path and op.source_path.exists():
        raw_content = op.source_path.read_text(encoding="utf-8")

    d["content"] = op.content  # markdown body (without frontmatter)
    d["raw_content"] = raw_content  # full file content
    return d


class OperatorUpdate(BaseModel):
    name: Optional[str] = None
    tags: Optional[List[str]] = None
    data_needed: Optional[List[str]] = None
    outputs: Optional[List[dict]] = None
    gate: Optional[dict] = None
    weight: Optional[float] = None
    score_range: Optional[str] = None
    history_variant: Optional[str] = None
    execution_mode: Optional[str] = None
    content: Optional[str] = None  # markdown body


class OperatorCreate(BaseModel):
    id: str
    name: str
    category: str
    tags: List[str] = []
    data_needed: List[str] = []
    outputs: List[dict] = []
    gate: dict = {}
    weight: float = 1.0
    score_range: str = "0-100"
    history_variant: str = ""
    execution_mode: str = "standard"
    content: str = ""


def _build_file_content(meta: dict, body: str) -> str:
    """Build the full .md file content from frontmatter dict and body."""
    frontmatter = yaml.dump(meta, allow_unicode=True, default_flow_style=False, sort_keys=False).strip()
    return f"---\n{frontmatter}\n---\n\n{body.strip()}\n"


@router.put("/{op_id}")
async def update_operator(
    op_id: str,
    update: OperatorUpdate,
    version: str = DEFAULT_OPERATOR_VERSION,
):
    """Update an existing operator (write back to .md file)."""
    registry, version_id, operators_dir = _get_registry(version)
    op = registry.get(op_id)
    if not op:
        raise HTTPException(status_code=404, detail=f"Operator not found: {op_id}")

    if not op.source_path or not op.source_path.exists():
        raise HTTPException(status_code=500, detail="Operator source file not found")

    # Read existing file to get current frontmatter
    text = op.source_path.read_text(encoding="utf-8")
    text = text.strip()

    # Parse existing frontmatter
    meta = {}
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            front = text[3:end].strip()
            try:
                meta = yaml.safe_load(front) or {}
            except yaml.YAMLError:
                meta = {}

    # Apply updates to frontmatter
    if update.name is not None:
        meta["name"] = update.name
    if update.tags is not None:
        meta["tags"] = update.tags
    if update.data_needed is not None:
        meta["data_needed"] = update.data_needed
    if update.outputs is not None:
        meta["outputs"] = update.outputs
    if update.gate is not None:
        meta["gate"] = update.gate
    if update.weight is not None:
        meta["weight"] = update.weight
    if update.score_range is not None:
        meta["score_range"] = update.score_range
    if update.history_variant is not None:
        if update.history_variant:
            meta["history_variant"] = update.history_variant
        else:
            meta.pop("history_variant", None)
    if update.execution_mode is not None:
        if update.execution_mode not in {"standard", "history_adapter"}:
            raise HTTPException(status_code=422, detail="Unsupported execution_mode")
        meta["execution_mode"] = update.execution_mode

    # Use new content or keep existing
    body = update.content if update.content is not None else op.content

    # Write back
    new_content = _build_file_content(meta, body)
    op.source_path.write_text(new_content, encoding="utf-8")

    # Return updated operator
    registry2, _, _ = _get_registry(version_id)
    updated = registry2.get(op_id)
    if updated:
        d = _operator_to_dict(updated, version_id, operators_dir)
        d["content"] = updated.content
        return d

    return {"status": "ok", "id": op_id}


@router.post("")
async def create_operator(
    data: OperatorCreate,
    version: str = DEFAULT_OPERATOR_VERSION,
):
    """Create a new operator (.md file)."""
    version_id, operators_dir = _normalize_version(version)
    # Determine target directory
    category = data.category or "uncategorized"
    target_dir = WORKSPACE_ROOT / operators_dir / category
    target_dir.mkdir(parents=True, exist_ok=True)

    target_file = target_dir / f"{data.id}.md"
    if target_file.exists():
        raise HTTPException(
            status_code=409,
            detail=f"Operator file already exists: {target_file.relative_to(WORKSPACE_ROOT)}",
        )

    # Build frontmatter
    meta = {
        "id": data.id,
        "name": data.name,
        "category": category,
        "tags": data.tags,
        "data_needed": data.data_needed,
        "outputs": data.outputs,
    }
    if data.gate:
        meta["gate"] = data.gate
    if data.weight != 1.0:
        meta["weight"] = data.weight
    if data.score_range != "0-100":
        meta["score_range"] = data.score_range
    if data.history_variant:
        meta["history_variant"] = data.history_variant
    if data.execution_mode not in {"standard", "history_adapter"}:
        raise HTTPException(status_code=422, detail="Unsupported execution_mode")
    if data.execution_mode != "standard":
        meta["execution_mode"] = data.execution_mode

    content = _build_file_content(meta, data.content)
    target_file.write_text(content, encoding="utf-8")

    # Return created operator
    registry, _, _ = _get_registry(version_id)
    op = registry.get(data.id)
    if op:
        d = _operator_to_dict(op, version_id, operators_dir)
        d["content"] = op.content
        return d

    return {"status": "ok", "id": data.id, "file_path": str(target_file)}
