"""
Agent 1 — Market Analysis Agent
================================
Scans a list of symbols on the 5-minute timeframe and looks for
trendline break-and-retest setups.

Strategy (LONG):
  1. Fit a downtrend line through recent swing highs (negative slope).
  2. Detect when price closes *above* the trendline (breakout bar).
  3. Record the highest high made after the break (breakout high).
  4. Wait for price to pull back to within RETRACEMENT_TOLERANCE of the trendline.
  5. Signal BUY when price closes above the trendline again (bounce confirmed)
     and is heading back toward the breakout high.
  Stop  = 0.2% below the lowest low since the breakout bar.
  Target = the breakout high.

Strategy (SHORT) is the exact mirror.

Output: list of TradeSignal dataclass objects with confidence scores.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from config.settings import LOOKBACK_BARS, RETRACEMENT_TOLERANCE, SWING_LOOKBACK
from utils.data_fetcher import DataFetcher
from utils.logger import setup_logger

logger = setup_logger(__name__)

_NY = ZoneInfo("America/New_York")


# ── Public data structures ────────────────────────────────────────────────────

@dataclass
class TradeSignal:
    symbol: str
    signal_type: str       # "BUY" | "SELL"
    entry_price: float
    stop_loss: float
    take_profit: float
    confidence: float      # 0.0 – 1.0
    timestamp: str
    reason: str
    timeframe: str = "5Min"


# ── Agent ─────────────────────────────────────────────────────────────────────

class MarketAnalysisAgent:
    """
    Stateless per-scan trendline break-and-retest detector.
    Call scan_symbols() each cycle to receive fresh TradeSignal objects.
    """

    def __init__(self) -> None:
        self._fetcher = DataFetcher()

    def scan_symbols(self, symbols: List[str]) -> List[TradeSignal]:
        """Return all valid trade signals across the provided symbols."""
        signals: List[TradeSignal] = []
        for sym in symbols:
            sig = self._analyze(sym)
            if sig:
                signals.append(sig)
        return signals

    # ── Core analysis ─────────────────────────────────────────────────────────

    def _analyze(self, symbol: str) -> Optional[TradeSignal]:
        df = self._fetcher.get_bars(symbol, limit=LOOKBACK_BARS)
        if df is None or len(df) < 30:
            logger.debug(f"{symbol}: insufficient data ({0 if df is None else len(df)} bars)")
            return None

        sig = self._check_long_setup(symbol, df)
        if sig:
            return sig
        return self._check_short_setup(symbol, df)

    # ── Long setup ────────────────────────────────────────────────────────────

    def _check_long_setup(self, symbol: str, df: pd.DataFrame) -> Optional[TradeSignal]:
        """
        Downtrend trendline → price breaks above → retraces → bounces → BUY.
        """
        highs  = df["high"].values
        lows   = df["low"].values
        closes = df["close"].values
        n = len(df)

        # 1. Find swing highs and fit downtrend line
        sh_idx = _swing_points(highs, SWING_LOOKBACK, is_high=True)
        if len(sh_idx) < 2:
            return None

        slope, intercept = _fit_line(sh_idx[-3:], highs[sh_idx[-3:]])
        if slope is None or slope >= 0:
            return None  # Need a negative slope (downtrend)

        # 2. Find a breakout candle (close crosses above trendline) in last 1–10 bars
        breakout_bar: Optional[int] = None
        for lookback in range(1, min(11, n)):
            i_prev = n - 1 - lookback
            i_curr = n - lookback
            tl_prev = slope * i_prev + intercept
            tl_curr = slope * i_curr + intercept
            if closes[i_prev] < tl_prev and closes[i_curr] >= tl_curr:
                breakout_bar = i_curr
                break

        if breakout_bar is None:
            return None

        bars_since = (n - 1) - breakout_bar
        if bars_since < 1:
            return None  # Need at least 1 bar after the break

        # 3. Breakout high = highest high from breakout bar to now
        breakout_high = float(highs[breakout_bar:].max())

        # 4. Retracement check — lowest low since break must touch trendline zone
        tl_now = slope * (n - 1) + intercept
        retest_zone_top = tl_now * (1.0 + RETRACEMENT_TOLERANCE)
        retest_low = float(lows[breakout_bar:].min())

        if retest_low > retest_zone_top:
            return None  # Never pulled back to trendline

        # 5. Current close must be above trendline (bounce confirmed)
        current_close = float(closes[-1])
        if current_close < tl_now * (1.0 - RETRACEMENT_TOLERANCE):
            return None  # Closed back below trendline — setup invalidated

        # 6. Build signal
        entry  = current_close
        stop   = round(retest_low * (1.0 - 0.002), 2)   # 0.2% below retest low
        target = round(breakout_high, 2)

        risk   = entry - stop
        reward = target - entry
        if risk <= 0 or reward <= 0:
            return None

        rr = reward / risk
        confidence = _confidence(rr, bars_since)

        logger.info(
            f"{symbol} LONG  entry={entry:.2f}  stop={stop:.2f}  "
            f"target={target:.2f}  R:R={rr:.1f}  conf={confidence:.0%}"
        )
        return TradeSignal(
            symbol=symbol,
            signal_type="BUY",
            entry_price=round(entry, 2),
            stop_loss=stop,
            take_profit=target,
            confidence=confidence,
            timestamp=datetime.now(_NY).isoformat(),
            reason=(
                f"Downtrend trendline break-and-retest | "
                f"R:R {rr:.1f}:1 | {bars_since} bars post-break"
            ),
        )

    # ── Short setup ───────────────────────────────────────────────────────────

    def _check_short_setup(self, symbol: str, df: pd.DataFrame) -> Optional[TradeSignal]:
        """
        Uptrend trendline → price breaks below → retraces → rejection → SELL.
        """
        highs  = df["high"].values
        lows   = df["low"].values
        closes = df["close"].values
        n = len(df)

        sl_idx = _swing_points(lows, SWING_LOOKBACK, is_high=False)
        if len(sl_idx) < 2:
            return None

        slope, intercept = _fit_line(sl_idx[-3:], lows[sl_idx[-3:]])
        if slope is None or slope <= 0:
            return None  # Need positive slope (uptrend)

        breakdown_bar: Optional[int] = None
        for lookback in range(1, min(11, n)):
            i_prev = n - 1 - lookback
            i_curr = n - lookback
            tl_prev = slope * i_prev + intercept
            tl_curr = slope * i_curr + intercept
            if closes[i_prev] > tl_prev and closes[i_curr] <= tl_curr:
                breakdown_bar = i_curr
                break

        if breakdown_bar is None:
            return None

        bars_since = (n - 1) - breakdown_bar
        if bars_since < 1:
            return None

        breakdown_low = float(lows[breakdown_bar:].min())

        tl_now = slope * (n - 1) + intercept
        retest_zone_bot = tl_now * (1.0 - RETRACEMENT_TOLERANCE)
        retest_high = float(highs[breakdown_bar:].max())

        if retest_high < retest_zone_bot:
            return None  # Never pulled back to trendline

        current_close = float(closes[-1])
        if current_close > tl_now * (1.0 + RETRACEMENT_TOLERANCE):
            return None  # Closed back above trendline — invalidated

        entry  = current_close
        stop   = round(retest_high * (1.0 + 0.002), 2)
        target = round(breakdown_low, 2)

        risk   = stop - entry
        reward = entry - target
        if risk <= 0 or reward <= 0:
            return None

        rr = reward / risk
        confidence = _confidence(rr, bars_since)

        logger.info(
            f"{symbol} SHORT entry={entry:.2f}  stop={stop:.2f}  "
            f"target={target:.2f}  R:R={rr:.1f}  conf={confidence:.0%}"
        )
        return TradeSignal(
            symbol=symbol,
            signal_type="SELL",
            entry_price=round(entry, 2),
            stop_loss=stop,
            take_profit=target,
            confidence=confidence,
            timestamp=datetime.now(_NY).isoformat(),
            reason=(
                f"Uptrend trendline break-and-retest | "
                f"R:R {rr:.1f}:1 | {bars_since} bars post-break"
            ),
        )


# ── Module-level helpers ──────────────────────────────────────────────────────

def _swing_points(prices: np.ndarray, lookback: int, is_high: bool) -> List[int]:
    """
    Return bar indices where prices[i] is the local max (is_high=True) or min.
    A point qualifies when it is strictly the extreme over
    [i-lookback … i+lookback] AND is strictly higher/lower than both neighbours.
    """
    n = len(prices)
    result: List[int] = []
    for i in range(lookback, n - lookback):
        window = prices[i - lookback : i + lookback + 1]
        if is_high:
            if (
                prices[i] == window.max()
                and prices[i] > prices[i - 1]
                and prices[i] > prices[i + 1]
            ):
                result.append(i)
        else:
            if (
                prices[i] == window.min()
                and prices[i] < prices[i - 1]
                and prices[i] < prices[i + 1]
            ):
                result.append(i)
    return result


def _fit_line(
    indices: List[int], prices: np.ndarray
) -> Tuple[Optional[float], Optional[float]]:
    """Linear regression through (index, price) pairs → (slope, intercept)."""
    if len(indices) < 2:
        return None, None
    try:
        x = np.array(indices, dtype=float)
        y = np.array(prices, dtype=float)
        slope, intercept = np.polyfit(x, y, 1)
        return float(slope), float(intercept)
    except Exception:
        return None, None


def _confidence(rr: float, bars_since_breakout: int) -> float:
    """
    Heuristic confidence score (0–1).
    Higher R:R and fewer bars since the breakout increase confidence.
    """
    rr_component   = min(0.45, (rr - 1.0) * 0.15)
    recency_bonus  = 0.1 / max(bars_since_breakout, 1)
    score = 0.50 + rr_component + recency_bonus
    return round(min(0.95, max(0.30, score)), 2)
