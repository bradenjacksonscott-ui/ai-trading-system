"""
Agent 3 — Execution Agent
==========================
Receives ApprovedTrade objects from the Risk Management Agent and:
  • Submits bracket orders (market entry + take-profit limit + stop-loss stop)
    via the Alpaca Trading API.
  • Exposes helpers for the orchestrator to query account balance, open
    position count, and today's P&L (used by the risk agent).
  • Logs every trade attempt (success or failure) to a daily CSV file in
    the trades/ directory.

All API credentials are read from environment variables — never hardcoded.
"""
from __future__ import annotations

import csv
import os
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
from alpaca.trading.models import Order
from alpaca.trading.requests import MarketOrderRequest

# TakeProfitRequest / StopLossRequest were introduced in alpaca-py 0.8+
try:
    from alpaca.trading.requests import TakeProfitRequest, StopLossRequest
    _BRACKET_SUPPORTED = True
except ImportError:
    _BRACKET_SUPPORTED = False

from agents.market_analysis_agent import TradeSignal
from agents.risk_management_agent import ApprovedTrade
from config.settings import ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_PAPER, TRADES_DIR
from utils.logger import setup_logger

logger = setup_logger(__name__)

_NY = ZoneInfo("America/New_York")


class ExecutionAgent:
    """
    Connects to Alpaca (paper or live), executes approved trades,
    and persists a CSV trade journal.
    """

    def __init__(self) -> None:
        if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
            raise ValueError(
                "ALPACA_API_KEY and ALPACA_SECRET_KEY must be set in your .env file."
            )
        self._client = TradingClient(
            api_key=ALPACA_API_KEY,
            secret_key=ALPACA_SECRET_KEY,
            paper=ALPACA_PAPER,
        )
        os.makedirs(TRADES_DIR, exist_ok=True)
        self._log_path = os.path.join(
            TRADES_DIR,
            f"trades_{datetime.now().strftime('%Y-%m-%d')}.csv",
        )
        self._init_log()

        mode = "PAPER" if ALPACA_PAPER else "LIVE"
        logger.info(f"ExecutionAgent connected to Alpaca [{mode}]")
        if not _BRACKET_SUPPORTED:
            logger.warning(
                "alpaca-py version does not support bracket orders — "
                "falling back to simple market orders. Upgrade with: "
                "pip install --upgrade alpaca-py"
            )

    # ── Account helpers ───────────────────────────────────────────────────────

    def get_account_balance(self) -> float:
        """Return current cash balance (buying power for day trading)."""
        try:
            return float(self._client.get_account().cash)
        except Exception as exc:
            logger.error(f"get_account_balance: {exc}")
            return 0.0

    def get_open_trade_count(self) -> int:
        """Return number of open positions."""
        try:
            return len(self._client.get_all_positions())
        except Exception as exc:
            logger.error(f"get_open_trade_count: {exc}")
            return 0

    def get_daily_pnl(self) -> float:
        """Return today's equity change (equity − last_equity)."""
        try:
            acct = self._client.get_account()
            return float(acct.equity) - float(acct.last_equity)
        except Exception as exc:
            logger.error(f"get_daily_pnl: {exc}")
            return 0.0

    # ── Trade execution ───────────────────────────────────────────────────────

    def execute_trade(self, approved: ApprovedTrade) -> Optional[Order]:
        """
        Submit a bracket order for an approved trade.

        Returns the Alpaca Order object on success, or None on failure.
        The trade is always logged regardless of outcome.
        """
        signal = approved.signal
        side   = OrderSide.BUY if signal.signal_type == "BUY" else OrderSide.SELL

        logger.info(
            f"Executing {signal.signal_type} {signal.symbol} "
            f"x{approved.position_size} shares | "
            f"SL={signal.stop_loss:.2f}  TP={signal.take_profit:.2f}"
        )

        try:
            if _BRACKET_SUPPORTED:
                order_req = MarketOrderRequest(
                    symbol=signal.symbol,
                    qty=approved.position_size,
                    side=side,
                    time_in_force=TimeInForce.DAY,
                    order_class=OrderClass.BRACKET,
                    take_profit=TakeProfitRequest(
                        limit_price=round(signal.take_profit, 2)
                    ),
                    stop_loss=StopLossRequest(
                        stop_price=round(signal.stop_loss, 2)
                    ),
                )
            else:
                # Fallback: plain market order (manual exit management required)
                order_req = MarketOrderRequest(
                    symbol=signal.symbol,
                    qty=approved.position_size,
                    side=side,
                    time_in_force=TimeInForce.DAY,
                )

            order = self._client.submit_order(order_req)
            logger.info(f"Order placed — ID: {order.id}  Status: {order.status}")
            self._log_trade(approved, order_id=str(order.id), status=str(order.status))
            return order

        except Exception as exc:
            logger.error(f"Order submission failed for {signal.symbol}: {exc}")
            self._log_trade(approved, order_id="N/A", status=f"FAILED: {exc}")
            return None

    # ── Position monitoring ───────────────────────────────────────────────────

    def monitor_positions(self) -> None:
        """Log a summary of all currently open positions."""
        try:
            positions = self._client.get_all_positions()
        except Exception as exc:
            logger.error(f"monitor_positions: {exc}")
            return

        if not positions:
            logger.debug("No open positions.")
            return

        logger.info(f"Open positions ({len(positions)}):")
        for pos in positions:
            pnl = float(pos.unrealized_pl)
            sign = "+" if pnl >= 0 else ""
            logger.info(
                f"  {pos.symbol:6s}  qty={pos.qty:>6}  "
                f"avg={float(pos.avg_entry_price):.2f}  "
                f"P&L: {sign}{pnl:.2f}"
            )

    # ── Trade journal (CSV) ───────────────────────────────────────────────────

    _CSV_HEADERS = [
        "timestamp", "symbol", "side", "qty",
        "entry_price", "stop_loss", "take_profit",
        "dollar_risk", "confidence", "reason",
        "order_id", "status",
    ]

    def _init_log(self) -> None:
        if not os.path.exists(self._log_path):
            with open(self._log_path, "w", newline="") as fh:
                csv.writer(fh).writerow(self._CSV_HEADERS)

    def _log_trade(self, trade: ApprovedTrade, order_id: str, status: str) -> None:
        sig = trade.signal
        row = [
            datetime.now(_NY).isoformat(),
            sig.symbol,
            sig.signal_type,
            trade.position_size,
            sig.entry_price,
            sig.stop_loss,
            sig.take_profit,
            trade.dollar_risk,
            sig.confidence,
            sig.reason,
            order_id,
            status,
        ]
        try:
            with open(self._log_path, "a", newline="") as fh:
                csv.writer(fh).writerow(row)
        except Exception as exc:
            logger.error(f"Failed to write trade log: {exc}")
