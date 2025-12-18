# Wallet Balance & P&L Fix Guide

## Issue
After switching to Kraken, wallet balance and net P&L are showing incorrect values.

## Root Cause
1. **Fee calculation wasn't exchange-aware** - Fixed ✅
2. **Portfolio file may have stale data** from Blofin trades
3. **Old closed positions** may have P&L calculated with Blofin fees

## Diagnostic Steps (Run on Droplet)

### Step 1: Run Diagnostic Script

```bash
cd /root/trading-bot-current
git pull origin main
chmod +x diagnose_wallet_pnl.py
python3 diagnose_wallet_pnl.py
```

This will show:
- Wallet balance calculated from closed positions
- Portfolio file values
- Any discrepancies
- Recent trade details

### Step 2: Check What's Wrong

The diagnostic will show:
1. **Closed positions P&L sum** (what dashboard uses)
2. **Portfolio realized_pnl** (what portfolio file has)
3. **Difference** between them

### Step 3: Fix Options

**Option A: If portfolio_futures.json has wrong realized_pnl**
```bash
# Recalculate from closed positions
cd /root/trading-bot-current
python3 << 'EOF'
import sys
sys.path.insert(0, '.')
from src.data_registry import DataRegistry as DR
from src.futures_portfolio_tracker import load_futures_portfolio, save_futures_portfolio

closed = DR.get_closed_positions(hours=None)
total_pnl = sum(float(p.get("pnl") or p.get("net_pnl") or p.get("realized_pnl") or 0) for p in closed)

portfolio = load_futures_portfolio()
print(f"Current portfolio realized_pnl: ${portfolio.get('realized_pnl', 0):,.2f}")
print(f"Recalculated from closed positions: ${total_pnl:,.2f}")

portfolio["realized_pnl"] = total_pnl
save_futures_portfolio(portfolio)
print("Fixed: Portfolio realized_pnl updated to match closed positions")
EOF
```

**Option B: If closed positions have wrong P&L (wrong fees)**

This is trickier - you'd need to recalculate P&L for all trades with correct exchange fees. This is likely not needed if the fee fix is working for new trades.

**Option C: Reset and Start Fresh (Nuclear Option)**

Only if everything is corrupted:
```bash
# Backup first!
cp logs/positions_futures.json logs/positions_futures.json.backup
cp logs/portfolio_futures.json logs/portfolio_futures.json.backup

# Reset portfolio to starting capital
python3 << 'EOF'
import sys
sys.path.insert(0, '.')
from src.futures_portfolio_tracker import load_futures_portfolio, save_futures_portfolio

portfolio = load_futures_portfolio()
portfolio["realized_pnl"] = 0.0
portfolio["total_margin_allocated"] = 10000.0
portfolio["available_margin"] = 10000.0
portfolio["used_margin"] = 0.0
save_futures_portfolio(portfolio)
print("Reset portfolio to starting capital")
EOF
```

**⚠️ WARNING:** Option C will lose all historical P&L. Only use if absolutely necessary.

## What Was Fixed

1. ✅ **Fee calculation now passes exchange parameter** - New Kraken trades will use correct fees
2. ✅ **Existing trades** - Already recorded, won't change automatically

## Next Steps

1. Run diagnostic to see the actual discrepancy
2. If discrepancy is small (< $50), it's likely just old Blofin trades with different fees - this is acceptable
3. If discrepancy is large (> $100), use Option A to sync portfolio file
4. Future trades will use correct Kraken fees automatically

## Monitoring

After fix:
- Check dashboard wallet balance
- Compare to portfolio_futures.json realized_pnl
- Should match within $1 (accounting for unrealized P&L from open positions)
