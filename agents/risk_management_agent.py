"""
Agent 2 — Risk Management Agent
=================================
Receives TradeSignal objects from the Market Analysis Agent and applies
a rule-based risk gate before forwarding them to the Execution Agent.

Rules enforced (in order):
  1. Minimum risk-reward ratio  (MIN_RISK_REWARD, default 1.5:1)
  2. Maximum concurrent open trades  (MAX_OPEN_TRADES, default 3)
  3. Maximum daily loss limit  (MAX_DAILY_LOSS_PCT, default 3 % of equity)
  4. Position sizing  — risk at most ACCOUNT_RISK_PER_TRADE % of balance per trade
  5. Sanity cap  — trade value cannot exceed 95 % of cash balance

Output: ApprovedTrade dataclass (approved=True/False + rejection reason).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from agents.market_analysis_agent import TradeSignal
from config.settings import (
    ACCOUNT_RISK_PER_TRADE,
    MAX_DAILY_LOSS_PCT,
    MAX_OPEN_TRADES,
    MIN_RISK_REWARD,
)
from utils.logger import setup_logger

logger = setup_logger(__name__)


# ── Public data structure ─────────────────────────────────────────────────────

@dataclass
class ApprovedTrade:
    signal: TradeSignal
    position_size: int        # Number of shares to trade
    dollar_risk: float        # $ at risk on this trade
    account_balance: float    # Cash balance at evaluation time
    approved: bool
    rejection_reason: str = ""


# ── Agent ─────────────────────────────────────────────────────────────────────

class RiskManagementAgent:
    """
    Stateless risk gate — all context (balance, open trades, P&L) is
    passed in per call so the orchestrator stays in control of state.
    """

    def evaluate_signal(
        self,
        signal: TradeSignal,
        account_balance: float,
        open_trade_count: int = 0,
        daily_pnl: float = 0.0,
    ) -> ApprovedTrade:
        """
        Validate signal against risk rules and calculate position size.

        Args:
            signal:           TradeSignal from MarketAnalysisAgent.
            account_balance:  Current cash/buying-power in USD.
            open_trade_count: Number of currently open positions.
            daily_pnl:        Today's realised + unrealised P&L (negative = loss).

        Returns:
            ApprovedTrade — check .approved before executing.
        """
        # ── Rule 1: Minimum risk-reward ───────────────────────────────────────
        rr = _risk_reward(signal)
        if rr < MIN_RISK_REWARD:
            return _reject(
                signal, account_balance,
                f"R:R {rr:.2f} is below the minimum {MIN_RISK_REWARD:.1f}",
            )

        # ── Rule 2: Maximum open positions ────────────────────────────────────
        if open_trade_count >= MAX_OPEN_TRADES:
            return _reject(
                signal, account_balance,
                f"Max open trades reached ({open_trade_count}/{MAX_OPEN_TRADES})",
            )

        # ── Rule 3: Daily loss limit ──────────────────────────────────────────
        if account_balance > 0 and daily_pnl < 0:
            loss_pct = abs(daily_pnl) / account_balance
            if loss_pct >= MAX_DAILY_LOSS_PCT:
                return _reject(
                    signal, account_balance,
                    f"Daily loss limit hit: {loss_pct:.1%} lost "
                    f"(limit {MAX_DAILY_LOSS_PCT:.0%})",
                )

        # ── Rule 4: Position sizing ───────────────────────────────────────────
        risk_per_share = abs(signal.entry_price - signal.stop_loss)
        if risk_per_share <= 0:
            return _reject(
                signal, account_balance,
                "Invalid stop loss — risk per share is zero or negative",
            )

        dollar_risk = account_balance * ACCOUNT_RISK_PER_TRADE
        position_size = int(dollar_risk / risk_per_share)

        if position_size < 1:
            return _reject(
                signal, account_balance,
                f"Position size rounds to 0 "
                f"(${dollar_risk:.2f} risk / ${risk_per_share:.4f}/share)",
            )

        # ── Rule 5: Trade-value cap (95 % of cash) ────────────────────────────
        max_affordable = int((account_balance * 0.95) / signal.entry_price)
        if position_size > max_affordable:
            position_size = max(1, max_affordable)
            logger.debug(
                f"{signal.symbol}: position capped to {position_size} shares "
                f"(95% cash limit)"
            )

        actual_risk = position_size * risk_per_share

        logger.info(
            f"APPROVED {signal.symbol}: {position_size} shares | "
            f"risk ${actual_risk:.2f} ({ACCOUNT_RISK_PER_TRADE:.0%} of "
            f"${account_balance:,.0f}) | R:R {rr:.1f}:1"
        )
        return ApprovedTrade(
            signal=signal,
            position_size=position_size,
            dollar_risk=round(actual_risk, 2),
            account_balance=account_balance,
            approved=True,
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _risk_reward(signal: TradeSignal) -> float:
    risk   = abs(signal.entry_price - signal.stop_loss)
    reward = abs(signal.take_profit - signal.entry_price)
    return reward / risk if risk > 0 else 0.0


def _reject(signal: TradeSignal, balance: float, reason: str) -> ApprovedTrade:
    logger.info(f"REJECTED {signal.symbol}: {reason}")
    return ApprovedTrade(
        signal=signal,
        position_size=0,
        dollar_risk=0.0,
        account_balance=balance,
        approved=False,
        rejection_reason=reason,
    )
