"""Build a credential-free, portable snapshot of the private research workspace."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DATABASE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}
TEXT_SUFFIXES = {".csv", ".json", ".md", ".txt", ".yaml", ".yml"}
SQLITE_SIDECAR_SUFFIXES = ("-journal", "-shm", "-wal")
GENERIC_SECRET_PATTERNS = (
    re.compile(r"(?i)\bsk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._-]{12,}"),
)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    # Windows PowerShell 5.1 writes UTF-8 with a BOM. ``utf-8-sig`` accepts
    # both that output and ordinary BOM-free UTF-8 files.
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _excluded_workspace_path(relative: Path) -> bool:
    lowered = tuple(part.lower() for part in relative.parts)
    name = relative.name.lower()
    if lowered[:3] == ("data", "providers", "baostock"):
        return True
    if "__pycache__" in lowered or name.endswith(".pyc"):
        return True
    if name == ".env" or name.startswith(".env."):
        return True
    return name.endswith(SQLITE_SIDECAR_SUFFIXES)


def _backup_sqlite(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_uri = f"file:{source.resolve().as_posix()}?mode=ro"
    print(f"SQLite snapshot: {source}", flush=True)
    with sqlite3.connect(source_uri, uri=True, timeout=60) as source_db:
        with sqlite3.connect(destination, timeout=60) as destination_db:
            source_db.backup(destination_db, pages=16_384, sleep=0.05)
            destination_db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
            destination_db.execute("PRAGMA journal_mode=DELETE").fetchone()
    for suffix in SQLITE_SIDECAR_SUFFIXES:
        destination.with_name(destination.name + suffix).unlink(missing_ok=True)
    with sqlite3.connect(f"file:{destination.resolve().as_posix()}?mode=ro", uri=True) as check:
        check.execute("SELECT count(*) FROM sqlite_master").fetchone()


def _copy_workspace(source: Path, destination: Path) -> None:
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if _excluded_workspace_path(relative) or path.is_symlink():
            continue
        target = destination / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.suffix.lower() in DATABASE_SUFFIXES:
            _backup_sqlite(path, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def _collect_credentials(source_workspace: Path) -> list[str]:
    credentials: list[str] = []
    for path, keys in (
        (source_workspace / "data/data_config.json", ("tushare_token",)),
        (source_workspace / "data/desktop/config.json", ("llm_api_key",)),
    ):
        payload = _load_json(path)
        for key in keys:
            value = str(payload.get(key, "")).strip()
            if value:
                credentials.append(value)
    return credentials


def _redact_text(text: str, credentials: Iterable[str]) -> str:
    for credential in credentials:
        text = text.replace(credential, "<redacted>")
    for pattern in GENERIC_SECRET_PATTERNS:
        text = pattern.sub("<redacted>", text)
    return text


def _sanitize_workspace(workspace: Path, credentials: list[str]) -> None:
    data_config_path = workspace / "data/data_config.json"
    data_config = _load_json(data_config_path)
    data_config.update(
        {
            "provider": "tushare",
            "tushare_token": "",
            "auto_update_enabled": False,
        }
    )
    _write_json(data_config_path, data_config)

    desktop_config_path = workspace / "data/desktop/config.json"
    desktop_config = _load_json(desktop_config_path)
    desktop_config["llm_api_key"] = ""
    desktop_config["lan_access_enabled"] = False
    for key in list(desktop_config):
        normalized = key.lower()
        if normalized in {"lan_access_token", "lan_access_token_hash"}:
            desktop_config.pop(key, None)
    _write_json(desktop_config_path, desktop_config)

    for path in workspace.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            original = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        redacted = _redact_text(original, credentials)
        if redacted != original:
            path.write_text(redacted, encoding="utf-8")


def _validate_workspace(workspace: Path, credentials: list[str]) -> None:
    if (workspace / "data/providers/baostock").exists():
        raise RuntimeError("BaoStock data leaked into the private Tushare baseline")
    tushare_db = workspace / "data/providers/tushare/market.db"
    if not tushare_db.is_file() or tushare_db.stat().st_size == 0:
        raise RuntimeError("Tushare market.db is missing from the private baseline")

    data_config = _load_json(workspace / "data/data_config.json")
    desktop_config = _load_json(workspace / "data/desktop/config.json")
    if data_config.get("tushare_token"):
        raise RuntimeError("Tushare token was not removed")
    if data_config.get("provider") != "tushare" or data_config.get("auto_update_enabled"):
        raise RuntimeError("Private baseline must use static Tushare data")
    if desktop_config.get("llm_api_key"):
        raise RuntimeError("LLM API key was not removed")
    if desktop_config.get("lan_access_enabled"):
        raise RuntimeError("LAN access must be disabled in the private baseline")

    leaked_sidecars = [
        path for path in workspace.rglob("*") if path.name.lower().endswith(SQLITE_SIDECAR_SUFFIXES)
    ]
    if leaked_sidecars:
        raise RuntimeError(f"SQLite sidecar leaked into baseline: {leaked_sidecars[0]}")

    for path in workspace.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if any(secret and secret in text for secret in credentials):
            raise RuntimeError(f"Credential leaked into {path}")
        if any(pattern.search(text) for pattern in GENERIC_SECRET_PATTERNS):
            raise RuntimeError(f"Possible credential leaked into {path}")


def _write_private_metadata(staging: Path, display_version: str) -> None:
    build_info_path = staging / "BUILD_INFO.json"
    build_info = _load_json(build_info_path)
    build_info.update(
        {
            "package_kind": "private-tushare-baseline",
            "display_version": display_version,
            "data_provider": "tushare",
            "data_auto_update": False,
            "credentials_included": False,
            "baseline_built_at_utc": datetime.now(timezone.utc).isoformat(),
        }
    )
    _write_json(build_info_path, build_info)

    _write_json(
        staging / "PRIVATE_BASELINE_INFO.json",
        {
            "package_kind": "private-tushare-baseline",
            "display_version": display_version,
            "usage": "private backup and internal migration only",
            "included": [
                "standard application",
                "Tushare historical database",
                "research reports and backtests",
                "frameworks, operators, factors and screening strategies",
                "conversation history and non-secret settings",
            ],
            "excluded": [
                "BaoStock database",
                "Tushare token",
                "LLM API key",
                "LAN credentials",
                ".env files",
                "SQLite WAL/SHM/journal files",
            ],
        },
    )
    (staging / "PRIVATE_BASELINE_README.md").write_text(
        "# Thesis Backtester 私有 Tushare 基线\n\n"
        "本包用于个人备份与内部迁移，不是公开数据发行包。它包含构建时的静态 "
        "Tushare 历史数据库、研究报告、回测结果与对话历史。\n\n"
        "Tushare Token、LLM API Key 和局域网凭据均已移除，自动数据更新默认关闭。"
        "如需继续更新或调用 LLM，请在系统设置中配置自己的凭据。\n",
        encoding="utf-8",
    )


def _create_zip(staging: Path, archive: Path) -> None:
    temporary = archive.with_suffix(archive.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    archive.parent.mkdir(parents=True, exist_ok=True)
    files = sorted(path for path in staging.rglob("*") if path.is_file())
    print(f"Creating ZIP64 archive with {len(files)} files: {archive}", flush=True)
    try:
        with zipfile.ZipFile(
            temporary,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=3,
            allowZip64=True,
        ) as output:
            for index, path in enumerate(files, 1):
                if path.stat().st_size >= 100 * 1024 * 1024:
                    print(
                        f"Compressing {path.relative_to(staging)} "
                        f"({path.stat().st_size / 1024**3:.2f} GiB)",
                        flush=True,
                    )
                output.write(path, path.relative_to(staging).as_posix())
                if index % 1000 == 0:
                    print(f"Archived {index}/{len(files)} files", flush=True)
        temporary.replace(archive)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def build_private_baseline(
    *,
    project_root: Path,
    source_workspace: Path,
    standard_release: Path,
    staging_dir: Path,
    archive: Path,
    display_version: str,
) -> None:
    project_root = project_root.resolve()
    source_workspace = source_workspace.resolve()
    standard_release = standard_release.resolve()
    staging_dir = staging_dir.resolve()
    archive = archive.resolve()
    if not _is_within(staging_dir, project_root) or not _is_within(archive, project_root):
        raise ValueError("Staging and archive paths must stay inside the project")
    if staging_dir.exists() or archive.exists():
        raise FileExistsError("Private baseline output already exists")
    if not source_workspace.is_dir() or not standard_release.is_dir():
        raise FileNotFoundError("Source workspace or standard release is missing")

    credentials = _collect_credentials(source_workspace)
    print(f"Copying standard release to {staging_dir}", flush=True)
    shutil.copytree(standard_release, staging_dir)
    staged_workspace = staging_dir / "workspace"
    shutil.rmtree(staged_workspace, ignore_errors=True)
    staged_workspace.mkdir(parents=True)
    _copy_workspace(source_workspace, staged_workspace)
    _sanitize_workspace(staged_workspace, credentials)
    _validate_workspace(staged_workspace, credentials)
    _write_private_metadata(staging_dir, display_version)
    _create_zip(staging_dir, archive)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--source-workspace", type=Path, required=True)
    parser.add_argument("--standard-release", type=Path, required=True)
    parser.add_argument("--staging-dir", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--display-version", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    build_private_baseline(
        project_root=args.project_root,
        source_workspace=args.source_workspace,
        standard_release=args.standard_release,
        staging_dir=args.staging_dir,
        archive=args.archive,
        display_version=args.display_version,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
