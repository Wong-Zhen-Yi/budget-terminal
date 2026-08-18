from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import budget_terminal_app.main as main_module


def test_old_yfinance_runtime_is_rejected() -> None:
    with patch.object(main_module.yf, "__version__", "1.2.0"):
        try:
            main_module._validate_market_data_runtime()
        except RuntimeError as exc:
            assert "requires yfinance 1.5.2 or newer" in str(exc)
            assert ".venv" in str(exc)
        else:
            raise AssertionError("unsupported yfinance runtime was accepted")


def test_supported_yfinance_runtime_is_accepted() -> None:
    with patch.object(main_module.yf, "__version__", "1.5.2"):
        assert main_module._validate_market_data_runtime() == "1.5.2"


if __name__ == "__main__":
    test_old_yfinance_runtime_is_rejected()
    test_supported_yfinance_runtime_is_accepted()
    print("runtime dependency guard tests passed")
