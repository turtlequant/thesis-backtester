import json

from src.data import config


def test_data_config_defaults_and_persistence(tmp_path, monkeypatch):
    config_path = tmp_path / "data_config.json"
    monkeypatch.setattr(config, "DATA_CONFIG_PATH", config_path)
    for key in ("DATA_PROVIDER", "TUSHARE_TOKEN", "DATA_START_DATE"):
        monkeypatch.delenv(key, raising=False)

    assert config.load_data_config()["provider"] == "baostock"

    saved = config.save_data_config(
        {
            "provider": "tushare",
            "tushare_token": "secret-token",
            "auto_update_enabled": True,
        }
    )

    assert saved["provider"] == "tushare"
    assert json.loads(config_path.read_text(encoding="utf-8"))["tushare_token"] == "secret-token"


def test_environment_overrides_file_config(tmp_path, monkeypatch):
    config_path = tmp_path / "data_config.json"
    config_path.write_text('{"provider": "baostock"}', encoding="utf-8")
    monkeypatch.setattr(config, "DATA_CONFIG_PATH", config_path)
    monkeypatch.setenv("DATA_PROVIDER", "akshare")

    assert config.load_data_config()["provider"] == "akshare"
