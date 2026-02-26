#!/usr/bin/env python3
"""
AI Day Trading System — Main Orchestrator
==========================================

Wires together the three agents and runs the main trading loop.

  Agent 1  MarketAnalysisAgent  — scans symbols, emits TradeSignal objects
  Agent 2  RiskManagementAgent  — validates signals, sizes positions
  Agent 3  ExecutionAgent       — places orders, tracks positions, logs trades

Run:
    python main.py

Stop cleanly with Ctrl-C.
"""
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from agents.execution_agent import ExecutionAgent
from agents.market_analysis_agent import MarketAnalysisAgent
from agents.risk_management_agent import RiskManagementAgent
from config.settings import SCAN_INTERVAL_SECONDS, SYMBOLS
from utils.logger import setup_logger

logger = setup_logger("main")

_NY = ZoneInfo("America/New_York")


# ── Market-hours gate ─────────────────────────────────────────────────────────

def _market_is_open() -> bool:
    """Return True during regular US equity market hours (Mon–Fri 09:30–16:00 ET)."""
    now = datetime.now(_NY)
    if now.weekday() >= 5:                          # Saturday=5, Sunday=6
        return False
    market_open  = now.replace(hour=9,  minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0,  second=0, microsecond=0)
    return market_open <= now <= market_close


# ── Main loop ─────────────────────────────────────────────────────────────────

def run() -> None:
    logger.info("=" * 64)
    logger.info("  AI Day Trading System — Starting")
    logger.info("=" * 64)

    # ── Initialise agents ──────────────────────────────────────────────────
    market_agent    = MarketAnalysisAgent()
    risk_agent      = RiskManagementAgent()
    execution_agent = ExecutionAgent()

    logger.info(f"Symbols   : {', '.join(SYMBOLS)}")
    logger.info(f"Interval  : {SCAN_INTERVAL_SECONDS}s between scans")
    logger.info("Press Ctrl-C to stop.\n")

    while True:
        try:
            # ── Market-hours check ─────────────────────────────────────────
            if not _market_is_open():
                logger.info("Market is closed — sleeping 60s …")
                time.sleep(60)
                continue

            logger.info(f"{'─' * 54}")
            logger.info(f"Scan started: {datetime.now(_NY).strftime('%H:%M:%S ET')}")

            # ── Agent 1 : Market Analysis ──────────────────────────────────
            signals = market_agent.scan_symbols(SYMBOLS)

            if not signals:
                logger.info("No trade signals found this cycle.")
            else:
                logger.info(f"{len(signals)} signal(s) found — running risk checks …")

            # ── Agent 2 → 3 : Risk check + Execution ──────────────────────
            for signal in signals:
                logger.info(
                    f"  Signal  [{signal.signal_type}] {signal.symbol} "
                    f"entry={signal.entry_price:.2f}  "
                    f"SL={signal.stop_loss:.2f}  "
                    f"TP={signal.take_profit:.2f}  "
                    f"conf={signal.confidence:.0%}"
                )

                # Pull live context for the risk agent
                balance          = execution_agent.get_account_balance()
                open_trade_count = execution_agent.get_open_trade_count()
                daily_pnl        = execution_agent.get_daily_pnl()

                approved = risk_agent.evaluate_signal(
                    signal,
                    account_balance=balance,
                    open_trade_count=open_trade_count,
                    daily_pnl=daily_pnl,
                )

                if not approved.approved:
                    logger.info(f"  → REJECTED: {approved.rejection_reason}")
                    continue

                logger.info(
                    f"  → APPROVED  {approved.position_size} shares | "
                    f"risk ${approved.dollar_risk:.2f}"
                )

                order = execution_agent.execute_trade(approved)
                if order:
                    logger.info(f"  → ORDER PLACED  id={order.id}")

            # ── Monitor open positions ─────────────────────────────────────
            execution_agent.monitor_positions()

            logger.info(
                f"Scan complete. Next scan in {SCAN_INTERVAL_SECONDS}s …\n"
            )
            time.sleep(SCAN_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            logger.info("\nShutdown requested — exiting cleanly.")
            break

        except Exception as exc:
            logger.error(f"Unhandled error in main loop: {exc}", exc_info=True)
            logger.info("Retrying in 30s …")
            time.sleep(30)


if __name__ == "__main__":
    run()
