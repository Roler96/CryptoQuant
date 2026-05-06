"""Database management tool for CryptoQuant."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.database import DatabaseManager, init_database
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()


def show_status():
    """Show database status."""
    db = init_database()
    
    console.print(Panel("[bold blue]Database Status[/bold blue]", expand=False))
    
    versions = db.get_data_versions()
    
    if not versions:
        console.print("[yellow]No data in database[/yellow]")
        return
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Pair")
    table.add_column("Timeframe")
    table.add_column("Version")
    table.add_column("Records", justify="right")
    table.add_column("Time Range")
    table.add_column("Source")
    
    total_records = 0
    
    for v in versions:
        from datetime import datetime, timezone
        
        min_dt = datetime.fromtimestamp(v["min_timestamp"]/1000, tz=timezone.utc) if v["min_timestamp"] else None
        max_dt = datetime.fromtimestamp(v["max_timestamp"]/1000, tz=timezone.utc) if v["max_timestamp"] else None
        
        time_range = f"{min_dt.strftime('%Y-%m-%d') if min_dt else '-'} to {max_dt.strftime('%Y-%m-%d') if max_dt else '-'}"
        
        table.add_row(
            v["pair"],
            v["timeframe"],
            str(v["version"]),
            f"{v['count']:,}",
            time_range,
            v["data_source"],
        )
        total_records += v["count"]
    
    console.print(table)
    console.print()
    console.print(f"[bold]Total pairs/timeframes:[/bold] {len(versions)}")
    console.print(f"[bold]Total records:[/bold] {total_records:,}")


def validate_data(pair: str = None, timeframe: str = None):
    """Validate data quality."""
    db = init_database()
    
    console.print(Panel("[bold blue]Data Quality Validation[/bold blue]", expand=False))
    
    if pair and timeframe:
        results = [db.validate_data_quality(pair, timeframe)]
    else:
        versions = db.get_data_versions()
        results = []
        for v in versions:
            console.print(f"Validating {v['pair']} {v['timeframe']}...")
            results.append(db.validate_data_quality(v["pair"], v["timeframe"]))
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Pair")
    table.add_column("Timeframe")
    table.add_column("Total", justify="right")
    table.add_column("Issues", justify="right")
    table.add_column("Status")
    
    for r in results:
        if "error" in r:
            status = "[red]✗ No data"
            issues = "-"
        else:
            issues = r["null_values"] + r["invalid_prices"] + r["negative_volumes"] + r["gaps"]
            status = "[green]✓ OK" if r["is_valid"] else f"[red]✗ {issues} issues"
            issues = str(issues) if issues > 0 else "-"
        
        table.add_row(
            r.get("pair", "-"),
            r.get("timeframe", "-"),
            str(r.get("total", 0)),
            issues,
            status,
        )
    
    console.print(table)


def reset_database():
    """Reset database (delete all data)."""
    db = init_database()
    
    console.print("[red]WARNING: This will delete all data![/red]")
    confirm = input("Type 'DELETE' to confirm: ")
    
    if confirm == "DELETE":
        db.drop_tables()
        db.create_tables()
        console.print("[green]✓ Database reset complete[/green]")
    else:
        console.print("[yellow]Cancelled[/yellow]")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Database management tool")
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # Status command
    status_parser = subparsers.add_parser("status", help="Show database status")
    
    # Validate command
    validate_parser = subparsers.add_parser("validate", help="Validate data quality")
    validate_parser.add_argument("--pair", help="Specific pair")
    validate_parser.add_argument("--timeframe", help="Specific timeframe")
    
    # Reset command
    reset_parser = subparsers.add_parser("reset", help="Reset database")
    
    args = parser.parse_args()
    
    if args.command == "status":
        show_status()
    elif args.command == "validate":
        validate_data(args.pair, args.timeframe)
    elif args.command == "reset":
        reset_database()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
