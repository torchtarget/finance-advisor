"""Main entry point — weekly speculative trading advisor."""

from __future__ import annotations

import argparse
import logging

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from src.config import load_config
from src.data.market_data import MarketDataProvider
from src.execution.paper_trader import PaperTrader
from src.risk.position_sizer import PositionSizer
from src.strategy.scanner import WeeklyScanner
from src.strategy import strategies as _  # noqa: F401 — registers strategies

console = Console()
logger = logging.getLogger("finance-advisor")


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def print_banner():
    banner = Text()
    banner.append("WEEKLY SPECULATIVE TRADING ADVISOR\n", style="bold red")
    banner.append("HIGH RISK — You can lose everything.\n", style="bold yellow")
    banner.append("Advisor for instruments available on DeGiro.", style="dim")
    console.print(Panel(banner, border_style="red"))


def cmd_scan(args):
    """Scan the market and display top picks."""
    config = load_config()
    market_data = MarketDataProvider()
    scanner = WeeklyScanner(config, market_data)

    console.print("\n[bold]Scanning market universe...[/bold]\n")

    candidates = scanner.scan()
    signals = scanner.generate_signals(candidates)

    if not signals:
        console.print("[yellow]No signals found meeting criteria.[/yellow]")
        return

    capital = args.capital
    sizer = PositionSizer(config)
    recommendations = sizer.size_positions(signals, capital)

    table = Table(title=f"Top Picks — This Week (${capital:,.0f} capital)")
    table.add_column("#", style="bold")
    table.add_column("Symbol", style="cyan bold")
    table.add_column("Strategy", style="magenta")
    table.add_column("Confidence", justify="right")
    table.add_column("Price", justify="right", style="green")
    table.add_column("Target", justify="right", style="green")
    table.add_column("Exp Return", justify="right")
    table.add_column("Allocation", justify="right", style="yellow")
    table.add_column("Qty", justify="right")
    table.add_column("Cost", justify="right")

    for rec in recommendations:
        sig = rec.signal
        cost = sig.entry_price * rec.suggested_quantity

        confidence_style = "green" if sig.confidence >= 0.7 else "yellow"
        ret_style = "green" if (sig.expected_return_pct or 0) > 0 else "red"

        table.add_row(
            str(rec.rank),
            sig.asset.symbol,
            sig.strategy.value,
            f"[{confidence_style}]{sig.confidence:.0%}[/{confidence_style}]",
            f"${sig.entry_price:.2f}",
            f"${sig.target_price:.2f}" if sig.target_price else "---",
            f"[{ret_style}]{sig.expected_return_pct:+.1f}%[/{ret_style}]" if sig.expected_return_pct else "---",
            f"{rec.allocation_pct:.0f}%",
            str(rec.suggested_quantity),
            f"${cost:,.0f}",
        )

    console.print(table)

    console.print("\n[bold]Signal Details:[/bold]\n")
    for rec in recommendations:
        sig = rec.signal
        console.print(f"  [cyan]{sig.asset.symbol}[/cyan]: {sig.rationale}")
        if rec.max_loss_pct:
            console.print(f"    [red]Max loss: {rec.max_loss_pct:.0f}% of capital[/red]")
    console.print()


def cmd_paper(args):
    """Run paper trading with the top picks."""
    config = load_config()
    market_data = MarketDataProvider()
    scanner = WeeklyScanner(config, market_data)

    capital = args.capital
    paper = PaperTrader(starting_capital=capital)
    sizer = PositionSizer(config)

    console.print(f"\n[bold]Paper Trading Mode --- ${capital:,.0f} capital[/bold]\n")

    signals = scanner.generate_signals()
    if not signals:
        console.print("[yellow]No signals --- skipping this week.[/yellow]")
        return

    recommendations = sizer.size_positions(signals, capital)

    console.print("[bold]Paper trades:[/bold]\n")
    for rec in recommendations:
        order = paper.execute_recommendation(rec)
        status_style = "green" if order.status.value == "filled" else "red"
        if order.filled_price:
            console.print(
                f"  [{status_style}]{order.status.value.upper()}[/{status_style}] "
                f"{order.direction.value} {order.quantity}x {order.asset.symbol} "
                f"@ ${order.filled_price:.2f}"
            )

    total_value = paper.get_total_value()
    console.print(f"\n  Cash remaining: ${paper.cash:,.2f}")
    console.print(f"  Positions value: ${total_value - paper.cash:,.2f}")
    console.print(f"  Total value: ${total_value:,.2f}\n")

    paper.save_state()
    console.print("[dim]State saved to data/paper_trades.json[/dim]")


def cmd_serve(args):
    """Start the web UI (FastAPI + React)."""
    import uvicorn

    console.print(f"\n[bold]Starting web UI on http://localhost:{args.port}[/bold]\n")
    uvicorn.run("src.api.server:app", host="0.0.0.0", port=args.port, reload=args.reload)


def main():
    setup_logging()
    print_banner()

    parser = argparse.ArgumentParser(description="Weekly Speculative Trading Advisor")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    subparsers = parser.add_subparsers(dest="command")

    # scan
    scan_parser = subparsers.add_parser("scan", help="Scan market and show top picks")
    scan_parser.add_argument("--capital", type=float, default=1_000, help="Available capital")
    scan_parser.set_defaults(func=cmd_scan)

    # paper
    paper_parser = subparsers.add_parser("paper", help="Run paper trading")
    paper_parser.add_argument("--capital", type=float, default=1_000, help="Starting capital")
    paper_parser.set_defaults(func=cmd_paper)

    # serve (web UI)
    serve_parser = subparsers.add_parser("serve", help="Start web UI")
    serve_parser.add_argument("--port", type=int, default=8000, help="Port")
    serve_parser.add_argument("--reload", action="store_true", help="Auto-reload on changes")
    serve_parser.set_defaults(func=cmd_serve)

    args = parser.parse_args()

    if args.verbose:
        setup_logging(verbose=True)

    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
