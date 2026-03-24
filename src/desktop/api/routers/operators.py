"""
Operator management endpoints — list, view, edit, create operators.
"""
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.data.settings import PROJECT_ROOT
from src.engine.operators import Operator, OperatorRegistry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/operators", tags=["operators"])

OPERATORS_DIR = "operators/v2"


def _get_registry() -> OperatorRegistry:
    """Create a fresh operator registry."""
    return OperatorRegistry(operators_dir=OPERATORS_DIR)


def _operator_to_dict(op: Operator) -> dict:
    """Serialize an Operator to a JSON-friendly dict."""
    # Derive category from source_path subdirectory
    category = ""
    if op.source_path:
        rel = op.source_path.relative_to(PROJECT_ROOT / OPERATORS_DIR)
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
        "file_path": str(op.source_path) if op.source_path else "",
    }


@router.get("")
async def list_operators():
    """List all operators grouped by category."""
    registry = _get_registry()
    operators = registry.list_all()

    grouped: Dict[str, List[dict]] = {}
    for op in operators:
        d = _operator_to_dict(op)
        cat = d["category"] or "uncategorized"
        grouped.setdefault(cat, []).append(d)

    # Sort within groups
    for cat in grouped:
        grouped[cat].sort(key=lambda x: x["id"])

    return {
        "categories": sorted(grouped.keys()),
        "operators": grouped,
        "total": len(operators),
    }


@router.get("/{op_id}")
async def get_operator(op_id: str):
    """Get full operator detail including markdown content."""
    registry = _get_registry()
    op = registry.get(op_id)
    if not op:
        raise HTTPException(status_code=404, detail=f"Operator not found: {op_id}")

    d = _operator_to_dict(op)

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
    content: str = ""


def _build_file_content(meta: dict, body: str) -> str:
    """Build the full .md file content from frontmatter dict and body."""
    frontmatter = yaml.dump(meta, allow_unicode=True, default_flow_style=False, sort_keys=False).strip()
    return f"---\n{frontmatter}\n---\n\n{body.strip()}\n"


@router.put("/{op_id}")
async def update_operator(op_id: str, update: OperatorUpdate):
    """Update an existing operator (write back to .md file)."""
    registry = _get_registry()
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

    # Use new content or keep existing
    body = update.content if update.content is not None else op.content

    # Write back
    new_content = _build_file_content(meta, body)
    op.source_path.write_text(new_content, encoding="utf-8")

    # Return updated operator
    registry2 = _get_registry()
    updated = registry2.get(op_id)
    if updated:
        d = _operator_to_dict(updated)
        d["content"] = updated.content
        return d

    return {"status": "ok", "id": op_id}


@router.post("")
async def create_operator(data: OperatorCreate):
    """Create a new operator (.md file)."""
    # Determine target directory
    category = data.category or "uncategorized"
    target_dir = PROJECT_ROOT / OPERATORS_DIR / category
    target_dir.mkdir(parents=True, exist_ok=True)

    target_file = target_dir / f"{data.id}.md"
    if target_file.exists():
        raise HTTPException(
            status_code=409,
            detail=f"Operator file already exists: {target_file.relative_to(PROJECT_ROOT)}",
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

    content = _build_file_content(meta, data.content)
    target_file.write_text(content, encoding="utf-8")

    # Return created operator
    registry = _get_registry()
    op = registry.get(data.id)
    if op:
        d = _operator_to_dict(op)
        d["content"] = op.content
        return d

    return {"status": "ok", "id": data.id, "file_path": str(target_file)}
