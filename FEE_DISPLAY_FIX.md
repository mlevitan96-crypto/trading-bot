# Fee Display Fix for Dashboard

## Problem
Fees were not showing in the closed trades dashboard table, even though fees are being tracked in the data.

## Root Cause
The `load_closed_positions_df()` function in `pnl_dashboard.py` was only checking for `trading_fees` and `funding_fees` fields, but not handling:
- SQLite format: `fees_usd` (combined total)
- Legacy format: `fees` (single field)

## Solution Applied

### 1. Updated Fee Extraction (`src/pnl_dashboard.py` line 431-442)
**Before:**
```python
fees = float(pos.get("trading_fees", 0) or 0) + float(pos.get("funding_fees", 0) or 0)
```

**After:**
```python
# Extract fees - handle multiple formats (SQLite: fees_usd, JSON: trading_fees + funding_fees)
fees_usd = pos.get("fees_usd", 0)  # SQLite format
trading_fees = pos.get("trading_fees", 0)
funding_fees = pos.get("funding_fees", 0)
legacy_fees = pos.get("fees", 0)

# Calculate total fees with proper fallback logic
if fees_usd and fees_usd != 0:
    fees = float(fees_usd)
elif (trading_fees and trading_fees != 0) or (funding_fees and funding_fees != 0):
    fees = float(trading_fees or 0) + float(funding_fees or 0)
else:
    fees = float(legacy_fees or 0.0)
```

### 2. Added Fee Breakdown to DataFrame
Added `trading_fees` and `funding_fees` columns to the dataframe for detailed breakdown (even if not displayed in table).

### 3. Table Configuration
The table already has the "Fees (USD)" column defined (line 844), so fees should now display.

## Fee Types Tracked

### Trading Fees
- **What it is**: Commission fees for opening and closing positions
- **Rate**: 0.06% (taker) or 0.02% (maker) per trade
- **Calculation**: Entry fee + Exit fee = 2 × fee_rate × notional_size
- **Typical range**: $0.08 - $0.26 per trade (depending on position size)

### Funding Fees
- **What it is**: Periodic funding payments for holding leveraged positions
- **Rate**: Varies by market (typically 0.01% - 0.1% per 8 hours)
- **Calculation**: Accumulated over position hold time
- **Typical value**: $0.00 for quick trades (< 1 hour), can be positive (paid) or negative (received)

### Total Fees
- **Formula**: `trading_fees + funding_fees`
- **Display**: Shown as "Fees (USD)" in dashboard
- **Impact**: Already deducted from `net_pnl` (net P&L is after fees)

## Verification

Run this on the droplet to verify fees are being extracted:

```bash
cd /root/trading-bot-current
git pull origin main
python3 debug_dashboard_fees.py
```

This will show:
- What fee fields exist in the data
- What fees are being calculated
- If fees are being loaded into the dataframe

## Expected Result

After pulling the changes:
1. Dashboard should show "Fees (USD)" column with values
2. Fees should be ~$0.08-$0.26 per trade (trading fees)
3. Total fees summary should show cumulative fees paid
4. Fees are already included in net P&L calculations

## Files Modified

1. `src/pnl_dashboard.py` - Updated fee extraction logic
2. `debug_dashboard_fees.py` - New debug script to verify fee data

## Testing Checklist

- [ ] Pull changes on droplet
- [ ] Run `debug_dashboard_fees.py` to verify data has fees
- [ ] Check dashboard - fees column should show values
- [ ] Verify fees match expected values (~$0.08-$0.26 per trade)
- [ ] Confirm total fees summary is accurate
