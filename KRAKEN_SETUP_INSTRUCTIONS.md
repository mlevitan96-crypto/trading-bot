# Kraken Integration Setup Instructions

## ✅ Phase 1 Complete: Core Client Implementation

The following components have been created:
- ✅ `src/kraken_futures_client.py` - Full Kraken Futures API client
- ✅ `src/kraken_rate_limiter.py` - Rate limiting for Kraken API
- ✅ `src/exchange_utils.py` - Symbol conversion utilities
- ✅ Updated `src/exchange_gateway.py` - Exchange selection support
- ✅ Updated `src/fee_calculator.py` - Multi-exchange fee support

## Step 1: Get Kraken API Keys

1. **Log into Kraken Pro**: https://www.kraken.com/pro
2. **Navigate to API Keys**:
   - Go to Settings → API
   - Click "Generate API Key"
   - Select permissions:
     - ✅ Query Funds
     - ✅ Query Open Orders & Trades
     - ✅ Create & Modify Orders
     - ✅ Access Futures Data (if separate option)
3. **Save API Credentials**:
   - **API Key**: Public key (starts with something like `...`)
   - **API Secret**: Private key (base64-encoded, save securely)

## Step 2: Configure Environment Variables

Add to your `.env` file:

```bash
# Exchange Selection
EXCHANGE=kraken  # Use "kraken" or "blofin"

# Kraken Futures API
KRAKEN_FUTURES_API_KEY=your_api_key_here
KRAKEN_FUTURES_API_SECRET=your_base64_api_secret_here
KRAKEN_FUTURES_TESTNET=false  # Set to "true" for paper trading on testnet

# Optional: Custom base URLs
# KRAKEN_FUTURES_BASE_URL=https://futures.kraken.com
# KRAKEN_FUTURES_TESTNET_BASE_URL=https://demo-futures.kraken.com
```

## Step 3: Test Connectivity

Run the connectivity test:

```bash
python src/kraken_futures_client.py
```

This will:
1. Test symbol normalization (BTCUSDT → PI_XBTUSD)
2. Test public market data endpoints
3. Test authenticated endpoints (if API keys are set)
4. Verify position and balance queries

**Expected Output**:
```
════════════════════════════════════════════════════════════
🔍 Testing Kraken Futures API Connectivity
════════════════════════════════════════════════════════════
📍 Mode: live
🌐 Base URL: https://futures.kraken.com
════════════════════════════════════════════════════════════

1️⃣ Testing mark price (symbol normalization)...
   ✅ BTCUSDT mark price: $XX,XXX.XX

2️⃣ Testing authenticated endpoint (account balance)...
   ✅ Account balance retrieved: {...}

3️⃣ Testing positions query...
   ✅ Positions retrieved: X open positions

4️⃣ Testing market data (OHLCV)...
   ✅ Fetched 10 candles
   Latest close: $XX,XXX.XX
```

## Step 4: Verify Symbol Mapping

The bot trades 14 symbols. Verify they all map correctly:

```python
from src.exchange_utils import normalize_to_kraken

symbols = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT", "DOTUSDT",
    "TRXUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "BNBUSDT",
    "LINKUSDT", "ARBUSDT", "OPUSDT", "PEPEUSDT"
]

for sym in symbols:
    kraken_sym = normalize_to_kraken(sym)
    print(f"{sym} → {kraken_sym}")
```

**Note**: Some symbols may need verification against actual Kraken API. The mapping assumes:
- BTC → XBT (PI_XBTUSD)
- Most others → PF_{BASE}USD

## Step 5: Test Exchange Gateway Integration

Verify the gateway routes correctly:

```python
from src.exchange_gateway import ExchangeGateway

# Test with Kraken
gateway = ExchangeGateway(exchange="kraken")
price = gateway.get_price("BTCUSDT", venue="futures")
print(f"BTC price via Kraken: ${price:,.2f}")
```

## Step 6: Testnet Testing (Recommended)

Before going live, test with Kraken testnet:

```bash
# In .env file
KRAKEN_FUTURES_TESTNET=true
```

Then run paper trading for at least 1 week to verify:
- ✅ Order placement works correctly
- ✅ Position tracking is accurate
- ✅ Exit strategies function properly
- ✅ Fee calculations are correct

## Step 7: Verify Fee Rates

**Important**: Verify Kraken's current fee structure:

1. Check Kraken documentation: https://support.kraken.com/hc/en-us/articles/360000767986
2. Update `src/fee_calculator.py` if rates differ:
   ```python
   "kraken": {
       "maker": 0.0002,  # Update if different
       "taker": 0.0005,  # Update if different
   }
   ```

## Step 8: Known Issues & Limitations

### Symbol Mapping
- Some symbols may not exist on Kraken (e.g., PEPEUSDT, ARBUSDT)
- Verify all symbols in `config/asset_universe.json` are available on Kraken
- Update `KRAKEN_SYMBOL_MAP` in `exchange_utils.py` with verified mappings

### API Differences
- **Leverage**: Kraken may require separate leverage setting API call
- **Order Types**: Kraken uses "mkt" vs "lmt" (not "MARKET" vs "LIMIT")
- **Take Profit/Stop Loss**: Parameter names may differ from Blofin

### Rate Limits
- Current limiter uses conservative 60 req/min
- May need adjustment based on actual Kraken limits
- Check: https://docs.futures.kraken.com/#rate-limits

## Step 9: Production Deployment Checklist

Before switching to live trading:

- [ ] All symbols verified and mapped correctly
- [ ] Testnet tested for 1+ weeks
- [ ] Fee rates confirmed and updated
- [ ] Rate limits configured correctly
- [ ] Position tracking verified accurate
- [ ] Exit strategies tested (profit targets, stops, time exits)
- [ ] Error handling tested (network failures, API errors)
- [ ] Leverage limits confirmed for your account tier
- [ ] Capital allocation verified (start small)

## Step 10: Switch to Production

1. Update `.env`:
   ```bash
   EXCHANGE=kraken
   KRAKEN_FUTURES_TESTNET=false
   ```

2. Restart bot:
   ```bash
   sudo systemctl restart tradingbot
   ```

3. Monitor closely for first 48 hours:
   - Check position tracking
   - Verify order execution
   - Monitor P&L calculations
   - Watch for any API errors

## Troubleshooting

### Authentication Errors
- Verify API secret is base64-decoded correctly
- Check API key permissions include futures trading
- Ensure testnet flag matches your API key type

### Symbol Not Found
- Verify symbol exists on Kraken Futures
- Check symbol mapping in `exchange_utils.py`
- Some symbols may require different naming (e.g., perpetual vs futures)

### Rate Limit Errors
- Increase `min_delay_seconds` in `kraken_rate_limiter.py`
- Reduce `max_calls` if hitting 429 errors
- Check actual Kraken rate limits in their docs

## Next Steps

After successful testnet testing:
1. Update any symbol mappings that failed
2. Verify fee calculations match actual trades
3. Test all exit strategies
4. Gradually increase position sizes
5. Monitor learning system adaptations
