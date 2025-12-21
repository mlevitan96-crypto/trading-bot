# Fee Tracking Fixes - Complete Implementation

## Summary
Fixed fee tracking across the entire system to ensure fees are properly displayed in the dashboard, tracked in the learning engine, and used in all profitability calculations.

## Changes Made

### 1. Dashboard Fee Extraction (`src/dashboard_app.py`)
**Fixed:** `get_closed_futures_positions()` function now properly handles both SQLite format (`fees_usd`) and JSON format (`trading_fees` + `funding_fees`)

**Location:** Lines 174-184

**What it does:**
- Checks for `fees_usd` field (SQLite format)
- Falls back to `trading_fees + funding_fees` (JSON format)
- Includes legacy `fees` field as final fallback
- Returns both total `fees` and separate `trading_fees`/`funding_fees` fields

**Result:** Dashboard now correctly displays fees for all closed trades, regardless of data source.

### 2. Data Enrichment Layer (`src/data_enrichment_layer.py`)
**Fixed:** Properly extracts fees from multiple field name variations

**Location:** Lines 125-148

**What it does:**
- Extracts fees from `fees_usd`, `trading_fees`, `funding_fees`, or legacy `fees` fields
- Calculates total fees with proper fallback logic
- Includes both total fees and separate trading/funding fee breakdown in enriched records

**Result:** Learning engine now has accurate fee data for all trades.

### 3. SQLite Database Integration
**Verified:** `position_manager.py` already writes `fees_usd` to SQLite (line 719)
- Combines `trading_fees_usd + funding_fees` into single `fees_usd` field
- Dashboard reads this field correctly via `get_closed_trades_from_db()`

**Result:** Fees are properly stored and retrieved from SQLite.

### 4. Learning Engine Integration
**Verified:** Learning engine uses `net_pnl` which already accounts for fees
- `futures_portfolio_tracker.py` calculates `net_pnl` after deducting fees (line 254)
- `continuous_learning_controller.py` uses `net_pnl` for profitability analysis (line 197)
- All profitability calculations are based on net P&L (after fees)

**Result:** Learning engine already accounts for fees in all profitability calculations.

## Dashboard Display

### Main Dashboard (`/`)
- Uses `render_template("dashboard.html")` with `closed_positions` context
- Each position includes `fees`, `trading_fees`, and `funding_fees` fields
- Template should display: `${r.get('fees', 0):.2f}` (if template exists)

### Futures Dashboard (`/futures`)
- Already displays fees in attribution table (line 1449)
- Shows fees for each trade: `${r.get('fees', 0):.2f}`

## Verification

To verify fees are being tracked:

1. **Check recent trades:**
   ```bash
   python3 check_fee_tracking.py
   ```

2. **Check dashboard:**
   - Navigate to dashboard closed trades table
   - Verify "Fees" column shows non-zero values
   - Fees should be ~$0.08-$0.26 per trade (based on position size)

3. **Check data enrichment:**
   ```bash
   python3 -c "
   from src.data_enrichment_layer import enrich_decisions
   enriched = enrich_decisions()
   print(f'Enriched decisions: {len(enriched)}')
   if enriched:
       print(f'Sample fees: {enriched[0].get(\"outcome\", {}).get(\"fees\", 0)}')
   "
   ```

## Fee Calculation Details

### Trading Fees
- **Entry Fee:** Calculated on notional size (margin × leverage)
- **Exit Fee:** Calculated on notional size
- **Rate:** 0.06% (taker) or 0.02% (maker) per trade
- **Total:** Entry + Exit = 2 × fee rate × notional

### Funding Fees
- Accumulated over position hold time
- Positive = paid, Negative = received
- Typically $0.00 for quick trades (< 1 hour)

### Net P&L Calculation
```
gross_pnl = margin × leveraged_roi
trading_fees = calculate_trading_fee(notional, order_type) × 2
funding_fees = accumulated_funding_fees
net_pnl = gross_pnl - trading_fees - funding_fees
```

## Files Modified

1. `src/dashboard_app.py` - Fee extraction in `get_closed_futures_positions()`
2. `src/data_enrichment_layer.py` - Fee extraction in enriched records
3. `check_fee_tracking.py` - New verification script

## Next Steps

1. **Deploy changes:**
   ```bash
   git add src/dashboard_app.py src/data_enrichment_layer.py check_fee_tracking.py FEE_TRACKING_FIXES.md
   git commit -m "Fix fee tracking across dashboard, data enrichment, and learning systems"
   git push origin main
   ```

2. **On droplet:**
   ```bash
   cd /root/trading-bot-current
   git pull origin main
   sudo systemctl restart tradingbot
   ```

3. **Verify:**
   - Check dashboard closed trades table shows fees
   - Run `check_fee_tracking.py` to verify data
   - Confirm learning engine has fee data in enriched decisions

## Notes

- Fees are already being calculated and stored correctly in trade records
- The fix ensures fees are properly extracted and displayed regardless of data source (SQLite vs JSON)
- Learning engine already uses net P&L (after fees) for all calculations
- All profitability metrics account for fees automatically
