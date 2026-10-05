"""OpenBB CLI wrapper for command-line access to OpenBB data.

Phase 6 — Slice 6.2 (optional): CLI wrapper
Feature-gated via ENABLE_OPENBB_DATA (default: false).
"""

from __future__ import annotations

import asyncio
import sys
from typing import Optional

import typer

from app.config import get_settings
from app.providers.openbb_provider import OpenBBProvider, OpenBBConfig

app = typer.Typer(name="openbb", help="OpenBB data CLI")


def get_provider() -> OpenBBProvider:
    settings = get_settings()
    if not settings.enable_openbb_data:
        typer.echo("Error: OpenBB data integration is disabled. Set ENABLE_OPENBB_DATA=true to enable.", err=True)
        raise typer.Exit(1)
    return OpenBBProvider(OpenBBConfig())


@app.command()
def equity(
    symbol: str = typer.Argument(..., help="Stock symbol (e.g., AAPL)"),
    interval: str = typer.Option("1d", help="Interval (1d, 1h, 5m, 1m)"),
    period: str = typer.Option("1y", help="Period (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max)"),
    limit: int = typer.Option(500, help="Max number of rows"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Get historical equity data."""
    async def _run():
        provider = get_provider()
        data = await provider.history(symbol=symbol.upper(), interval=interval, range=period)
        if data is None:
            typer.echo(f"No data found for {symbol.upper()}", err=True)
            raise typer.Exit(1)
        
        if limit:
            data = data[:limit]
        
        if json_output:
            import json
            typer.echo(json.dumps(data, indent=2))
        else:
            for row in data:
                typer.echo(f"{row['time']} | O:{row['open']:.2f} H:{row['high']:.2f} L:{row['low']:.2f} C:{row['close']:.2f} V:{row['volume']:.0f}")
    
    asyncio.run(_run())


@app.command()
def crypto(
    symbol: str = typer.Argument(..., help="Crypto symbol (e.g., BTC-USD)"),
    interval: str = typer.Option("1d", help="Interval (1d, 1h, 5m, 1m)"),
    period: str = typer.Option("1y", help="Period (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max)"),
    limit: int = typer.Option(500, help="Max number of rows"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Get historical crypto data."""
    async def _run():
        provider = get_provider()
        data = await provider.history(symbol=symbol.upper(), interval=interval, range=period)
        if data is None:
            typer.echo(f"No data found for {symbol.upper()}", err=True)
            raise typer.Exit(1)
        
        if limit:
            data = data[:limit]
        
        if json_output:
            import json
            typer.echo(json.dumps(data, indent=2))
        else:
            for row in data:
                typer.echo(f"{row['time']} | O:{row['open']:.2f} H:{row['high']:.2f} L:{row['low']:.2f} C:{row['close']:.2f} V:{row['volume']:.0f}")
    
    asyncio.run(_run())


@app.command()
def quote(
    symbol: str = typer.Argument(..., help="Symbol (e.g., AAPL or BTC-USD)"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Get real-time quote."""
    async def _run():
        provider = get_provider()
        quote = await provider.quote(symbol=symbol.upper())
        if quote is None:
            typer.echo(f"No quote found for {symbol.upper()}", err=True)
            raise typer.Exit(1)
        
        if json_output:
            import json
            typer.echo(json.dumps(quote, indent=2))
        else:
            typer.echo(f"{symbol.upper()}: ${quote['last_price']:.2f} (bid: {quote['bid']}, ask: {quote['ask']})")
    
    asyncio.run(_run())


@app.command()
def news(
    symbol: Optional[str] = typer.Option(None, help="Filter by symbol"),
    limit: int = typer.Option(10, help="Number of news items"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Get news from OpenBB."""
    async def _run():
        provider = get_provider()
        news = await provider.news(symbol=symbol, limit=limit)
        if not news:
            typer.echo("No news found")
            return
        
        if json_output:
            import json
            typer.echo(json.dumps([{
                "id": item.id,
                "headline": item.headline,
                "url": item.url,
                "source": item.source,
                "published_at": str(item.published_at),
                "categories": item.categories,
                "related_symbols": item.related_symbols,
                "sentiment_score": item.sentiment_score,
            } for item in news], indent=2))
        else:
            for item in news:
                typer.echo(f"[{item.published_at}] {item.headline} ({item.source})")
                if item.url:
                    typer.echo(f"  {item.url}")
    
    asyncio.run(_run())


@app.command()
def calendar(
    limit: int = typer.Option(10, help="Number of events"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Get economic calendar from OpenBB."""
    async def _run():
        provider = get_provider()
        events = await provider.calendar(limit=limit)
        if not events:
            typer.echo("No events found")
            return
        
        if json_output:
            import json
            typer.echo(json.dumps([{
                "id": item.id,
                "title": item.title,
                "country": item.country,
                "currency": item.currency,
                "importance": str(item.importance),
                "scheduled_at": str(item.scheduled_at),
                "actual": item.actual,
                "forecast": item.forecast,
                "prior": item.prior,
            } for item in events], indent=2))
        else:
            for item in events:
                typer.echo(f"[{item.scheduled_at}] {item.title} ({item.country}) - {item.importance}")
    
    asyncio.run(_run())


@app.command()
def available():
    """List available OpenBB integrations."""
    async def _run():
        provider = get_provider()
        import openbb as obb
        for attr in dir(obb):
            if not attr.startswith("_"):
                typer.echo(attr)
    
    asyncio.run(_run())


if __name__ == "__main__":
    app()