import time

import pytest

from market import symbols

# A tiny stand-in for Nasdaq's symbol directory, so no test ever downloads it.
FIXTURE_LISTINGS = [
    {"symbol": "AAPL", "name": "Apple Inc.", "exchange": "Nasdaq", "etf": False, "main_board": True},
    {"symbol": "AMAT", "name": "Applied Materials, Inc.", "exchange": "Nasdaq", "etf": False, "main_board": True},
    {"symbol": "APLE", "name": "Apple Hospitality REIT, Inc.", "exchange": "NYSE", "etf": False, "main_board": True},
    {"symbol": "MLGO", "name": "MicroAlgo, Inc.", "exchange": "Nasdaq", "etf": False, "main_board": False},
    {"symbol": "BRKC", "name": "YieldMax BRK.B Option Income Strategy ETF", "exchange": "NYSE Arca", "etf": True, "main_board": False},
    {"symbol": "BRK-B", "name": "Berkshire Hathaway Inc.", "exchange": "NYSE", "etf": False, "main_board": True},
    {"symbol": "MSFT", "name": "Microsoft Corporation", "exchange": "Nasdaq", "etf": False, "main_board": True},
    {"symbol": "NVDA", "name": "NVIDIA Corporation", "exchange": "Nasdaq", "etf": False, "main_board": True},
    {"symbol": "SPY", "name": "SPDR S&P 500 ETF Trust", "exchange": "NYSE Arca", "etf": True, "main_board": False},
]


def load_listings(monkeypatch, rows):
    monkeypatch.setattr(symbols, "_rows", list(rows))
    monkeypatch.setattr(symbols, "_by_symbol", {r["symbol"]: r for r in rows})
    monkeypatch.setattr(symbols, "_loaded_at", time.monotonic())
    monkeypatch.setattr(symbols, "_failed_at", 0.0)


@pytest.fixture(autouse=True)
def _symbol_directory(monkeypatch):
    load_listings(monkeypatch, FIXTURE_LISTINGS)
