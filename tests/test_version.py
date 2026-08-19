from pathlib import Path

from src.desktop.api.main import app
from src.version import DISPLAY_VERSION, RELEASE_STAGE, __version__


PROJECT_ROOT = Path(__file__).parents[1]


def test_beta_version_is_shared_by_api_and_frontend():
    assert __version__ == "0.1.0"
    assert RELEASE_STAGE == "Beta"
    assert DISPLAY_VERSION == "Beta v0.1.0"
    assert app.version == __version__

    app_source = (PROJECT_ROOT / "src/desktop/frontend/js/app.js").read_text(encoding="utf-8")
    settings_source = (
        PROJECT_ROOT / "src/desktop/frontend/js/pages/settings.js"
    ).read_text(encoding="utf-8")
    assert "appInfo.display_version" in app_source
    assert "settings.app_display_version" in settings_source
    assert "v1.0.0" not in app_source
    assert "1.0.0</span>" not in settings_source


def test_package_and_release_build_derive_version_from_source_module():
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    build_script = (PROJECT_ROOT / "scripts/build_windows.ps1").read_text(encoding="utf-8")

    assert 'dynamic = ["version"]' in pyproject
    assert 'version = { attr = "src.version.__version__" }' in pyproject
    assert 'src\\version.py' in build_script
    assert "ThesisBacktester-$releaseStageSlug-v$version-windows-x64" in build_script
