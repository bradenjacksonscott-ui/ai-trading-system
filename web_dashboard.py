"""
Web Dashboard — opens in your browser at http://localhost:5001
Auto-refreshes every 10 seconds. No terminal interaction needed to view.
Pages:
  /            Live trading view (account, open positions, closed trades)
  /calendar    Trade calendar — colour-coded days showing wins/losses
  /backtest    YTD backtest results table + run button
"""
import calendar
import csv
import glob
import os
import subprocess
import sys
import webbrowser
from collections import defaultdict
from datetime import datetime, date
from threading import Timer
from zoneinfo import ZoneInfo

from flask import Flask, render_template_string, redirect, url_for

app = Flask(__name__)
TRADES_DIR = "trades"
_NY = ZoneInfo("America/New_York")

# ── Shared CSS / nav ──────────────────────────────────────────────────────────
BASE_STYLE = """
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Segoe UI', Arial, sans-serif; background: #0d1117; color: #e6edf3; padding: 20px; }
a { color: #58a6ff; text-decoration: none; }
a:hover { text-decoration: underline; }
h1 { font-size: 22px; color: #58a6ff; margin-bottom: 4px; }
.subtitle { color: #8b949e; font-size: 13px; margin-bottom: 20px; }
.nav { display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }
.nav a {
  padding: 6px 18px; border-radius: 6px; border: 1px solid #30363d;
  font-size: 14px; color: #e6edf3;
}
.nav a.active, .nav a:hover { background: #1f6feb; border-color: #1f6feb; color: #fff; text-decoration: none; }
.cards { display: flex; gap: 14px; margin-bottom: 22px; flex-wrap: wrap; }
.card { background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 14px 22px; min-width: 160px; flex: 1; }
.card .label { color: #8b949e; font-size: 11px; text-transform: uppercase; letter-spacing: 1px; }
.card .value { font-size: 26px; font-weight: bold; margin-top: 4px; }
.green { color: #3fb950; } .red { color: #f85149; } .white { color: #e6edf3; } .blue { color: #58a6ff; }
.section { background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 16px; margin-bottom: 18px; }
.section h2 { font-size: 13px; color: #8b949e; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px solid #30363d; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th { text-align: left; color: #8b949e; font-size: 12px; font-weight: normal; padding: 6px 10px; }
td { padding: 8px 10px; border-top: 1px solid #21262d; }
tr:hover td { background: #1c2128; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: bold; }
.badge-buy { background: #1a4731; color: #3fb950; }
.badge-sell { background: #3d1f1f; color: #f85149; }
.badge-tp { background: #1a4731; color: #3fb950; }
.badge-sl { background: #3d1f1f; color: #f85149; }
.badge-eod { background: #2d2d1f; color: #e3b341; }
.empty { color: #484f58; font-style: italic; padding: 12px 10px; display: block; }
.btn { display: inline-block; padding: 8px 18px; background: #1f6feb; color: #fff; border-radius: 6px; font-size: 14px; border: none; cursor: pointer; }
.btn:hover { background: #388bfd; text-decoration: none; }
.status-open { color: #3fb950; font-weight: bold; }
.status-closed { color: #f85149; font-weight: bold; }
</style>
"""

NAV = """
<div class="nav">
  <a href="/" class="{live}">Live Trading</a>
  <a href="/calendar" class="{cal}">Trade Calendar</a>
  <a href="/backtest" class="{bt}">YTD Backtest</a>
</div>
"""

# ── Helpers ───────────────────────────────────────────────────────────────────

def today_str():
    return datetime.now().strftime("%Y-%m-%d")

