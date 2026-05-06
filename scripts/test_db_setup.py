"""Test database setup and functionality without API keys."""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.database import DatabaseManager, init_database
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def test_database_setup():
    """Test database initialization and basic operations."""
    console.print(Panel("[bold blue]Testing Database Setup[/bold blue]", expand=False))
    
    try:
        db = init_database()
        console.print("[green]✓ Database initialized successfully[/green]")
        
        # Test insert
        test_candles = [
            {
                "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000) - 3600000,
                "open": 50000.0,
                "high": 51000.0,
                "low": 49500.0,
                "close": 50500.0,
                "volume": 100.5,
            },
            {
                "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
                "open": 50500.0,
                "high": 52000.0,
                "low": 50000.0,
                "close": 51500.0,
                "volume": 150.0,
            },
        ]
        
        count = db.save_candles(test_candles, "BTC/USDT", "1h")
        console.print(f"[green]✓ Inserted {count} test candles[/green]")
        
        # Test query
        candles = db.get_candles("BTC/USDT", "1h")
        console.print(f"[green]✓ Retrieved {len(candles)} candles[/green]")
        
        # Test version update
        db.update_data_version("BTC/USDT", "1h", len(candles), "TEST")
        console.print("[green]✓ Data version updated[/green]")
        
        # Test data quality
        quality = db.validate_data_quality("BTC/USDT", "1h")
        console.print(f"[green]✓ Data quality checked: {quality}[/green]")
        
        # Show versions
        versions = db.get_data_versions()
        if versions:
            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("Pair")
            table.add_column("Timeframe")
            table.add_column("Version")
            table.add_column("Count")
            
            for v in versions:
                table.add_row(v["pair"], v["timeframe"], str(v["version"]), str(v["count"]))
            
            console.print("\n[yellow]Data Versions:[/yellow]")
            console.print(table)
        
        console.print("\n[bold green]✓ All database tests passed![/bold green]")
        return True
        
    except Exception as e:
        console.print(f"[red]✗ Test failed: {e}[/red]")
        return False


def main():
    console.print("=" * 60)
    console.print("Database Setup Verification")
    console.print("=" * 60)
    console.print()
    
    success = test_database_setup()
    
    console.print()
    console.print("=" * 60)
    if success:
        console.print("[bold green]✓ Database is ready for real data![/bold green]")
        console.print()
        console.print("Next steps:")
        console.print("  1. Add OKX API credentials to .env file")
        console.print("  2. Run: python scripts/download_all_data.py")
        console.print("  3. Run: python scripts/db_manager.py validate")
    else:
        console.print("[bold red]✗ Database setup failed[/bold red]")
    console.print("=" * 60)
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
