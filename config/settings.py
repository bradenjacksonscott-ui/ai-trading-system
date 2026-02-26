"""
Configuration settings — all values loaded from .env via python-dotenv.
No API keys or credentials are required to run this system.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Symbols to watch ─────────────────────────────────────────────────────────
SYMBOLS: list = [
    s.strip()
    for s in os.getenv("SYMBOLS", "AAPL,MSFT,TSLA,NVDA,SPY").split(",")
    if s.strip()
]

# ── Scan interval ─────────────────────────────────────────────────────────────
SCAN_INTERVAL_SECONDS: int = int(os.getenv("SCAN_INTERVAL_SECONDS", "300"))

# ── Paper trading simulator ───────────────────────────────────────────────────
STARTING_BALANCE: float = float(os.getenv("STARTING_BALANCE", "10000.0"))

# ── Risk management ───────────────────────────────────────────────────────────
DOLLAR_RISK_PER_TRADE: float = float(os.getenv("DOLLAR_RISK_PER_TRADE", "270.0"))   # Fixed $ risk
MAX_DAILY_LOSS_PCT: float = float(os.getenv("MAX_DAILY_LOSS_PCT", "0.03"))           # 3% daily stop
MAX_OPEN_TRADES: int = int(os.getenv("MAX_OPEN_TRADES", "3"))
MIN_RISK_REWARD: float = float(os.getenv("MIN_RISK_REWARD", "1.5"))

# ── Session limits ────────────────────────────────────────────────────────────
MAX_TRADES_PER_SESSION: int = int(os.getenv("MAX_TRADES_PER_SESSION", "1"))  # 1 per NY, 1 per Asia

# ── Technical analysis ────────────────────────────────────────────────────────
SWING_LOOKBACK: int = int(os.getenv("SWING_LOOKBACK", "5"))
LOOKBACK_BARS: int = int(os.getenv("LOOKBACK_BARS", "100"))
RETRACEMENT_TOLERANCE: float = float(os.getenv("RETRACEMENT_TOLERANCE", "0.003"))

# ── Paths ─────────────────────────────────────────────────────────────────────
LOG_DIR: str = "logs"
TRADES_DIR: str = "trades"
