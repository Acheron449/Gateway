"""Service providers for Gateway."""

# Lazy imports to avoid circular dependency with app.models
def __getattr__(name: str):
    if name == "FinnhubNewsProvider":
        from .finnhub_provider import FinnhubNewsProvider
        return FinnhubNewsProvider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["FinnhubNewsProvider"]