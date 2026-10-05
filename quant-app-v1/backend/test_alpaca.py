import sys
print("Starting...", flush=True)
try:
    from app.providers.alpaca_provider import AlpacaProvider
    print("AlpacaProvider imported successfully", flush=True)
    provider = AlpacaProvider()
    print("meta:", provider.meta, flush=True)
except Exception as e:
    print("Error:", e, flush=True)
    import traceback
    traceback.print_exc()