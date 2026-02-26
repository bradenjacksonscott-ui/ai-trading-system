"""
Configuration settings — all values loaded from .env via python-dotenv.
Never hardcode credentials here.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Alpaca API ────────────────────────────────────────────────────────────────
ALPACA_API_KEY: str = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY: str = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_PAPER: bool = os.getenv("ALPACA_PAPER", "true").lower() == "true"

# ── Symbols to watch ─────────────────────────────────────────────────────────
SYMBOLS: list = [
    s.strip()
    for s in os.getenv("SYMBOLS", "AAPL,MSFT,TSLA,NVDA,SPY").split(",")
    if s.strip()
]

# ── Scan interval ─────────────────────────────────────────────────────────────
SCAN_INTERVAL_SECONDS: int = int(os.getenv("SCAN_INTERVAL_SECONDS", "300"))

# ── Risk management ───────────────────────────────────────────────────────────
ACCOUNT_RISK_PER_TRADE: float = float(os.getenv("ACCOUNT_RISK_PER_TRADE", "0.01"))  # 1%
MAX_DAILY_LOSS_PCT: float = float(os.getenv("MAX_DAILY_LOSS_PCT", "0.03"))           # 3%
MAX_OPEN_TRADES: int = int(os.getenv("MAX_OPEN_TRADES", "3"))
MIN_RISK_REWARD: float = float(os.getenv("MIN_RISK_REWARD", "1.5"))

# ── Technical analysis ────────────────────────────────────────────────────────
SWING_LOOKBACK: int = int(os.getenv("SWING_LOOKBACK", "5"))        # Bars each side for swing detection
LOOKBACK_BARS: int = int(os.getenv("LOOKBACK_BARS", "100"))         # Bars to fetch per symbol
RETRACEMENT_TOLERANCE: float = float(os.getenv("RETRACEMENT_TOLERANCE", "0.003"))  # 0.3%

# ── Paths ─────────────────────────────────────────────────────────────────────
LOG_DIR: str = "logs"
TRADES_DIR: str = "trades"
