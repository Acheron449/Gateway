try:
    from app.providers.alpaca_provider import AlpacaProvider
    print('AlpacaProvider imported successfully')
    print('meta:', AlpacaProvider().meta)
except Exception as e:
    print('Error:', e)
    import traceback
    traceback.print_exc()