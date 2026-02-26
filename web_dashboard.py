"""
Web Dashboard — opens in your browser at http://localhost:5001
Auto-refreshes every 10 seconds. No terminal interaction needed to view.
"""
import csv
import os
import webbrowser
from datetime import datetime
from threading import Timer
from flask import Flask, render_template_string

app = Flask(__name__)

TRADES_DIR = "trades"

HTML = """
<!DOCTYPE html>
<html>
<head>
  <title>AI Trading Dashboard</title>
  <meta http-equiv="refresh" content="10">
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Segoe UI', Arial, sans-serif;
      background: #0d1117;
      color: #e6edf3;
      padding: 20px;
    }
    h1 {
      font-size: 24px;
      color: #58a6ff;
      margin-bottom: 4px;
    }
    .subtitle {
      color: #8b949e;
      font-size: 13px;
      margin-bottom: 24px;
    }
    .status-badge {
      display: inline-block;
      padding: 3px 12px;
      border-radius: 20px;
      font-size: 13px;
      font-weight: bold;
      margin-left: 12px;
    }
    .open   { background: #1a4731; color: #3fb950; }
    .closed { background: #3d1f1f; color: #f85149; }

    .cards {
      display: flex;
      gap: 16px;
      margin-bottom: 24px;
      flex-wrap: wrap;
    }
    .card {
      background: #161b22;
      border: 1px solid #30363d;
      border-radius: 10px;
      padding: 16px 24px;
      min-width: 180px;
      flex: 1;
    }
    .card .label { color: #8b949e; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; }
    .card .value { font-size: 28px; font-weight: bold; margin-top: 4px; }
    .green { color: #3fb950; }
    .red   { color: #f85149; }
    .white { color: #e6edf3; }
    .blue  { color: #58a6ff; }

    .section {
      background: #161b22;
      border: 1px solid #30363d;
      border-radius: 10px;
      padding: 16px;
      margin-bottom: 20px;
    }
    .section h2 {
      font-size: 15px;
      color: #8b949e;
      text-transform: uppercase;
      letter-spacing: 1px;
      margin-bottom: 14px;
      padding-bottom: 8px;
      border-bottom: 1px solid #30363d;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }
    th {
      text-align: left;
      color: #8b949e;
      font-size: 12px;
      font-weight: normal;
      padding: 6px 10px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    td {
      padding: 8px 10px;
      border-top: 1px solid #21262d;
    }
    tr:hover td { background: #1c2128; }
    .badge {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 4px;
      font-size: 12px;
      font-weight: bold;
    }
    .badge-buy   { background: #1a4731; color: #3fb950; }
    .badge-sell  { background: #3d1f1f; color: #f85149; }
    .badge-tp    { background: #1a4731; color: #3fb950; }
    .badge-sl    { background: #3d1f1f; color: #f85149; }
    .empty { color: #484f58; font-style: italic; padding: 12px 10px; }
    .footer { color: #484f58; font-size: 12px; margin-top: 16px; text-align: center; }
  </style>
</head>
<body>

  <h1>
    AI Day Trading System
    {% if market_open %}
      <span class="status-badge open">● MARKET OPEN</span>
    {% else %}
      <span class="status-badge closed">● MARKET CLOSED</span>
    {% endif %}
  </h1>
  <div class="subtitle">{{ now }}  —  Auto-refreshes every 10 seconds</div>

  <!-- Account Cards -->
  <div class="cards">
    <div class="card">
      <div class="label">Starting Balance</div>
      <div class="value white">${{ "%.2f"|format(starting) }}</div>
    </div>
    <div class="card">
      <div class="label">Realised P&amp;L Today</div>
      <div class="value {% if realised >= 0 %}green{% else %}red{% endif %}">
        ${{ "%+.2f"|format(realised) }}
      </div>
    </div>
    <div class="card">
      <div class="label">Est. Cash Balance</div>
      <div class="value white">${{ "%.2f"|format(cash) }}</div>
    </div>
    <div class="card">
      <div class="label">Open Positions</div>
      <div class="value blue">{{ open_count }}</div>
    </div>
    <div class="card">
      <div class="label">Closed Trades</div>
      <div class="value white">{{ closed_count }}</div>
    </div>
  </div>

  <!-- Open Positions -->
  <div class="section">
    <h2>Open Positions ({{ open_count }})</h2>
    {% if open_trades %}
    <table>
      <tr>
        <th>Symbol</th><th>Side</th><th>Qty</th>
        <th>Entry</th><th>Stop Loss</th><th>Take Profit</th>
        <th>$ Risk</th><th>Confidence</th><th>Time</th>
      </tr>
      {% for t in open_trades %}
      <tr>
        <td><strong>{{ t.symbol }}</strong></td>
        <td><span class="badge badge-{{ t.side|lower }}">{{ t.side }}</span></td>
        <td>{{ t.qty }}</td>
        <td>${{ "%.2f"|format(t.entry_price|float) }}</td>
        <td class="red">${{ "%.2f"|format(t.stop_loss|float) }}</td>
        <td class="green">${{ "%.2f"|format(t.take_profit|float) }}</td>
        <td>${{ "%.2f"|format(t.dollar_risk|float) }}</td>
        <td>{{ "%.0f"|format(t.confidence|float * 100) }}%</td>
        <td>{{ t.timestamp[:19] }}</td>
      </tr>
      {% endfor %}
    </table>
    {% else %}
    <div class="empty">No open positions — waiting for a setup...</div>
    {% endif %}
  </div>

  <!-- Closed Trades -->
  <div class="section">
    <h2>Closed Trades ({{ closed_count }})</h2>
    {% if exits %}
    <table>
      <tr>
        <th>Symbol</th><th>Side</th><th>Qty</th>
        <th>Entry</th><th>Exit</th><th>P&amp;L</th>
        <th>Result</th><th>Time</th>
      </tr>
      {% for e in exits|reverse %}
      <tr>
        <td><strong>{{ e.symbol }}</strong></td>
        <td><span class="badge badge-{{ e.side|lower }}">{{ e.side }}</span></td>
        <td>{{ e.qty }}</td>
        <td>${{ "%.2f"|format(e.entry_price|float) }}</td>
        <td>${{ "%.2f"|format(e.exit_price|float) }}</td>
        <td class="{% if e.pnl|float >= 0 %}green{% else %}red{% endif %}">
          ${{ "%+.2f"|format(e.pnl|float) }}
        </td>
        <td>
          <span class="badge {% if e.exit_reason == 'TAKE-PROFIT' %}badge-tp{% else %}badge-sl{% endif %}">
            {{ e.exit_reason }}
          </span>
        </td>
        <td>{{ e.timestamp[:19] }}</td>
      </tr>
      {% endfor %}
    </table>
    {% else %}
    <div class="empty">No closed trades yet today...</div>
    {% endif %}
  </div>

  <div class="footer">
    Dashboard served from http://localhost:5001 &nbsp;|&nbsp;
    Trades saved to trades/ folder &nbsp;|&nbsp;
    Stop with Ctrl-C in the trading engine window
  </div>

</body>
</html>
"""

