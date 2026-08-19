import asyncio

from src.desktop.api.routers import datasources


class _TestProvider:
    def __init__(self, error=None):
        self.error = error
        self.calls = 0

    def test_connection(self):
        self.calls += 1
        if self.error:
            raise self.error
        return {"success": True, "message": "连接正常"}


def test_connection_check_reuses_successful_provider(monkeypatch):
    provider = _TestProvider()
    cleared = []
    monkeypatch.setattr(datasources, "get_provider", lambda name: provider)
    monkeypatch.setattr(datasources, "clear_provider_cache", cleared.append)

    first = asyncio.run(datasources.test_provider("baostock"))
    second = asyncio.run(datasources.test_provider("baostock"))

    assert first["success"] is True
    assert second["success"] is True
    assert provider.calls == 2
    assert cleared == []


def test_connection_check_evicts_failed_provider(monkeypatch):
    provider = _TestProvider(RuntimeError("connection lost"))
    cleared = []
    monkeypatch.setattr(datasources, "get_provider", lambda name: provider)
    monkeypatch.setattr(datasources, "clear_provider_cache", cleared.append)

    result = asyncio.run(datasources.test_provider("baostock"))

    assert result["success"] is False
    assert cleared == ["baostock"]
