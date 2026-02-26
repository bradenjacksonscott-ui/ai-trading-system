"""
Agent 3 — Execution Agent (Paper Trading Simulator)
=====================================================
No brokerage account or API key required.

Simulates order execution with a virtual cash balance, tracks open positions,
monitors stop-loss / take-profit exits on every scan cycle, and journals
every trade to a daily CSV file in the trades/ directory.

Virtual account state is kept in memory for the duration of the run.
Starting balance is set via STARTING_BALANCE in your .env file.
"""
from __future__ import annotations

import csv
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from agents.market_analysis_agent import TradeSignal
from agents.risk_management_agent import ApprovedTrade
from config.settings import STARTING_BALANCE, TRADES_DIR
from utils.data_fetcher import DataFetcher
from utils.logger import setup_logger

logger = setup_logger(__name__)

_NY = ZoneInfo("America/New_York")


# ── Internal position record ──────────────────────────────────────────────────

@dataclass
class Position:
    order_id: str
    symbol: str
    side: str            # "BUY" or "SELL"
    qty: int
    entry_price: float
    stop_loss: float
    take_profit: float
    entry_time: str
    unrealized_pnl: float = 0.0


# ── Agent ─────────────────────────────────────────────────────────────────────

class ExecutionAgent:
    """
    Paper trading simulator.

    Tracks a virtual cash balance, open positions, and realised P&L.
    No external API calls for execution — all fills are simulated at the
    entry price provided by the Market Analysis Agent.
    """

    def __init__(self) -> None:
        self._cash: float = STARTING_BALANCE
        self._positions: Dict[str, Position] = {}   # order_id → Position
        self._realised_pnl_today: float = 0.0
        self._fetcher = DataFetcher()

        os.makedirs(TRADES_DIR, exist_ok=True)
        self._log_path = os.path.join(
            TRADES_DIR,
            f"trades_{datetime.now().strftime('%Y-%m-%d')}.csv",
        )
        self._init_log()

        logger.info(
            f"Paper trading simulator ready — "
            f"starting balance: ${self._cash:,.2f}"
        )

    # ── Account helpers (same interface as the Alpaca version) ────────────────

    def get_account_balance(self) -> float:
        """Return current cash balance."""
        return self._cash

    def get_open_trade_count(self) -> int:
        """Return number of currently open (simulated) positions."""
        return len(self._positions)

    def get_daily_pnl(self) -> float:
        """Return today's realised P&L plus unrealised P&L on open positions."""
        unrealised = sum(p.unrealized_pnl for p in self._positions.values())
        return self._realised_pnl_today + unrealised

    # ── Order execution ───────────────────────────────────────────────────────

    def execute_trade(self, approved: ApprovedTrade) -> Optional[Position]:
        """
        Simulate a market fill at the signal's entry price.

        Deducts the trade value from cash and opens a position with the
        supplied stop-loss and take-profit levels.
        Returns the Position object, or None if the account has insufficient funds.
        """
        signal = approved.signal
        trade_value = approved.position_size * signal.entry_price

        if trade_value > self._cash:
            logger.warning(
                f"Insufficient cash for {signal.symbol}: "
                f"need ${trade_value:.2f}, have ${self._cash:.2f}"
            )
            return None

        # Deduct cost from cash
        self._cash -= trade_value

        order_id = str(uuid.uuid4())[:8]
        pos = Position(
            order_id=order_id,
            symbol=signal.symbol,
            side=signal.signal_type,
            qty=approved.position_size,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            entry_time=datetime.now(_NY).isoformat(),
        )
        self._positions[order_id] = pos

        logger.info(
            f"SIMULATED FILL  [{signal.signal_type}] {signal.symbol} "
            f"x{approved.position_size} @ ${signal.entry_price:.2f} "
            f"| order_id={order_id}"
        )

        self._log_trade(
            approved=approved,
            order_id=order_id,
            status="FILLED (simulated)",
        )
        return pos

    # ── Position monitoring & exit management ─────────────────────────────────

    def monitor_positions(self) -> None:
        """
        Check each open position against its stop-loss and take-profit.
        Fetch the latest price via yfinance and close the position if either
        level is breached. Also logs unrealised P&L for open positions.
        """
        if not self._positions:
            logger.debug("No open positions to monitor.")
            return

        to_close: List[str] = []

        for oid, pos in self._positions.items():
            current_price = self._get_current_price(pos.symbol)
            if current_price is None:
                continue

            # Update unrealised P&L
            if pos.side == "BUY":
                pos.unrealized_pnl = (current_price - pos.entry_price) * pos.qty
                hit_stop   = current_price <= pos.stop_loss
                hit_target = current_price >= pos.take_profit
            else:  # SELL (short)
                pos.unrealized_pnl = (pos.entry_price - current_price) * pos.qty
                hit_stop   = current_price >= pos.stop_loss
                hit_target = current_price <= pos.take_profit

            sign = "+" if pos.unrealized_pnl >= 0 else ""
            logger.info(
                f"  {pos.symbol:6s} [{pos.side}] x{pos.qty} "
                f"entry={pos.entry_price:.2f}  now={current_price:.2f}  "
                f"P&L: {sign}{pos.unrealized_pnl:.2f}"
            )

            if hit_stop:
                logger.info(f"  → STOP-LOSS triggered for {pos.symbol} @ {current_price:.2f}")
                self._close_position(oid, current_price, reason="STOP-LOSS")
                to_close.append(oid)
            elif hit_target:
                logger.info(f"  → TAKE-PROFIT triggered for {pos.symbol} @ {current_price:.2f}")
                self._close_position(oid, current_price, reason="TAKE-PROFIT")
                to_close.append(oid)

        for oid in to_close:
            del self._positions[oid]

        logger.info(
            f"Account  cash=${self._cash:,.2f}  "
            f"open={len(self._positions)}  "
            f"daily P&L=${self.get_daily_pnl():+.2f}"
        )

    def _close_position(self, order_id: str, exit_price: float, reason: str) -> None:
        pos = self._positions[order_id]

        if pos.side == "BUY":
            pnl = (exit_price - pos.entry_price) * pos.qty
            proceeds = exit_price * pos.qty
        else:
            pnl = (pos.entry_price - exit_price) * pos.qty
            proceeds = pos.entry_price * pos.qty + pnl  # return margin + pnl

        self._cash += proceeds
        self._realised_pnl_today += pnl

        logger.info(
            f"CLOSED {pos.symbol} [{reason}]  "
            f"entry={pos.entry_price:.2f} exit={exit_price:.2f}  "
            f"P&L: {pnl:+.2f}  cash=${self._cash:,.2f}"
        )

        self._log_exit(pos, exit_price=exit_price, pnl=pnl, reason=reason)

    def _get_current_price(self, symbol: str) -> Optional[float]:
        """Fetch the latest close price for a symbol."""
        try:
            import yfinance as yf
            data = yf.Ticker(symbol).history(period="1d", interval="1m")
            if data.empty:
                return None
            return float(data["Close"].iloc[-1])
        except Exception as exc:
            logger.error(f"Could not fetch current price for {symbol}: {exc}")
            return None

    # ── Trade journal (CSV) ───────────────────────────────────────────────────

    _ENTRY_HEADERS = [
        "timestamp", "order_id", "symbol", "side", "qty",
        "entry_price", "stop_loss", "take_profit",
        "dollar_risk", "confidence", "reason", "status",
    ]
    _EXIT_HEADERS = [
        "timestamp", "order_id", "symbol", "side", "qty",
        "entry_price", "exit_price", "pnl", "exit_reason",
    ]

    def _init_log(self) -> None:
        if not os.path.exists(self._log_path):
            with open(self._log_path, "w", newline="") as fh:
                csv.writer(fh).writerow(self._ENTRY_HEADERS)

    def _log_trade(self, approved: ApprovedTrade, order_id: str, status: str) -> None:
        sig = approved.signal
        row = [
            datetime.now(_NY).isoformat(), order_id,
            sig.symbol, sig.signal_type, approved.position_size,
            sig.entry_price, sig.stop_loss, sig.take_profit,
            approved.dollar_risk, sig.confidence, sig.reason, status,
        ]
        self._append_row(row)

    def _log_exit(self, pos: Position, exit_price: float, pnl: float, reason: str) -> None:
        exit_log = os.path.join(
            TRADES_DIR,
            f"exits_{datetime.now().strftime('%Y-%m-%d')}.csv",
        )
        write_header = not os.path.exists(exit_log)
        try:
            with open(exit_log, "a", newline="") as fh:
                w = csv.writer(fh)
                if write_header:
                    w.writerow(self._EXIT_HEADERS)
                w.writerow([
                    datetime.now(_NY).isoformat(), pos.order_id,
                    pos.symbol, pos.side, pos.qty,
                    pos.entry_price, exit_price, round(pnl, 2), reason,
                ])
        except Exception as exc:
            logger.error(f"Failed to write exit log: {exc}")

    def _append_row(self, row: list) -> None:
        try:
            with open(self._log_path, "a", newline="") as fh:
                csv.writer(fh).writerow(row)
        except Exception as exc:
            logger.error(f"Failed to write trade log: {exc}")
