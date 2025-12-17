# Kraken Exchange Integration Analysis

## Current Exchange Setup

### Active Exchanges
- **Futures Trading**: **Blofin** (Chinese exchange via `blofin_futures_client.py`)
- **Spot Market Data**: **Binance.US** (via `blofin_client.py` - confusing naming)
- **Architecture**: `ExchangeGateway` pattern with pluggable clients

### Key Integration Files
- `src/exchange_gateway.py` - Routes to spot/futures clients
- `src/blofin_futures_client.py` - Blofin futures API client (HMAC-SHA256 auth)
- `src/blofin_client.py` - Binance.US market data client
- `src/bot_cycle.py` - Uses `ExchangeGateway` for all trading operations

---

## Does Exchange Choice Matter for Real Money Trading?

### YES - It Matters Significantly

**1. Regulatory Compliance**
- **Blofin**: Chinese exchange, NOT US-regulated
- **Kraken**: US-regulated through CFTC/NFA via "Kraken Derivatives US"
- **Legal Requirement**: US residents trading futures MUST use US-regulated exchanges

**2. API Differences**
- Different authentication methods (Kraken uses different HMAC format)
- Different symbol formats (Blofin: `BTC-USDT`, Kraken: `PI_XBTUSD`)
- Different order types and parameters
- Different rate limits and error codes

**3. Fee Structures**
- Different taker/maker fees affect profitability calculations
- Current code assumes Blofin fees (0.06% taker, 0.02% maker)
- Would need fee recalibration for Kraken

**4. Technical Implementation**
- NOT just about "providing APIs" - entire client layer needs rewrite
- Symbol normalization logic differs
- Position tracking formats differ
- Margin/leverage calculations may differ

---

## Kraken Integration Status

### ✅ Kraken Does Support Trading Bots
- Official support for automated trading
- REST and WebSocket APIs available
- Python example code provided
- Reference: https://support.kraken.com/hc/articles/360001373983

### ✅ Kraken Futures Available in US
- **Kraken Derivatives US** (CFTC/NFA regulated)
- Available to verified US residents via Kraken Pro
- CME-listed cryptocurrency futures contracts
- Reference: https://www.kraken.com/features/futures

### ❌ No Kraken Integration in Current Codebase
- Zero Kraken-specific code found
- No `kraken_client.py` or similar
- Would require new implementation

---

## Required Integration Work

### 1. Create Kraken Futures Client
**File**: `src/kraken_futures_client.py`

**Key Methods Needed**:
```python
class KrakenFuturesClient:
    def __init__(self, api_key, api_secret, base_url="https://futures.kraken.com")
    
    def get_mark_price(self, symbol: str) -> float
    def get_orderbook(self, symbol: str, depth: int) -> Dict
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame
    def place_order(self, symbol, side, qty, price=None, leverage=1, ...) -> Dict
    def cancel_order(self, order_id: str, symbol: str) -> Dict
    def get_positions(self, symbol: Optional[str] = None) -> Dict
    def get_balance(self) -> Dict
```

**Differences from Blofin**:
- **Authentication**: Kraken uses different HMAC-SHA512 format with nonce + message
- **Symbol Format**: `PI_XBTUSD` (not `BTC-USDT`) - need conversion layer
- **API Endpoints**: Different base URL (`https://futures.kraken.com/derivatives/api/v3`)
- **Error Handling**: Different error response formats

### 2. Update Exchange Gateway
**File**: `src/exchange_gateway.py`

**Changes Needed**:
```python
class ExchangeGateway:
    def __init__(self, exchange="blofin", ...):  # Add exchange parameter
        if exchange == "kraken":
            from src.kraken_futures_client import KrakenFuturesClient
            self.fut = KrakenFuturesClient()
        elif exchange == "blofin":
            from src.blofin_futures_client import BlofinFuturesClient
            self.fut = BlofinFuturesClient()
```

### 3. Symbol Normalization
**File**: `src/exchange_utils.py` (new)

**Need Conversion Functions**:
```python
def normalize_to_kraken(symbol: str) -> str:
    """Convert BTCUSDT -> PI_XBTUSD"""
    # Kraken uses different naming
    # BTC -> XBT (per ISO 4217)
    # Format: PI_XBTUSD for perpetuals

def normalize_from_kraken(symbol: str) -> str:
    """Convert PI_XBTUSD -> BTCUSDT"""
    # Reverse conversion for internal use
```

### 4. Fee Calibration
**File**: `src/fee_calculator.py` (update)

