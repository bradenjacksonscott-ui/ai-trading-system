#!/usr/bin/env python3
"""
Live Trading Dashboard
======================
Run this in a second terminal window while main.py is running.
Refreshes every 5 seconds and shows:
  - Account summary (balance, daily P&L, open positions)
  - Open positions table
  - Recent trades table
  - Latest log lines

Usage:
    venv\Scripts\activate
    python dashboard.py
"""
import csv
import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from rich.columns import Columns
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

_NY = ZoneInfo("America/New_York")
TRADES_DIR = "trades"
LOG_DIR    = "logs"
REFRESH_SECONDS = 5


# ── Helpers ───────────────────────────────────────────────────────────────────

def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def read_csv(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, newline="") as fh:
            return list(csv.DictReader(fh))
    except Exception:
        return []


def tail_log(n: int = 12) -> list[str]:
    path = os.path.join(LOG_DIR, f"trading_{today()}.log")
    if not os.path.exists(path):
        return ["No log file yet — start main.py first."]
    try:
        with open(path) as fh:
            lines = fh.readlines()
        return [l.rstrip() for l in lines[-n:]]
    except Exception:
        return []


def pnl_color(val: float) -> str:
    if val > 0:   return "bold green"
    if val < 0:   return "bold red"
    return "white"


# ── Panel builders ────────────────────────────────────────────────────────────

def build_header() -> Panel:
    now  = datetime.now(_NY)
    wd   = now.weekday()
    open_time  = now.replace(hour=9,  minute=30, second=0, microsecond=0)
    close_time = now.replace(hour=16, minute=0,  second=0, microsecond=0)
    is_open = (wd < 5) and (open_time <= now <= close_time)
    status  = "[bold green]MARKET OPEN[/]" if is_open else "[bold red]MARKET CLOSED[/]"
    time_str = now.strftime("%I:%M:%S %p ET  —  %A %b %d, %Y")
    return Panel(
        f"[bold white]AI Day Trading System[/]   {status}\n[dim]{time_str}[/]",
        box=box.DOUBLE_EDGE,
        style="bold blue",
    )


def build_account(trades: list[dict], exits: list[dict]) -> Panel:
    # Starting balance from .env (default 10000)
    try:
        from config.settings import STARTING_BALANCE
        starting = STARTING_BALANCE
    except Exception:
        starting = 10_000.0

    # Calculate realised P&L from exits
    realised = sum(float(r.get("pnl", 0)) for r in exits)

    # Open positions = entries without a matching exit
    exited_ids = {r.get("order_id") for r in exits}
    open_trades = [t for t in trades if t.get("order_id") not in exited_ids
                   and t.get("status", "").startswith("FILLED")]

    # Approximate current balance
    spent_open = sum(
        float(t.get("entry_price", 0)) * int(t.get("qty", 0))
        for t in open_trades
    )
    cash = starting + realised - spent_open

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim")
    grid.add_column(style="bold white")
    grid.add_row("Starting balance", f"${starting:>12,.2f}")
    grid.add_row("Realised P&L",
                 Text(f"${realised:>+12,.2f}", style=pnl_color(realised)))
    grid.add_row("Est. cash balance", f"${cash:>12,.2f}")
    grid.add_row("Open positions",   f"{len(open_trades):>12}")
    grid.add_row("Closed trades",    f"{len(exits):>12}")

    return Panel(grid, title="[bold]Account Summary[/]", box=box.ROUNDED,
                 border_style="cyan")


def build_open_positions(trades: list[dict], exits: list[dict]) -> Panel:
    exited_ids = {r.get("order_id") for r in exits}
    open_trades = [t for t in trades if t.get("order_id") not in exited_ids
                   and t.get("status", "").startswith("FILLED")]

    tbl = Table(box=box.SIMPLE_HEAD, show_edge=False,
                header_style="bold magenta")
    tbl.add_column("Symbol",  style="bold white", width=8)
    tbl.add_column("Side",    width=6)
    tbl.add_column("Qty",     justify="right", width=6)
    tbl.add_column("Entry",   justify="right", width=8)
    tbl.add_column("Stop",    justify="right", width=8)
    tbl.add_column("Target",  justify="right", width=8)
    tbl.add_column("$ Risk",  justify="right", width=8)
    tbl.add_column("Time",    width=20)

    if not open_trades:
        tbl.add_row("[dim]No open positions[/]", "", "", "", "", "", "", "")
    else:
        for t in open_trades:
            side_color = "green" if t.get("side") == "BUY" else "red"
            tbl.add_row(
                t.get("symbol", ""),
                f"[{side_color}]{t.get('side','')}[/]",
                t.get("qty", ""),
                f"${float(t.get('entry_price',0)):.2f}",
                f"${float(t.get('stop_loss',0)):.2f}",
                f"${float(t.get('take_profit',0)):.2f}",
                f"${float(t.get('dollar_risk',0)):.2f}",
                t.get("timestamp", "")[:19],
            )

    return Panel(tbl, title=f"[bold]Open Positions ({len(open_trades)})[/]",
                 box=box.ROUNDED, border_style="green")


