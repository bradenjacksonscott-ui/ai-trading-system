"""
Market data fetcher — uses yfinance (Yahoo Finance).
No API key or account required. Completely free.
Fetches 5-minute OHLCV bars for a given symbol.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd
import yfinance as yf

from config.settings import LOOKBACK_BARS
from utils.logger import setup_logger

logger = setup_logger(__name__)


class DataFetcher:
    """Fetches 5-minute bars from Yahoo Finance via yfinance."""

    def get_bars(self, symbol: str, limit: int = LOOKBACK_BARS) -> Optional[pd.DataFrame]:
        """
        Fetch the most recent `limit` 5-minute bars for `symbol`.

        Returns a DataFrame indexed by timestamp with columns:
          open, high, low, close, volume
        Returns None if the request fails or no data is available.

        Note: yfinance provides up to 60 days of 5-minute data.
        """
        try:
            ticker = yf.Ticker(symbol)
            # period="5d" gives enough bars; interval="5m" = 5-minute candles
            df = ticker.history(period="5d", interval="5m")

            if df is None or df.empty:
                logger.warning(f"No bar data returned for {symbol}")
                return None

            # Normalise column names to lowercase
            df.columns = [c.lower() for c in df.columns]

            # Keep standard OHLCV columns only
            ohlcv = [c for c in ("open", "high", "low", "close", "volume") if c in df.columns]
            df = df[ohlcv].copy()

            df.index.name = "timestamp"
            df = df.sort_index()

            return df.tail(limit)

        except Exception as exc:
            logger.error(f"DataFetcher.get_bars({symbol}): {exc}")
            return None
