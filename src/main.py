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
from src.backtest.engine import BacktestEngine

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


def cmd_backtest(args):
    """Run a historical backtest and display results."""
    config = load_config()

    console.print(f"\n[bold]Running backtest: {args.weeks} weeks, ${args.capital:,.0f} capital (buy Mon open → sell next Mon open)[/bold]\n")

    engine = BacktestEngine(config=config, capital=args.capital)
    result = engine.run(num_weeks=args.weeks)

    if not result.weeks:
        console.print("[yellow]No trading weeks found in the date range.[/yellow]")
        return

    # Per-week detail table
    detail_table = Table(title="Weekly Backtest Results")
    detail_table.add_column("Week", style="cyan")
    detail_table.add_column("Picks", style="magenta")
    detail_table.add_column("Entry Prices", justify="right")
    detail_table.add_column("Exit Prices", justify="right")
    detail_table.add_column("Weekly P&L", justify="right")
    detail_table.add_column("Return", justify="right")
    detail_table.add_column("Capital", justify="right", style="dim")

    for week in result.weeks:
        if week.trades:
            symbols = ", ".join(t.symbol for t in week.trades)
            entries = ", ".join(f"${t.entry_price:.2f}" for t in week.trades)
            exits = ", ".join(f"${t.exit_price:.2f}" for t in week.trades)
        else:
            symbols = "[dim]no picks[/dim]"
            entries = "---"
            exits = "---"

        pnl_style = "green" if week.weekly_pnl >= 0 else "red"
        ret_style = "green" if week.weekly_return_pct >= 0 else "red"

        detail_table.add_row(
            f"{week.week_start} to {week.week_end}",
            symbols,
            entries,
            exits,
            f"[{pnl_style}]${week.weekly_pnl:+,.2f}[/{pnl_style}]",
            f"[{ret_style}]{week.weekly_return_pct:+.2f}%[/{ret_style}]",
            f"${week.capital_end:,.2f}",
        )

    console.print(detail_table)

    # Summary stats table
    console.print()
    summary_table = Table(title="Backtest Summary", show_header=False, box=None, padding=(0, 2))
    summary_table.add_column("Metric", style="bold")
    summary_table.add_column("Value", justify="right")

    total_style = "green" if result.total_return_pct >= 0 else "red"

    summary_table.add_row("Starting Capital", f"${result.starting_capital:,.2f}")
    summary_table.add_row("Ending Capital", f"${result.ending_capital:,.2f}")
    summary_table.add_row("Total P&L", f"[{total_style}]${result.total_pnl:+,.2f}[/{total_style}]")
    summary_table.add_row("Total Return", f"[{total_style}]{result.total_return_pct:+.2f}%[/{total_style}]")
    summary_table.add_row("Win Rate", f"{result.win_rate:.1f}%")
    summary_table.add_row("Avg Weekly Return", f"{result.avg_weekly_return_pct:+.2f}%")
    summary_table.add_row("Best Week", f"[green]{result.best_week_return_pct:+.2f}%[/green]")
    summary_table.add_row("Worst Week", f"[red]{result.worst_week_return_pct:+.2f}%[/red]")
    summary_table.add_row("Max Drawdown", f"[red]{result.max_drawdown_pct:.2f}%[/red]")
    summary_table.add_row("Sharpe Ratio (ann.)", f"{result.sharpe_ratio:.2f}")
    summary_table.add_row("Total Trades", str(result.total_trades))
    summary_table.add_row("Winning / Losing", f"{result.winning_trades} / {result.losing_trades}")

    console.print(summary_table)
    console.print()