**Kraken Fees** (need to verify current rates):
- Maker: ~0.02% (similar to Blofin)
- Taker: ~0.05-0.075% (different from Blofin's 0.06%)
- Update fee calculations in sizing/adjustment logic

### 5. Environment Configuration
**File**: `.env` (update)

**New Variables Needed**:
```bash
# Exchange Selection
EXCHANGE=kraken  # or "blofin"

# Kraken Futures API
KRAKEN_FUTURES_API_KEY=...
KRAKEN_FUTURES_API_SECRET=...
KRAKEN_FUTURES_TESTNET=false  # Use testnet for paper trading
```

### 6. Rate Limiting
**File**: `src/kraken_rate_limiter.py` (new)

**Kraken Rate Limits** (need to verify):
- Different from Blofin's limits
- May need different throttling strategy

---

## Implementation Complexity

### Estimated Effort
- **High Complexity** - ~40-60 hours of development
- **Why**: Entire API client layer needs rewrite, not just config changes

### Critical Components to Test
1. **Authentication** - HMAC signature generation
2. **Order Execution** - Market/limit orders with leverage
3. **Position Tracking** - Real-time position updates
4. **Symbol Mapping** - All trading pairs (BTC, ETH, SOL, etc.)
5. **Error Handling** - Network failures, API errors, rate limits
6. **Paper Trading** - Testnet integration first

### Risk Areas
1. **Symbol Format Mismatches** - Internal code uses `BTCUSDT`, Kraken uses `PI_XBTUSD`
2. **Position Synchronization** - Ensuring `positions_futures.json` stays in sync
3. **Fee Calculations** - All profitability models assume Blofin fees
4. **Leverage Rules** - Kraken may have different leverage limits/permissions

---

## Migration Strategy

### Phase 1: Kraken Client Development (Week 1-2)
1. Create `kraken_futures_client.py` with all required methods
2. Implement authentication (HMAC-SHA512)
3. Test with Kraken testnet API
4. Verify symbol conversion works for all trading pairs

### Phase 2: Gateway Integration (Week 2)
1. Update `ExchangeGateway` to support exchange selection
2. Add environment variable for exchange choice
3. Test routing logic with paper trading

### Phase 3: Fee & Symbol Updates (Week 2-3)
1. Update fee calculator with Kraken rates
2. Add symbol conversion layer
3. Update all hardcoded symbol references
4. Test with all symbols in `config/asset_universe.json`

### Phase 4: Testing & Validation (Week 3-4)
1. Paper trading on Kraken testnet for 1 week
2. Verify position tracking accuracy
3. Validate P&L calculations
4. Test all exit strategies (profit targets, stops, time exits)

### Phase 5: Production Deployment (Week 4)
1. Switch to Kraken live API (small capital)
2. Monitor for 48 hours
3. Full deployment if stable

---

## Kraken API Resources

### Official Documentation
- **REST API**: https://docs.futures.kraken.com/#introduction
- **WebSocket**: https://docs.futures.kraken.com/#websocket-api
- **Python Examples**: https://github.com/krakenfx/kraken-python
- **Rate Limits**: Check docs for current limits

### Key Endpoints Needed
```
GET  /api/v3/tickers          # Mark prices
GET  /api/v3/orderbook        # Orderbook depth
GET  /api/v3/candles          # OHLCV data
POST /api/v3/sendorder        # Place order
POST /api/v3/cancelorder      # Cancel order
GET  /api/v3/openpositions    # Get positions
GET  /api/v3/accounts         # Get balance
```

---

## Recommendation

### For US Real Money Trading: **YES, Switch to Kraken**

**Reasons**:
1. **Legal Compliance** - US-regulated exchange required for US residents
2. **Long-term Viability** - Blofin may face US regulatory issues
3. **Insurance/Protection** - Kraken Derivatives US offers SIPC-like protections

### Next Steps
1. **Verify Kraken Account** - Ensure you can access Kraken Derivatives US
2. **Get API Keys** - Generate futures API keys (testnet + live)
3. **Start Implementation** - Begin Phase 1 (Kraken client development)
4. **Test Thoroughly** - Paper trade for 2-4 weeks before real money

### Estimated Timeline
- **Development**: 3-4 weeks
- **Testing**: 1-2 weeks
- **Production Ready**: ~6 weeks from start

---

## Questions to Resolve

1. **Kraken Account Status**: Do you already have a Kraken account? Can you access futures?
2. **Symbol Availability**: Does Kraken offer all symbols you trade (BTC, ETH, SOL, AVAX, etc.)?
3. **Leverage Limits**: What leverage is available on Kraken for your account tier?
4. **Fee Structure**: What are current Kraken futures fees (maker/taker)?
5. **Timeline**: When do you need to go live? This affects prioritization.
