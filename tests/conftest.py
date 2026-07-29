import pytest


@pytest.fixture(autouse=True)
def _no_update_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POCKETROCKS_SKIP_VERSION_CHECK", "1")
