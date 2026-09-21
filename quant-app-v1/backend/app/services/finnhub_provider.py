"""Compatibility alias for the canonical Finnhub adapter."""

from app.providers.finnhub_provider import FinnhubProvider

FinnhubNewsProvider = FinnhubProvider

__all__ = ["FinnhubNewsProvider", "FinnhubProvider"]
