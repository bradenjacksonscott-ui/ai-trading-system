"""
Market data fetcher — wraps the Alpaca StockHistoricalDataClient.
Fetches 5-minute OHLCV bars for a given symbol.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from config.settings import ALPACA_API_KEY, ALPACA_SECRET_KEY, LOOKBACK_BARS
from utils.logger import setup_logger

logger = setup_logger(__name__)

_NY = ZoneInfo("America/New_York")


class DataFetcher:
    """Thin wrapper around Alpaca's market-data API for 5-minute bars."""

    def __init__(self) -> None:
        if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
            raise ValueError(
                "ALPACA_API_KEY and ALPACA_SECRET_KEY must be set in your .env file."
            )
        self._client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)
        self._tf = TimeFrame(5, TimeFrameUnit.Minute)

    def get_bars(self, symbol: str, limit: int = LOOKBACK_BARS) -> Optional[pd.DataFrame]:
        """
        Fetch the most recent `limit` 5-minute bars for `symbol`.

        Returns a DataFrame indexed by timestamp with columns:
          open, high, low, close, volume
        Returns None if the request fails or no data is available.
        """
        try:
            end = datetime.now(_NY)
            start = end - timedelta(days=10)  # Extra window to cover weekends/holidays

            req = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=self._tf,
                start=start,
                end=end,
            )
            resp = self._client.get_stock_bars(req)
            df: pd.DataFrame = resp.df

            if df is None or df.empty:
                logger.warning(f"No bar data returned for {symbol}")
                return None

            # alpaca-py returns a MultiIndex (symbol, timestamp); drop the symbol level
            if isinstance(df.index, pd.MultiIndex):
                level_vals = df.index.get_level_values(0)
                if symbol not in level_vals:
                    logger.warning(f"{symbol} not found in response index")
                    return None
                df = df.xs(symbol, level=0)

            df = df.sort_index()
            df.index.name = "timestamp"

            # Keep standard OHLCV columns only
            ohlcv = [c for c in ("open", "high", "low", "close", "volume") if c in df.columns]
            return df[ohlcv].tail(limit).copy()

        except Exception as exc:
            logger.error(f"DataFetcher.get_bars({symbol}): {exc}")
            return None
