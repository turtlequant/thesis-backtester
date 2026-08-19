import asyncio

from src.data import config
from src.desktop import network_access
from src.desktop.api.routers import settings
from src.version import DISPLAY_VERSION, RELEASE_STAGE, __version__


def test_app_identity_is_exposed_from_the_canonical_version_module():
    result = asyncio.run(settings.get_app_info())

    assert result["version"] == __version__
    assert result["release_stage"] == RELEASE_STAGE
    assert result["display_version"] == DISPLAY_VERSION

    full_settings = asyncio.run(settings.get_settings())
    assert full_settings["app_display_version"] == DISPLAY_VERSION


def test_settings_masks_data_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_CONFIG_PATH", tmp_path / "data_config.json")
    for key in ("DATA_PROVIDER", "TUSHARE_TOKEN", "DATA_START_DATE"):
        monkeypatch.delenv(key, raising=False)
    settings.set_config_path(tmp_path / "desktop_config.json")
    cleared_providers = []
    monkeypatch.setattr(settings, "clear_provider_cache", cleared_providers.append)

    result = asyncio.run(
        settings.update_settings(
            settings.SettingsUpdate(
                data_provider="tushare",
                tushare_token="1234567890abcdef",
                auto_update_enabled=True,
                auto_update_time="18:45",
            )
        )
    )

    assert result["data_provider"] == "tushare"
    assert result["tushare_token_set"] is True
    assert result["tushare_token_masked"].startswith("1234")
    assert "tushare_token" not in result
    assert cleared_providers == ["tushare"]

    asyncio.run(
        settings.update_settings(settings.SettingsUpdate(data_provider="baostock"))
    )
    assert cleared_providers == ["tushare"]


def test_enabling_lan_access_generates_one_time_token(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_CONFIG_PATH", tmp_path / "data_config.json")
    config_path = tmp_path / "desktop_config.json"
    settings.set_config_path(config_path)
    network_access.configure_active_lan_access(False)

    try:
        result = asyncio.run(
            settings.update_settings(settings.SettingsUpdate(lan_access_enabled=True))
        )

        token = result["lan_access_token"]
        stored = config_path.read_text(encoding="utf-8")
        assert token not in stored
        assert result["lan_access_enabled"] is True
        assert result["lan_access_token_set"] is True
        assert result["lan_access_restart_required"] is True
        assert network_access.LAN_TOKEN_HASH_KEY not in asyncio.run(settings.get_settings())
    finally:
        network_access.clear_active_lan_access()
