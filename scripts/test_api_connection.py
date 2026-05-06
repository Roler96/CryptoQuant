"""Test OKX API connection."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

load_dotenv()

console = Console()


def test_connection():
    """Test API connection."""
    console.print(Panel("[bold blue]Testing OKX API Connection[/bold blue]", expand=False))
    
    try:
        from data.manager import OKXClient
        
        # Try sandbox first
        console.print("Connecting to OKX Sandbox...")
        client = OKXClient(sandbox=True)
        
        # Test fetch
        console.print("Fetching BTC/USDT ticker...")
        ticker = client.fetch_ticker("BTC/USDT")
        
        console.print(f"[green]✓ Connection successful![/green]")
        console.print(f"  Last price: {ticker.last}")
        console.print(f"  Bid: {ticker.bid}")
        console.print(f"  Ask: {ticker.ask}")
        console.print(f"  24h Volume: {ticker.volume}")
        
        # Test OHLCV
        console.print("\nFetching BTC/USDT 1h candles (last 10)...")
        candles = client.fetch_ohlcv("BTC/USDT", "1h", limit=10)
        
        console.print(f"[green]✓ Fetched {len(candles)} candles[/green]")
        
        if candles:
            console.print(f"  First candle: {candles[0].timestamp}")
            console.print(f"  Last candle: {candles[-1].timestamp}")
            console.print(f"  Open: {candles[0].open_price}")
            console.print(f"  Close: {candles[0].close_price}")
        
        client.close()
        console.print("\n[bold green]✓ API test successful! Ready to download data.[/bold green]")
        return True
        
    except Exception as e:
        console.print(f"[red]✗ Connection failed: {e}[/red]")
        return False


def main():
    console.print("=" * 60)
    console.print("OKX API Connection Test")
    console.print("=" * 60)
    console.print()
    
    success = test_connection()
    
    console.print()
    console.print("=" * 60)
    if success:
        console.print("[bold green]✓ API is working![/bold green]")
        console.print()
        console.print("Next steps:")
        console.print("  1. python -m cli.main fetch --pair BTC/USDT --timeframe 1h --days 30")
        console.print("  2. python scripts/download_all_data.py")
    else:
        console.print("[bold red]✗ API connection failed[/bold red]")
    console.print("=" * 60)
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
