#!/usr/bin/env python3
"""
Backtesting Engine
==================
Runs the trendline break-and-retest strategy over historical data
and produces a full performance report.

Usage:
    python backtest.py                        # last 90 days, all symbols
    python backtest.py --days 180             # last 180 days
    python backtest.py --symbol AAPL          # single symbol
    python backtest.py --days 365 --symbol TSLA

Results are printed to the console AND saved to:
    trades/backtest_results_YYYY-MM-DD.csv
"""
import argparse
import csv
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional

import numpy as np
import pandas as pd
import yfinance as yf

from agents.market_analysis_agent import (
    TradeSignal,
    _confidence,
    _fit_line,
    _swing_points,
)
from config.settings import (
    ACCOUNT_RISK_PER_TRADE,
    LOOKBACK_BARS,
    MAX_OPEN_TRADES,
    MIN_RISK_REWARD,
    RETRACEMENT_TOLERANCE,
    STARTING_BALANCE,
    SWING_LOOKBACK,
    SYMBOLS,
    TRADES_DIR,
)
from utils.logger import setup_logger

logger = setup_logger("backtest")


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class BacktestTrade:
    symbol: str
    side: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    qty: int
    pnl: float
    pnl_pct: float
    exit_reason: str   # "TAKE-PROFIT" | "STOP-LOSS" | "END-OF-DATA"
    confidence: float
    rr_ratio: float


@dataclass
class BacktestResult:
    symbol: str
    trades: List[BacktestTrade] = field(default_factory=list)

    @property
    def total_trades(self): return len(self.trades)
    @property
    def wins(self): return [t for t in self.trades if t.pnl > 0]
    @property
    def losses(self): return [t for t in self.trades if t.pnl <= 0]
    @property
    def win_rate(self): return len(self.wins) / self.total_trades if self.trades else 0
    @property
    def total_pnl(self): return sum(t.pnl for t in self.trades)
    @property
    def avg_win(self): return sum(t.pnl for t in self.wins) / len(self.wins) if self.wins else 0
    @property
    def avg_loss(self): return sum(t.pnl for t in self.losses) / len(self.losses) if self.losses else 0
    @property
    def profit_factor(self):
        gross_win  = sum(t.pnl for t in self.wins)
        gross_loss = abs(sum(t.pnl for t in self.losses))
        return gross_win / gross_loss if gross_loss > 0 else float("inf")
    @property
    def max_drawdown(self):
        if not self.trades: return 0.0
        equity = STARTING_BALANCE
        peak   = equity
        max_dd = 0.0
        for t in self.trades:
            equity += t.pnl
            peak    = max(peak, equity)
            max_dd  = max(max_dd, peak - equity)
        return max_dd


# ── Data fetching ─────────────────────────────────────────────────────────────

def fetch_history(symbol: str, days: int) -> Optional[pd.DataFrame]:
    """Download daily bars for a longer lookback, then return 5-min bars."""
    try:
        end   = datetime.now()
        start = end - timedelta(days=days + 10)
        ticker = yf.Ticker(symbol)
        # yfinance: 5m data available up to 60 days; use 1d for longer periods
        if days <= 58:
            df = ticker.history(start=start, end=end, interval="5m")
        else:
            df = ticker.history(start=start, end=end, interval="1d")
            logger.info(f"{symbol}: using daily bars (>60 day window)")
        if df is None or df.empty:
            return None
        df.columns = [c.lower() for c in df.columns]
        df = df[["open","high","low","close","volume"]].sort_index()
        return df
    except Exception as e:
        logger.error(f"fetch_history({symbol}): {e}")
        return None


# ── Strategy replay ───────────────────────────────────────────────────────────