def cmd_sixmonth(args):
    """Generate 6-month buy-and-hold picks."""
    from src.strategy.sixmonth.scanner import SixMonthScanner

    capital = args.capital
    max_picks = args.picks

    console.print(f"\n[bold]6-MONTH BUY & HOLD — ${capital:,.0f} capital, top {max_picks} picks[/bold]")
    console.print("[bold red]CANNOT sell for 6 months. CAN add on strength.[/bold red]\n")

    scanner = SixMonthScanner()
    scores = scanner.scan()
    picks = scanner.generate_picks(capital=capital, max_picks=max_picks, scores=scores)

    if not picks:
        console.print("[yellow]No picks found.[/yellow]")
        return

    # Rankings table
    console.print("[bold]Momentum Rankings (top 15):[/bold]\n")
    rank_table = Table()
    rank_table.add_column("#", style="bold")
    rank_table.add_column("Symbol", style="cyan bold")
    rank_table.add_column("Score", justify="right")
    rank_table.add_column("Price", justify="right")
    rank_table.add_column("6m Return", justify="right")
    rank_table.add_column("3m Return", justify="right")
    rank_table.add_column("1m Return", justify="right")
    rank_table.add_column("Trend", justify="center")
    rank_table.add_column("Vol Trend", justify="right")

    for i, s in enumerate(scores[:15]):
        trend = ""
        if s.above_200_sma:
            trend += "200"
        if s.above_50_sma:
            trend += "+50"
        if s.making_new_highs:
            trend += " NEW HI"

        score_style = "green" if s.composite_score >= 60 else "yellow" if s.composite_score >= 40 else "red"
        ret6_style = "green" if s.return_6m > 0 else "red"
        ret3_style = "green" if s.return_3m > 0 else "red"
        ret1_style = "green" if s.return_1m > 0 else "red"

        rank_table.add_row(
            str(i + 1),
            s.symbol,
            f"[{score_style}]{s.composite_score:.0f}[/{score_style}]",
            f"${s.price_now:.2f}",
            f"[{ret6_style}]{s.return_6m:+.1f}%[/{ret6_style}]",
            f"[{ret3_style}]{s.return_3m:+.1f}%[/{ret3_style}]",
            f"[{ret1_style}]{s.return_1m:+.1f}%[/{ret1_style}]",
            trend,
            f"{s.volume_trend:.1f}x",
        )
    console.print(rank_table)

    # Picks detail
    console.print(f"\n[bold]YOUR {max_picks} PICKS — Hold until {picks[0].hold_until}:[/bold]\n")

    per_pick_capital = capital / max_picks
    for pick in picks:
        initial_deploy = per_pick_capital * (pick.initial_allocation_pct / (100 / max_picks))
        reserve = per_pick_capital - initial_deploy
        qty_now = int(initial_deploy / pick.entry_price)
        cost_now = qty_now * pick.entry_price

        console.print(Panel(
            f"[cyan bold]{pick.symbol}[/cyan bold] — {pick.strategy.value}\n\n"
            f"Price: ${pick.entry_price:.2f}  →  Target: ${pick.target_price:.2f} ([green]{pick.expected_return_pct:+.1f}%[/green])\n"
            f"Confidence: {pick.confidence:.0%}  |  Score: {pick.momentum_score.composite_score:.0f}/100\n\n"
            f"[bold]Deploy now:[/bold] {qty_now} shares × ${pick.entry_price:.2f} = ${cost_now:,.2f}\n"
            f"[bold]Reserve for pyramiding:[/bold] ${reserve:,.2f}\n"
            f"[bold]Add trigger:[/bold] Buy more if price rises +{pick.add_trigger_pct:.0f}% from entry\n"
            f"[bold]Hold until:[/bold] {pick.hold_until}\n\n"
            f"[bold]Rationale:[/bold] {pick.rationale}\n\n"
            f"[green]Catalysts:[/green] {chr(10).join('  + ' + c for c in pick.catalysts) if pick.catalysts else '  None identified'}\n\n"
            f"[red]Risks:[/red] {chr(10).join('  - ' + r for r in pick.risks) if pick.risks else '  Total loss accepted'}",
            title=f"Pick #{picks.index(pick) + 1}",
            border_style="cyan",
        ))

    console.print()


def cmd_validate(args):
    """Run the validation suite."""
    from src.backtest.validate import run_all

    console.print("\n[bold]Running validation suite...[/bold]\n")
    ok = run_all()
    if ok:
        console.print("\n[bold green]ALL VALIDATIONS PASSED[/bold green]")
    else:
        console.print("\n[bold red]VALIDATION FAILURES DETECTED[/bold red]")


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

    # backtest
    bt_parser = subparsers.add_parser("backtest", help="Run historical backtest")
    bt_parser.add_argument("--weeks", type=int, default=12, help="Number of weeks to backtest")
    bt_parser.add_argument("--capital", type=float, default=1_000, help="Starting capital")
    bt_parser.set_defaults(func=cmd_backtest)

    # validate
    val_parser = subparsers.add_parser("validate", help="Run validation suite")
    val_parser.set_defaults(func=cmd_validate)

    # sixmonth
    sm_parser = subparsers.add_parser("sixmonth", help="6-month buy-and-hold picks")
    sm_parser.add_argument("--capital", type=float, default=5_000, help="Capital to deploy")
    sm_parser.add_argument("--picks", type=int, default=3, help="Number of picks")
    sm_parser.set_defaults(func=cmd_sixmonth)

    args = parser.parse_args()

    if args.verbose:
        setup_logging(verbose=True)

    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