def build_recent_exits(exits: list[dict]) -> Panel:
    tbl = Table(box=box.SIMPLE_HEAD, show_edge=False,
                header_style="bold magenta")
    tbl.add_column("Symbol",  style="bold white", width=8)
    tbl.add_column("Side",    width=6)
    tbl.add_column("Qty",     justify="right", width=6)
    tbl.add_column("Entry",   justify="right", width=8)
    tbl.add_column("Exit",    justify="right", width=8)
    tbl.add_column("P&L",     justify="right", width=9)
    tbl.add_column("Reason",  width=12)
    tbl.add_column("Time",    width=20)

    recent = list(reversed(exits[-10:]))

    if not recent:
        tbl.add_row("[dim]No closed trades yet[/]", "", "", "", "", "", "", "")
    else:
        for r in recent:
            pnl = float(r.get("pnl", 0))
            side_color = "green" if r.get("side") == "BUY" else "red"
            reason = r.get("exit_reason", "")
            reason_color = "green" if reason == "TAKE-PROFIT" else "red"
            tbl.add_row(
                r.get("symbol", ""),
                f"[{side_color}]{r.get('side','')}[/]",
                r.get("qty", ""),
                f"${float(r.get('entry_price',0)):.2f}",
                f"${float(r.get('exit_price',0)):.2f}",
                Text(f"${pnl:+.2f}", style=pnl_color(pnl)),
                f"[{reason_color}]{reason}[/]",
                r.get("timestamp", "")[:19],
            )

    return Panel(tbl, title="[bold]Recent Closed Trades[/]",
                 box=box.ROUNDED, border_style="yellow")


def build_log() -> Panel:
    lines = tail_log(12)
    colored = []
    for line in lines:
        if "ERROR"    in line: colored.append(f"[red]{line}[/]")
        elif "FILLED" in line: colored.append(f"[bold green]{line}[/]")
        elif "CLOSED" in line: colored.append(f"[bold yellow]{line}[/]")
        elif "APPROVED" in line: colored.append(f"[cyan]{line}[/]")
        elif "REJECTED" in line: colored.append(f"[dim red]{line}[/]")
        else:                   colored.append(f"[dim]{line}[/]")
    return Panel("\n".join(colored), title="[bold]Live Log[/]",
                 box=box.ROUNDED, border_style="dim white")


# ── Main render loop ──────────────────────────────────────────────────────────

def build_screen() -> Layout:
    trades_path = os.path.join(TRADES_DIR, f"trades_{today()}.csv")
    exits_path  = os.path.join(TRADES_DIR, f"exits_{today()}.csv")
    trades = read_csv(trades_path)
    exits  = read_csv(exits_path)

    layout = Layout()
    layout.split_column(
        Layout(build_header(),                       name="header",   size=4),
        Layout(build_account(trades, exits),         name="account",  size=9),
        Layout(build_open_positions(trades, exits),  name="open",     size=10),
        Layout(build_recent_exits(exits),            name="exits",    size=12),
        Layout(build_log(),                          name="log",      size=15),
    )
    return layout


def main():
    console = Console()
    console.clear()
    console.print(Panel(
        "[bold cyan]AI Day Trading Dashboard[/]\n"
        "[dim]Refreshes every 5 seconds. Press Ctrl-C to exit.[/]",
        box=box.DOUBLE_EDGE
    ))

    with Live(build_screen(), console=console,
              refresh_per_second=1, screen=True) as live:
        try:
            while True:
                time.sleep(REFRESH_SECONDS)
                live.update(build_screen())
        except KeyboardInterrupt:
            pass

    console.print("\n[dim]Dashboard closed.[/]")


if __name__ == "__main__":
    main()