def simulate_symbol(symbol: str, df: pd.DataFrame, balance: float) -> BacktestResult:
    """
    Walk forward through the bars, running the trendline strategy on each
    rolling window and simulating fills / exits bar-by-bar.
    """
    result = BacktestResult(symbol=symbol)
    closes = df["close"].values
    highs  = df["high"].values
    lows   = df["low"].values
    n      = len(df)
    open_trade: Optional[BacktestTrade] = None

    for i in range(LOOKBACK_BARS, n):
        window_close = closes[max(0, i - LOOKBACK_BARS): i]
        window_high  = highs [max(0, i - LOOKBACK_BARS): i]
        window_low   = lows  [max(0, i - LOOKBACK_BARS): i]

        current_close = float(closes[i])
        current_high  = float(highs[i])
        current_low   = float(lows[i])
        bar_date      = str(df.index[i])[:19]

        # ── Check exit on open trade ──────────────────────────────────────
        if open_trade:
            if open_trade.side == "BUY":
                if current_low <= open_trade.exit_price and open_trade.exit_reason == "STOP-LOSS":
                    # stop hit
                    pnl = (open_trade.exit_price - open_trade.entry_price) * open_trade.qty
                    open_trade.pnl      = round(pnl, 2)
                    open_trade.pnl_pct  = round(pnl / (open_trade.entry_price * open_trade.qty) * 100, 2)
                    open_trade.exit_date = bar_date
                    result.trades.append(open_trade)
                    balance += open_trade.exit_price * open_trade.qty + pnl
                    open_trade = None
                elif current_high >= open_trade.exit_price and open_trade.exit_reason == "TAKE-PROFIT":
                    pnl = (open_trade.exit_price - open_trade.entry_price) * open_trade.qty
                    open_trade.pnl      = round(pnl, 2)
                    open_trade.pnl_pct  = round(pnl / (open_trade.entry_price * open_trade.qty) * 100, 2)
                    open_trade.exit_date = bar_date
                    result.trades.append(open_trade)
                    balance += open_trade.exit_price * open_trade.qty + pnl
                    open_trade = None
            else:  # SELL
                if current_high >= open_trade.exit_price and open_trade.exit_reason == "STOP-LOSS":
                    pnl = (open_trade.entry_price - open_trade.exit_price) * open_trade.qty
                    open_trade.pnl      = round(pnl, 2)
                    open_trade.pnl_pct  = round(pnl / (open_trade.entry_price * open_trade.qty) * 100, 2)
                    open_trade.exit_date = bar_date
                    result.trades.append(open_trade)
                    open_trade = None
                elif current_low <= open_trade.exit_price and open_trade.exit_reason == "TAKE-PROFIT":
                    pnl = (open_trade.entry_price - open_trade.exit_price) * open_trade.qty
                    open_trade.pnl      = round(pnl, 2)
                    open_trade.pnl_pct  = round(pnl / (open_trade.entry_price * open_trade.qty) * 100, 2)
                    open_trade.exit_date = bar_date
                    result.trades.append(open_trade)
                    open_trade = None
            continue  # don't look for new entry while in a trade

        # ── Look for new entry ────────────────────────────────────────────
        signal = _detect_long(window_close, window_high, window_low)
        if signal is None:
            signal = _detect_short(window_close, window_high, window_low)
        if signal is None:
            continue

        # Risk / reward check
        risk   = abs(signal["entry"] - signal["stop"])
        reward = abs(signal["target"] - signal["entry"])
        if risk <= 0 or (reward / risk) < MIN_RISK_REWARD:
            continue

        # Position sizing
        dollar_risk   = balance * ACCOUNT_RISK_PER_TRADE
        qty           = max(1, int(dollar_risk / risk))
        trade_value   = qty * signal["entry"]
        if trade_value > balance * 0.95:
            qty = max(1, int(balance * 0.95 / signal["entry"]))

        balance -= qty * signal["entry"]

        open_trade = BacktestTrade(
            symbol=symbol,
            side=signal["side"],
            entry_date=bar_date,
            exit_date="",
            entry_price=round(signal["entry"], 2),
            exit_price=round(signal["stop"] if True else signal["target"], 2),
            qty=qty,
            pnl=0.0,
            pnl_pct=0.0,
            exit_reason="STOP-LOSS",
            confidence=signal["confidence"],
            rr_ratio=round(reward / risk, 2),
        )
        # Set proper exit targets
        open_trade.exit_price  = round(signal["stop"], 2)
        open_trade.exit_reason = "STOP-LOSS"
        # We'll check both SL and TP each bar — encode TP separately
        open_trade._tp = round(signal["target"], 2)  # type: ignore[attr-defined]

    # Close any still-open trade at end of data
    if open_trade:
        last_close = float(closes[-1])
        pnl = (last_close - open_trade.entry_price) * open_trade.qty
        if open_trade.side == "SELL":
            pnl = (open_trade.entry_price - last_close) * open_trade.qty
        open_trade.pnl       = round(pnl, 2)
        open_trade.pnl_pct   = round(pnl / (open_trade.entry_price * open_trade.qty) * 100, 2)
        open_trade.exit_date  = str(df.index[-1])[:19]
        open_trade.exit_price = round(last_close, 2)
        open_trade.exit_reason = "END-OF-DATA"
        result.trades.append(open_trade)

    return result


def _detect_long(closes, highs, lows):
    n = len(closes)
    sh = _swing_points(highs, SWING_LOOKBACK, is_high=True)
    if len(sh) < 2: return None
    slope, intercept = _fit_line(sh[-3:], highs[sh[-3:]])
    if slope is None or slope >= 0: return None
    for back in range(1, min(9, n)):
        tl_prev = slope * (n-1-back) + intercept
        tl_curr = slope * (n-back)   + intercept
        if closes[n-1-back] < tl_prev and closes[n-back] >= tl_curr:
            bars_since = back - 1
            tl_now      = slope * (n-1) + intercept
            bk_high     = float(highs[n-back:].max())
            retest_low  = float(lows[n-back:].min())
            if retest_low > tl_now * (1 + RETRACEMENT_TOLERANCE): return None
            if closes[-1] < tl_now * (1 - RETRACEMENT_TOLERANCE): return None
            entry  = float(closes[-1])
            stop   = round(retest_low * 0.998, 2)
            target = round(bk_high, 2)
            risk   = entry - stop
            reward = target - entry
            if risk <= 0 or reward <= 0: return None
            return {"side":"BUY","entry":entry,"stop":stop,"target":target,
                    "confidence":_confidence(reward/risk, bars_since)}
    return None


