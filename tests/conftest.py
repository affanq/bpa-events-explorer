import pytest

from bpa_app import config


@pytest.fixture(autouse=True)
def cortex_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "CORTEX_BASE_URL", "https://cortex.example.test")
