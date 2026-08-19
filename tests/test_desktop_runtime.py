import asyncio
import json

from src.data import settings as data_settings
from src.desktop import runtime
from src.desktop.api.routers import chat


def test_project_root_resolves_to_executable_directory_when_compiled(tmp_path):
    module_file = tmp_path / "source" / "src" / "data" / "settings.py"
    executable = tmp_path / "release" / "ThesisBacktester.exe"

    assert data_settings.resolve_project_root(module_file, executable, compiled=True) == (
        executable.parent.resolve()
    )
    assert data_settings.resolve_project_root(module_file, executable, compiled=False) == (
        module_file.resolve().parents[2]
    )


def test_data_root_supports_relative_and_absolute_overrides(tmp_path, monkeypatch):
    monkeypatch.setattr(data_settings, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(data_settings, "WORKSPACE_ROOT", tmp_path / "workspace")

    assert data_settings.resolve_data_root("") == tmp_path / "workspace" / "data"
    assert data_settings.resolve_data_root("market-data") == (
        tmp_path / "workspace" / "market-data"
    ).resolve()
    assert data_settings.resolve_data_root(str(tmp_path / "external")) == (
        tmp_path / "external"
    ).resolve()


def test_workspace_root_supports_relative_and_absolute_overrides(tmp_path, monkeypatch):
    monkeypatch.setattr(data_settings, "PROJECT_ROOT", tmp_path)

    assert data_settings.resolve_workspace_root("") == tmp_path / "workspace"
    assert data_settings.resolve_workspace_root("research") == (tmp_path / "research").resolve()
    assert data_settings.resolve_workspace_root(str(tmp_path / "external")) == (
        tmp_path / "external"
    ).resolve()


def test_prepare_workspace_migrates_legacy_roots_and_seeds_missing_files(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "workspace"
    seed = tmp_path / "resources" / "workspace_seed"
    roots = {
        "data": workspace / "data",
        "strategies": workspace / "strategies",
        "operators": workspace / "operators",
        "factors": workspace / "factors",
        "screening_strategies": workspace / "screening_strategies",
    }
    for name in roots:
        legacy = tmp_path / name
        legacy.mkdir()
        (legacy / "legacy.txt").write_text(name, encoding="utf-8")
    (seed / "strategies" / "builtin").mkdir(parents=True)
    (seed / "strategies" / "builtin" / "strategy.yaml").write_text(
        "name: builtin", encoding="utf-8"
    )

    monkeypatch.setattr(data_settings, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(data_settings, "WORKSPACE_ROOT", workspace)
    monkeypatch.setattr(data_settings, "WORKSPACE_SEED_ROOT", seed)
    monkeypatch.setattr(data_settings, "DATA_ROOT", roots["data"])
    monkeypatch.setattr(data_settings, "STRATEGIES_ROOT", roots["strategies"])
    monkeypatch.setattr(data_settings, "OPERATORS_ROOT", roots["operators"])
    monkeypatch.setattr(data_settings, "FACTORS_ROOT", roots["factors"])
    monkeypatch.setattr(
        data_settings,
        "SCREENING_STRATEGIES_ROOT",
        roots["screening_strategies"],
    )

    migrated = data_settings.prepare_workspace()

    assert set(migrated) == set(roots)
    assert (roots["data"] / "legacy.txt").read_text(encoding="utf-8") == "data"
    assert (roots["strategies"] / "builtin" / "strategy.yaml").exists()
    assert not (tmp_path / "data").exists()


def test_legacy_desktop_files_migrate_to_external_runtime_directory(tmp_path):
    legacy_dir = tmp_path / "src" / "desktop"
    runtime_dir = tmp_path / "data" / "desktop"
    legacy_dir.mkdir(parents=True)
    legacy_config = legacy_dir / "config.json"
    legacy_history = legacy_dir / "chat_history.json"
    config_payload = '{"llm_model":"test-model"}'
    history_payload = '[{"role":"user","content":"hello","timestamp":1}]'
    legacy_config.write_text(config_payload, encoding="utf-8")
    legacy_history.write_text(history_payload, encoding="utf-8")

    migrated = runtime.prepare_runtime_files(
        config_path=runtime_dir / "config.json",
        history_path=runtime_dir / "chat_history.json",
        legacy_config_path=legacy_config,
        legacy_history_path=legacy_history,
    )

    assert migrated == {"config": True, "history": True}
    assert (runtime_dir / "config.json").read_text(encoding="utf-8") == config_payload
    assert (runtime_dir / "chat_history.json").read_text(encoding="utf-8") == history_payload
    assert not legacy_config.exists()
    assert not legacy_history.exists()


def test_chat_histories_are_independent_and_legacy_file_is_upgraded(tmp_path):
    config_path = tmp_path / "config.json"
    history_path = tmp_path / "chat_history.json"
    legacy_messages = [
        {"role": "user", "content": "legacy", "timestamp": 1.0},
    ]
    history_path.write_text(
        json.dumps(legacy_messages, ensure_ascii=False),
        encoding="utf-8",
    )

    try:
        chat.set_config(config_path, tmp_path, history_path)
        assert asyncio.run(chat.get_history("qualitative:analysis")) == legacy_messages

        chat._histories["infrastructure:datasources"] = [
            {"role": "user", "content": "data", "timestamp": 2.0},
        ]
        chat._save_history()
        chat._load_history()

        assert asyncio.run(chat.get_history("qualitative:analysis"))[0]["content"] == "legacy"
        assert (
            asyncio.run(chat.get_history("infrastructure:datasources"))[0]["content"]
            == "data"
        )

        asyncio.run(chat.clear_history("infrastructure:datasources"))
        assert asyncio.run(chat.get_history("infrastructure:datasources")) == []
        assert len(asyncio.run(chat.get_history("qualitative:analysis"))) == 1

        stored = json.loads(history_path.read_text(encoding="utf-8"))
        assert stored["version"] == 1
        assert set(stored["conversations"]) == {"qualitative:analysis"}
    finally:
        chat._histories = {}
        chat._history_path = None