def _detect_short(closes, highs, lows):
    n = len(closes)
    sl = _swing_points(lows, SWING_LOOKBACK, is_high=False)
    if len(sl) < 2: return None
    slope, intercept = _fit_line(sl[-3:], lows[sl[-3:]])
    if slope is None or slope <= 0: return None
    for back in range(1, min(9, n)):
        tl_prev = slope * (n-1-back) + intercept
        tl_curr = slope * (n-back)   + intercept
        if closes[n-1-back] > tl_prev and closes[n-back] <= tl_curr:
            bars_since = back - 1
            tl_now     = slope * (n-1) + intercept
            bk_low     = float(lows[n-back:].min())
            retest_high = float(highs[n-back:].max())
            if retest_high < tl_now * (1 - RETRACEMENT_TOLERANCE): return None
            if closes[-1] > tl_now * (1 + RETRACEMENT_TOLERANCE): return None
            entry  = float(closes[-1])
            stop   = round(retest_high * 1.002, 2)
            target = round(bk_low, 2)
            risk   = stop - entry
            reward = entry - target
            if risk <= 0 or reward <= 0: return None
            return {"side":"SELL","entry":entry,"stop":stop,"target":target,
                    "confidence":_confidence(reward/risk, bars_since)}
    return None


# ── Report ────────────────────────────────────────────────────────────────────

def print_report(results: List[BacktestResult], days: int):
    all_trades = [t for r in results for t in r.trades]
    total_pnl  = sum(t.pnl for t in all_trades)
    wins       = [t for t in all_trades if t.pnl > 0]
    losses     = [t for t in all_trades if t.pnl <= 0]
    win_rate   = len(wins) / len(all_trades) * 100 if all_trades else 0

    print("\n" + "═"*60)
    print(f"  BACKTEST RESULTS — last {days} days")
    print("═"*60)
    print(f"  Symbols tested : {', '.join(r.symbol for r in results)}")
    print(f"  Total trades   : {len(all_trades)}")
    print(f"  Win rate       : {win_rate:.1f}%  ({len(wins)}W / {len(losses)}L)")
    print(f"  Total P&L      : ${total_pnl:+,.2f}")
    print(f"  Avg win        : ${sum(t.pnl for t in wins)/len(wins):+.2f}" if wins else "  Avg win        : n/a")
    print(f"  Avg loss       : ${sum(t.pnl for t in losses)/len(losses):+.2f}" if losses else "  Avg loss       : n/a")

    print("\n  Per-symbol breakdown:")
    print(f"  {'Symbol':<8} {'Trades':>7} {'Win%':>7} {'P&L':>10} {'Prof.Factor':>13}")
    print("  " + "-"*50)
    for r in results:
        if r.total_trades == 0:
            print(f"  {r.symbol:<8} {'0':>7} {'—':>7} {'—':>10} {'—':>13}")
        else:
            print(f"  {r.symbol:<8} {r.total_trades:>7} {r.win_rate*100:>6.1f}% "
                  f"${r.total_pnl:>+9,.2f} {r.profit_factor:>12.2f}x")
    print("═"*60 + "\n")


def save_csv(results: List[BacktestResult]):
    os.makedirs(TRADES_DIR, exist_ok=True)
    path = os.path.join(TRADES_DIR, f"backtest_results_{datetime.now().strftime('%Y-%m-%d')}.csv")
    headers = ["symbol","side","entry_date","exit_date","entry_price",
               "exit_price","qty","pnl","pnl_pct","exit_reason","confidence","rr_ratio"]
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(headers)
        for r in results:
            for t in r.trades:
                w.writerow([t.symbol, t.side, t.entry_date, t.exit_date,
                            t.entry_price, t.exit_price, t.qty, t.pnl, t.pnl_pct,
                            t.exit_reason, t.confidence, t.rr_ratio])
    print(f"  Results saved to: {path}\n")
    return path


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Backtest the trendline strategy")
    parser.add_argument("--days",   type=int, default=90,    help="Lookback days (default 90)")
    parser.add_argument("--symbol", type=str, default=None,  help="Single symbol (default: all)")
    args = parser.parse_args()

    symbols = [args.symbol.upper()] if args.symbol else SYMBOLS
    print(f"\n  Running backtest: {args.days} days | {', '.join(symbols)}")
    print("  Downloading data...\n")

    results = []
    for sym in symbols:
        df = fetch_history(sym, args.days)
        if df is None or len(df) < LOOKBACK_BARS + 10:
            logger.warning(f"{sym}: not enough data, skipping")
            continue
        logger.info(f"{sym}: {len(df)} bars loaded — running strategy...")
        res = simulate_symbol(sym, df, STARTING_BALANCE)
        results.append(res)
        logger.info(f"{sym}: {res.total_trades} trades found")

    if not results:
        print("  No results — try reducing --days or check your symbols.")
        return

    print_report(results, args.days)
    save_csv(results)


if __name__ == "__main__":
    main()