def today():
    return datetime.now().strftime("%Y-%m-%d")

def read_csv(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path, newline="") as fh:
            return list(csv.DictReader(fh))
    except Exception:
        return []

def is_market_open():
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("America/New_York"))
    if now.weekday() >= 5:
        return False
    o = now.replace(hour=9,  minute=30, second=0, microsecond=0)
    c = now.replace(hour=16, minute=0,  second=0, microsecond=0)
    return o <= now <= c

@app.route("/")
def index():
    trades = read_csv(os.path.join(TRADES_DIR, f"trades_{today()}.csv"))
    exits  = read_csv(os.path.join(TRADES_DIR, f"exits_{today()}.csv"))

    try:
        from config.settings import STARTING_BALANCE
        starting = STARTING_BALANCE
    except Exception:
        starting = 10_000.0

    exited_ids  = {r.get("order_id") for r in exits}
    open_trades = [t for t in trades
                   if t.get("order_id") not in exited_ids
                   and t.get("status", "").startswith("FILLED")]

    realised   = sum(float(r.get("pnl", 0)) for r in exits)
    spent_open = sum(float(t.get("entry_price", 0)) * int(t.get("qty", 0))
                     for t in open_trades)
    cash = starting + realised - spent_open

    return render_template_string(
        HTML,
        now=datetime.now().strftime("%I:%M:%S %p  —  %A %b %d, %Y"),
        market_open=is_market_open(),
        starting=starting,
        realised=realised,
        cash=cash,
        open_count=len(open_trades),
        closed_count=len(exits),
        open_trades=open_trades,
        exits=exits,
    )

def open_browser():
    webbrowser.open("http://localhost:5001")

if __name__ == "__main__":
    print("\n  AI Trading Dashboard")
    print("  Opening at http://localhost:5001 ...")
    print("  Press Ctrl-C to stop.\n")
    Timer(1.5, open_browser).start()
    app.run(host="localhost", port=5001, debug=False)