def read_csv(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
    except Exception:
        return []

def is_market_open():
    now = datetime.now(_NY)
    if now.weekday() >= 5:
        return False
    o = now.replace(hour=9, minute=30, second=0, microsecond=0)
    c = now.replace(hour=16, minute=0,  second=0, microsecond=0)
    return o <= now <= c

def get_account_data():
    try:
        from config.settings import STARTING_BALANCE
        starting = STARTING_BALANCE
    except Exception:
        starting = 10_000.0
    trades = read_csv(os.path.join(TRADES_DIR, f"trades_{today_str()}.csv"))
    exits  = read_csv(os.path.join(TRADES_DIR, f"exits_{today_str()}.csv"))
    exited_ids  = {r.get("order_id") for r in exits}
    open_trades = [t for t in trades if t.get("order_id") not in exited_ids
                   and t.get("status", "").startswith("FILLED")]
    realised   = sum(float(r.get("pnl", 0)) for r in exits)
    spent_open = sum(float(t.get("entry_price", 0)) * int(t.get("qty", 0)) for t in open_trades)
    cash = starting + realised - spent_open
    return starting, cash, realised, open_trades, exits

def latest_backtest_file():
    files = sorted(glob.glob(os.path.join(TRADES_DIR, "backtest_results_*.csv")), reverse=True)
    return files[0] if files else None

# ── Live trading page ─────────────────────────────────────────────────────────

LIVE_HTML = BASE_STYLE + NAV + """
<h1>AI Day Trading System
  {% if market_open %}<span style="font-size:14px;color:#3fb950;margin-left:10px;">● MARKET OPEN</span>
  {% else %}<span style="font-size:14px;color:#f85149;margin-left:10px;">● MARKET CLOSED</span>{% endif %}
</h1>
<div class="subtitle">{{ now }}  —  Refreshes every 10s</div>

<div class="cards">
  <div class="card"><div class="label">Starting Balance</div><div class="value white">${{ "%.2f"|format(starting) }}</div></div>
  <div class="card"><div class="label">Realised P&amp;L Today</div>
    <div class="value {% if realised >= 0 %}green{% else %}red{% endif %}">${{ "%+.2f"|format(realised) }}</div></div>
  <div class="card"><div class="label">Est. Cash</div><div class="value white">${{ "%.2f"|format(cash) }}</div></div>
  <div class="card"><div class="label">Open Positions</div><div class="value blue">{{ open_trades|length }}</div></div>
  <div class="card"><div class="label">Closed Today</div><div class="value white">{{ exits|length }}</div></div>
</div>

<div class="section">
  <h2>Open Positions ({{ open_trades|length }})</h2>
  {% if open_trades %}
  <table>
    <tr><th>Symbol</th><th>Side</th><th>Qty</th><th>Entry</th><th>Stop Loss</th><th>Take Profit</th><th>$ Risk</th><th>Conf.</th><th>Time</th></tr>
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
  {% else %}<span class="empty">No open positions — waiting for a setup...</span>{% endif %}
</div>

<div class="section">
  <h2>Closed Trades Today ({{ exits|length }})</h2>
  {% if exits %}
  <table>
    <tr><th>Symbol</th><th>Side</th><th>Qty</th><th>Entry</th><th>Exit</th><th>P&amp;L</th><th>Result</th><th>Time</th></tr>
    {% for e in exits|reverse %}
    <tr>
      <td><strong>{{ e.symbol }}</strong></td>
      <td><span class="badge badge-{{ e.side|lower }}">{{ e.side }}</span></td>
      <td>{{ e.qty }}</td>
      <td>${{ "%.2f"|format(e.entry_price|float) }}</td>
      <td>${{ "%.2f"|format(e.exit_price|float) }}</td>
      <td class="{% if e.pnl|float >= 0 %}green{% else %}red{% endif %}">${{ "%+.2f"|format(e.pnl|float) }}</td>
      <td><span class="badge {% if e.exit_reason=='TAKE-PROFIT' %}badge-tp{% elif e.exit_reason=='STOP-LOSS' %}badge-sl{% else %}badge-eod{% endif %}">{{ e.exit_reason }}</span></td>
      <td>{{ e.timestamp[:19] }}</td>
    </tr>
    {% endfor %}
  </table>
  {% else %}<span class="empty">No closed trades yet today...</span>{% endif %}
</div>
<meta http-equiv="refresh" content="10">
"""

@app.route("/")
def live():
    starting, cash, realised, open_trades, exits = get_account_data()
    return render_template_string(
        LIVE_HTML,
        now=datetime.now().strftime("%I:%M:%S %p  %b %d, %Y"),
        market_open=is_market_open(),
        starting=starting, cash=cash, realised=realised,
        open_trades=open_trades, exits=exits,
    ).replace('"{live}"', '"active"').replace('"{cal}"', '""').replace('"{bt}"', '""')

# ── Calendar page ─────────────────────────────────────────────────────────────

CAL_HTML = BASE_STYLE + NAV + """
<h1>Trade Calendar</h1>
<div class="subtitle">{{ year }} — green = net profit day, red = net loss day, dot = trades taken</div>

{% for month_num, month_name, weeks, stats in months %}
<div class="section" style="display:inline-block;min-width:260px;margin-right:14px;margin-bottom:14px;vertical-align:top;">
  <h2>{{ month_name }}
    <span style="float:right;font-size:12px;">
      {{ stats.trades }}T &nbsp;
      <span class="{% if stats.pnl >= 0 %}green{% else %}red{% endif %}">${{ "%+.0f"|format(stats.pnl) }}</span>
    </span>
  </h2>
  <table style="font-size:13px;">
    <tr>{% for d in ['Mo','Tu','We','Th','Fr','Sa','Su'] %}<th style="width:34px;text-align:center;padding:4px;">{{ d }}</th>{% endfor %}</tr>
    {% for week in weeks %}
    <tr>
      {% for day, day_data in week %}
      <td style="text-align:center;padding:5px;border-radius:6px;
        {% if day_data %}
          {% if day_data.pnl > 0 %}background:#1a4731;color:#3fb950;
          {% elif day_data.pnl < 0 %}background:#3d1f1f;color:#f85149;
          {% else %}background:#21262d;{% endif %}
        {% endif %}">
        {% if day %}
          {{ day }}{% if day_data %}<br><span style="font-size:10px;">{{ day_data.trades }}t</span>{% endif %}
        {% endif %}
      </td>
      {% endfor %}
    </tr>
    {% endfor %}
  </table>
</div>
{% endfor %}
"""

@app.route("/calendar")
def cal():
    # Gather all exit files for this year
    year = datetime.now().year
    day_data = defaultdict(lambda: {"pnl": 0.0, "trades": 0})

    all_exit_files = glob.glob(os.path.join(TRADES_DIR, "exits_*.csv"))
    for f in all_exit_files:
        for row in read_csv(f):
            ts = row.get("timestamp", "")[:10]
            if ts.startswith(str(year)):
                day_data[ts]["pnl"]    += float(row.get("pnl", 0))
                day_data[ts]["trades"] += 1

    # Also include backtest exits for this year
    bt_file = latest_backtest_file()
    if bt_file:
        for row in read_csv(bt_file):
            ts = row.get("exit_date", "")[:10]
            if ts.startswith(str(year)):
                day_data[ts]["pnl"]    += float(row.get("pnl", 0))
                day_data[ts]["trades"] += 1

    months = []
    for month_num in range(1, 13):
        month_name = date(year, month_num, 1).strftime("%B")
        cal_weeks  = calendar.monthcalendar(year, month_num)
        weeks = []
        month_pnl, month_trades = 0.0, 0
        for week in cal_weeks:
            row_data = []
            for day in week:
                if day == 0:
                    row_data.append((None, None))
                else:
                    key = f"{year}-{month_num:02d}-{day:02d}"
                    d = day_data.get(key)
                    if d and d["trades"] > 0:
                        month_pnl    += d["pnl"]
                        month_trades += d["trades"]
                        row_data.append((day, d))
                    else:
                        row_data.append((day, None))
            weeks.append(row_data)
        months.append((
            month_num, month_name, weeks,
            {"pnl": month_pnl, "trades": month_trades},
        ))

    return render_template_string(
        CAL_HTML, year=year, months=months,
    ).replace('"{live}"', '""').replace('"{cal}"', '"active"').replace('"{bt}"', '""')

# ── Backtest page ─────────────────────────────────────────────────────────────

BT_HTML = BASE_STYLE + NAV + """
<h1>YTD Backtest Results</h1>
<div class="subtitle">Strategy tested on historical data from Jan 1 {{ year }} to today</div>

<div style="margin-bottom:18px;">
  <a href="/run-backtest" class="btn">&#9654; Run / Refresh YTD Backtest</a>
  <span style="color:#8b949e;font-size:13px;margin-left:14px;">Takes ~30 seconds — page will reload when done</span>
</div>

{% if summary %}
<div class="cards">
  <div class="card"><div class="label">Total Trades</div><div class="value white">{{ summary.total }}</div></div>
  <div class="card"><div class="label">Win Rate</div><div class="value {% if summary.win_rate >= 50 %}green{% else %}red{% endif %}">{{ "%.0f"|format(summary.win_rate) }}%</div></div>
  <div class="card"><div class="label">Total P&amp;L</div><div class="value {% if summary.pnl >= 0 %}green{% else %}red{% endif %}">${{ "%+.2f"|format(summary.pnl) }}</div></div>
  <div class="card"><div class="label">Avg Win</div><div class="value green">${{ "%+.2f"|format(summary.avg_win) }}</div></div>
  <div class="card"><div class="label">Avg Loss</div><div class="value red">${{ "%.2f"|format(summary.avg_loss) }}</div></div>
  <div class="card"><div class="label">Profit Factor</div><div class="value white">{{ "%.2f"|format(summary.pf) }}x</div></div>
</div>

<div class="section">
  <h2>All Backtest Trades ({{ trades|length }})</h2>
  {% if trades %}
  <table>
    <tr><th>Symbol</th><th>Side</th><th>Qty</th><th>Entry Date</th><th>Exit Date</th><th>Entry $</th><th>Exit $</th><th>P&amp;L</th><th>R:R</th><th>Result</th></tr>
    {% for t in trades %}
    <tr>
      <td><strong>{{ t.symbol }}</strong></td>
      <td><span class="badge badge-{{ t.side|lower }}">{{ t.side }}</span></td>
      <td>{{ t.qty }}</td>
      <td>{{ t.entry_date[:10] }}</td>
      <td>{{ t.exit_date[:10] }}</td>
      <td>${{ "%.2f"|format(t.entry_price|float) }}</td>
      <td>${{ "%.2f"|format(t.exit_price|float) }}</td>
      <td class="{% if t.pnl|float >= 0 %}green{% else %}red{% endif %}">${{ "%+.2f"|format(t.pnl|float) }}</td>
      <td>{{ t.rr_ratio }}</td>
      <td><span class="badge {% if t.exit_reason=='TAKE-PROFIT' %}badge-tp{% elif t.exit_reason=='STOP-LOSS' %}badge-sl{% else %}badge-eod{% endif %}">{{ t.exit_reason }}</span></td>
    </tr>
    {% endfor %}
  </table>
  {% else %}<span class="empty">No trades found in backtest.</span>{% endif %}
</div>
{% else %}
<div class="section">
  <span class="empty">&#9203; Backtest is running in the background — auto-refreshing every 15 seconds...</span>
</div>
<meta http-equiv="refresh" content="15">
{% endif %}
"""

@app.route("/backtest")
def backtest_page():
    bt_file = latest_backtest_file()
    trades  = read_csv(bt_file) if bt_file else []

    summary = None
    if trades:
        wins   = [t for t in trades if float(t.get("pnl", 0)) > 0]
        losses = [t for t in trades if float(t.get("pnl", 0)) <= 0]
        total_pnl = sum(float(t.get("pnl", 0)) for t in trades)
        gross_win  = sum(float(t.get("pnl", 0)) for t in wins)
        gross_loss = abs(sum(float(t.get("pnl", 0)) for t in losses))
        summary = {
            "total":    len(trades),
            "win_rate": len(wins) / len(trades) * 100 if trades else 0,
            "pnl":      total_pnl,
            "avg_win":  gross_win  / len(wins)   if wins   else 0,
            "avg_loss": gross_loss / len(losses) if losses else 0,
            "pf":       gross_win / gross_loss   if gross_loss > 0 else 0,
        }

    return render_template_string(
        BT_HTML,
        year=datetime.now().year,
        trades=trades,
        summary=summary,
    ).replace('"{live}"', '""').replace('"{cal}"', '""').replace('"{bt}"', '"active"')

@app.route("/run-backtest")
def run_backtest():
    """Trigger a YTD backtest in a subprocess, then redirect back."""
    days_this_year = (datetime.now() - datetime(datetime.now().year, 1, 1)).days + 1
    try:
        venv_python = os.path.join("venv", "Scripts", "python.exe")
        python_exe  = venv_python if os.path.exists(venv_python) else sys.executable
        subprocess.Popen(
            [python_exe, "backtest.py", "--days", str(days_this_year)],
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except Exception as e:
        pass
    import time; time.sleep(2)
    return redirect(url_for("backtest_page"))

# ── Entry point ───────────────────────────────────────────────────────────────

def open_browser():
    webbrowser.open("http://localhost:5001")

def _auto_run_backtest():
    """Kick off a YTD backtest in the background if no results file exists yet."""
    if latest_backtest_file():
        return  # Already have data
    days_this_year = (datetime.now() - datetime(datetime.now().year, 1, 1)).days + 1
    venv_python = os.path.join("venv", "Scripts", "python.exe")
    python_exe  = venv_python if os.path.exists(venv_python) else sys.executable
    try:
        subprocess.Popen(
            [python_exe, "backtest.py", "--days", str(days_this_year)],
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        print("  Auto-running YTD backtest in the background (~30s)...")
    except Exception:
        pass


if __name__ == "__main__":
    print("\n  AI Trading Dashboard")
    print("  Opening at http://localhost:5001 ...")
    print("  Press Ctrl-C to stop.\n")
    _auto_run_backtest()
    Timer(1.5, open_browser).start()
    app.run(host="localhost", port=5001, debug=False)
