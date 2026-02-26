# AI Day Trading System

A three-agent algorithmic trading system for US equities, built on Alpaca's paper-trading API.

---

## Architecture

```
main.py (orchestrator)
    │
    ├── Agent 1 — MarketAnalysisAgent
    │     Fetches 5-min bars from Alpaca, detects trendline break-and-retest
    │     setups, and emits TradeSignal objects with confidence scores.
    │
    ├── Agent 2 — RiskManagementAgent
    │     Applies risk rules (R:R, max open trades, daily loss limit,
    │     position sizing) and either approves or rejects each signal.
    │
    └── Agent 3 — ExecutionAgent
          Submits bracket orders (entry + stop-loss + take-profit) via Alpaca,
          monitors open positions, and journals every trade to a CSV file.
```

### Strategy (5-minute trendline break-and-retest)

**Long setup**
1. Fit a downtrend line through recent swing highs.
2. Price closes above the trendline (breakout).
3. Record the highest high made after the break.
4. Price pulls back toward the trendline (retest).
5. **Entry** when price bounces off the trendline heading back to the breakout high.
6. **Stop-loss** 0.2% below the retest low.
7. **Take-profit** at the breakout high.

**Short setup** is the mirror image.

---

## Prerequisites

- Python 3.11+
- A free [Alpaca](https://alpaca.markets) account (paper trading is free, no real money needed)
- `git` installed

---

## Setup

### 1. Clone / enter the project
```bash
git clone <your-repo-url>
cd ai-trading-system
```

### 2. Create a virtual environment
```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure environment variables
```bash
cp .env.template .env
```
Open `.env` and fill in:
- `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` — from your Alpaca dashboard → Paper Trading → API Keys
- Optionally adjust `SYMBOLS`, risk parameters, and scan interval.

**Important:** `.env` is in `.gitignore` — your keys will never be committed.

### 5. Run
```bash
python main.py
```

The system will:
- Wait until US market hours (09:30–16:00 ET, Mon–Fri).
- Scan your symbol list every `SCAN_INTERVAL_SECONDS` (default 5 min).
- Log output to the console and to `logs/trading_YYYY-MM-DD.log`.
- Write every trade to `trades/trades_YYYY-MM-DD.csv`.

Stop cleanly with **Ctrl-C**.

---

## Project Structure

```
ai-trading-system/
├── agents/
│   ├── market_analysis_agent.py   # Agent 1 — trendline strategy
│   ├── risk_management_agent.py   # Agent 2 — risk rules & position sizing
│   └── execution_agent.py         # Agent 3 — Alpaca orders & trade log
├── config/
│   └── settings.py                # All config loaded from .env
├── utils/
│   ├── data_fetcher.py            # Alpaca market-data wrapper
│   └── logger.py                  # Logging setup
├── logs/                          # Daily log files (git-ignored)
├── trades/                        # Daily trade journals CSV (git-ignored)
├── main.py                        # Orchestrator — connects all three agents
├── requirements.txt
├── .env.template                  # Copy to .env and add your keys
└── .gitignore
```

---

## Risk Parameters (`.env`)

| Variable | Default | Description |
|---|---|---|
| `ACCOUNT_RISK_PER_TRADE` | `0.01` | Max equity risked per trade (1%) |
| `MAX_DAILY_LOSS_PCT` | `0.03` | Daily loss limit — system stops trading at 3% |
| `MAX_OPEN_TRADES` | `3` | Maximum simultaneous open positions |
| `MIN_RISK_REWARD` | `1.5` | Minimum R:R to accept a signal |
| `SWING_LOOKBACK` | `5` | Bars each side to confirm a swing high/low |
| `RETRACEMENT_TOLERANCE` | `0.003` | How close price must approach the trendline (0.3%) |

---

## Disclaimer

This software is for **educational and paper-trading purposes only**. It does not constitute financial advice. Past performance in simulation does not guarantee future results. Always thoroughly test any automated system in paper trading before considering live deployment.
