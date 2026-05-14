import os
import sys

import pandas as pd
import pytest

# Add repo root to sys.path so tests can import entry, modules.*, etc.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


@pytest.fixture(scope="module")
def backtest_results():
    path = os.path.join(DATA_DIR, "QQQ_backtest_results.csv")
    if not os.path.exists(path):
        pytest.skip(f"QQQ_backtest_results.csv not found — run backtest.py first")
    return pd.read_csv(path, index_col="date", parse_dates=True)


@pytest.fixture(scope="module")
def df_qqq():
    path = os.path.join(DATA_DIR, "QQQ_indicators.csv")
    if not os.path.exists(path):
        pytest.skip(f"QQQ_indicators.csv not found — run indicators.py first")
    df = pd.read_csv(path, index_col=0, parse_dates=True).sort_index()
    df.drop(columns=[c for c in ("Ticker", "Adj Close") if c in df.columns], inplace=True)
    return df
