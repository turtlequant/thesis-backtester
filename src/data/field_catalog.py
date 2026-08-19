"""Semantic native-field catalog with explicit provider bindings.

The catalog describes source data only.  Derived calculations live in the
factor catalog and reference the stable ``semantic_id`` values defined here.
Provider adapters are therefore allowed to expose different capabilities
without pretending that their raw tables are equivalent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from .settings import PROJECT_ROOT


DEFAULT_FIELD_CATALOG_PATH = PROJECT_ROOT / "src" / "data" / "catalog" / "native_fields.yaml"
COMPATIBILITY_LEVELS = {"exact", "approximate", "unavailable"}


@dataclass(frozen=True)
class ProviderFieldBinding:
    provider: str
    dataset: str
    field: str
    compatibility: str = "exact"
    note: str = ""


@dataclass(frozen=True)
class SourceField:
    id: str
    semantic_id: str
    name: str
    description: str
    category: str
    column: str
    dtype: str
    unit: str
    grain: str
    time_field: str
    preferred_direction: str = "desc"
    aggregation: str = "last"
    roles: Tuple[str, ...] = ()
    bindings: Dict[str, ProviderFieldBinding] = field(default_factory=dict)

    def binding_for(self, provider: str) -> Optional[ProviderFieldBinding]:
        return self.bindings.get(provider.lower())


class SourceFieldCatalog:
    """Load and resolve stable semantic fields."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path or DEFAULT_FIELD_CATALOG_PATH)
        self.schema_version = 1
        self._by_id: Dict[str, SourceField] = {}
        self._by_semantic_id: Dict[str, SourceField] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            raise FileNotFoundError(f"原生字段目录不存在: {self.path}")
        payload = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        self.schema_version = int(payload.get("schema_version", 1))
        if self.schema_version != 1:
            raise ValueError(f"不支持的原生字段目录版本: {self.schema_version}")

        for raw in payload.get("fields", []):
            bindings: Dict[str, ProviderFieldBinding] = {}
            for provider, binding in (raw.get("bindings") or {}).items():
                compatibility = str(binding.get("compatibility", "exact"))
                if compatibility not in COMPATIBILITY_LEVELS:
                    raise ValueError(
                        f"字段 {raw.get('id')} 的 {provider} 兼容等级无效: {compatibility}"
                    )
                bindings[str(provider).lower()] = ProviderFieldBinding(
                    provider=str(provider).lower(),
                    dataset=str(binding.get("dataset", "")),
                    field=str(binding.get("field", raw.get("column", raw.get("id", "")))),
                    compatibility=compatibility,
                    note=str(binding.get("note", "")),
                )

            source = SourceField(
                id=str(raw["id"]),
                semantic_id=str(raw["semantic_id"]),
                name=str(raw.get("name", raw["id"])),
                description=str(raw.get("description", "")),
                category=str(raw.get("category", "其他")),
                column=str(raw.get("column", raw["id"])),
                dtype=str(raw.get("dtype", "float64")),
                unit=str(raw.get("unit", "")),
                grain=str(raw.get("grain", "security_date")),
                time_field=str(raw.get("time_field", "trade_date")),
                preferred_direction=str(raw.get("preferred_direction", "desc")),
                aggregation=str(raw.get("aggregation", "last")),
                roles=tuple(str(role) for role in raw.get("roles", [])),
                bindings=bindings,
            )
            if source.id in self._by_id or source.semantic_id in self._by_semantic_id:
                raise ValueError(f"原生字段目录存在重复定义: {source.id}")
            self._by_id[source.id] = source
            self._by_semantic_id[source.semantic_id] = source

    def list_all(self) -> List[SourceField]:
        return list(self._by_id.values())

    def get(self, identifier: str) -> Optional[SourceField]:
        return self._by_id.get(identifier) or self._by_semantic_id.get(identifier)

    def require(self, identifier: str) -> SourceField:
        source = self.get(identifier)
        if source is None:
            raise KeyError(f"未知原生字段: {identifier}")
        return source

    def resolve_column(self, semantic_id: str) -> str:
        return self.require(semantic_id).column
