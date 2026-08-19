import importlib.util
import json
import sqlite3
import sys
import zipfile
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[1] / "scripts/package_private_baseline.py"
SPEC = importlib.util.spec_from_file_location("package_private_baseline", SCRIPT_PATH)
assert SPEC and SPEC.loader
PACKAGE_MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PACKAGE_MODULE
SPEC.loader.exec_module(PACKAGE_MODULE)
build_private_baseline = PACKAGE_MODULE.build_private_baseline


def _make_database(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as database:
        database.execute("PRAGMA journal_mode=WAL")
        database.execute("CREATE TABLE sample (value TEXT)")
        database.execute("INSERT INTO sample VALUES (?)", (value,))


def test_private_baseline_is_complete_static_and_credential_free(tmp_path):
    project_root = tmp_path / "project"
    standard_release = project_root / "dist/standard"
    source_workspace = project_root / "workspace"
    staging_dir = project_root / ".build/private"
    archive = project_root / "dist/private.zip"

    standard_release.mkdir(parents=True)
    (standard_release / "ThesisBacktester.exe").write_bytes(b"application")
    (standard_release / "BUILD_INFO.json").write_text(
        "\ufeff" + json.dumps({"version": "0.1.0"}), encoding="utf-8"
    )
    (standard_release / "workspace/old.txt").parent.mkdir(parents=True)
    (standard_release / "workspace/old.txt").write_text("seed", encoding="utf-8")

    tushare_token = "0123456789abcdef0123456789abcdef"
    llm_key = "sk-private-example-value"
    data_config = source_workspace / "data/data_config.json"
    data_config.parent.mkdir(parents=True)
    data_config.write_text(
        json.dumps(
            {
                "provider": "baostock",
                "tushare_token": tushare_token,
                "auto_update_enabled": True,
                "auto_update_time": "18:30",
            }
        ),
        encoding="utf-8",
    )
    desktop_config = source_workspace / "data/desktop/config.json"
    desktop_config.parent.mkdir(parents=True)
    desktop_config.write_text(
        json.dumps(
            {
                "llm_api_key": llm_key,
                "llm_model": "example-model",
                "lan_access_enabled": True,
                "lan_access_token_hash": "private-hash",
            }
        ),
        encoding="utf-8",
    )
    (desktop_config.parent / "chat_history.json").write_text(
        json.dumps({"conversations": [f"keys: {tushare_token} and {llm_key}"]}),
        encoding="utf-8",
    )
    (source_workspace / ".env").write_text("SECRET=value", encoding="utf-8")
    report = source_workspace / "strategies/custom/live/report.md"
    report.parent.mkdir(parents=True)
    report.write_text("research result", encoding="utf-8")
    _make_database(source_workspace / "data/providers/tushare/market.db", "tushare")
    _make_database(source_workspace / "data/providers/baostock/market.db", "baostock")

    build_private_baseline(
        project_root=project_root,
        source_workspace=source_workspace,
        standard_release=standard_release,
        staging_dir=staging_dir,
        archive=archive,
        display_version="Beta v0.1.0",
    )

    with zipfile.ZipFile(archive) as package:
        names = set(package.namelist())
        assert "ThesisBacktester.exe" in names
        assert "workspace/data/providers/tushare/market.db" in names
        assert "workspace/strategies/custom/live/report.md" in names
        assert "PRIVATE_BASELINE_INFO.json" in names
        assert not any("baostock" in name.lower() for name in names)
        assert not any(name.endswith((".env", "-wal", "-shm", "-journal")) for name in names)

        packaged_data_config = json.loads(
            package.read("workspace/data/data_config.json").decode("utf-8")
        )
        packaged_desktop_config = json.loads(
            package.read("workspace/data/desktop/config.json").decode("utf-8")
        )
        packaged_chat = package.read("workspace/data/desktop/chat_history.json").decode("utf-8")
        build_info = json.loads(package.read("BUILD_INFO.json").decode("utf-8"))

    assert packaged_data_config["provider"] == "tushare"
    assert packaged_data_config["tushare_token"] == ""
    assert packaged_data_config["auto_update_enabled"] is False
    assert packaged_desktop_config["llm_api_key"] == ""
    assert packaged_desktop_config["lan_access_enabled"] is False
    assert "lan_access_token_hash" not in packaged_desktop_config
    assert tushare_token not in packaged_chat
    assert llm_key not in packaged_chat
    assert build_info["package_kind"] == "private-tushare-baseline"
    assert build_info["display_version"] == "Beta v0.1.0"

    extracted_db = tmp_path / "market.db"
    with zipfile.ZipFile(archive) as package:
        extracted_db.write_bytes(package.read("workspace/data/providers/tushare/market.db"))
    with sqlite3.connect(extracted_db) as database:
        assert database.execute("SELECT value FROM sample").fetchone()[0] == "tushare"
