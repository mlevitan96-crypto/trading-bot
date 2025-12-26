# Golden Hour vs 24/7 Trading Configuration

## Overview

This feature enables **configurable golden hour restriction** while **always tracking** which trades occurred during golden hour (09:00-16:00 UTC) versus 24/7 trading. This allows you to:

1. **Enable/disable** the golden hour restriction via config
2. **Always track** `trading_window` field in positions (either "golden_hour" or "24_7")
3. **Compare performance** between golden hour and 24/7 trades in the dashboard

## Configuration

**File:** `feature_store/golden_hour_config.json`

```json
{
  "restrict_to_golden_hour": false,
  "updated_at": null,
  "description": "Set restrict_to_golden_hour to false to enable 24/7 trading while still tracking which trades are golden_hour vs 24_7"
}
```

### Settings

- **`restrict_to_golden_hour: true`** - Blocks new entries outside 09:00-16:00 UTC (original behavior)
- **`restrict_to_golden_hour: false`** - Allows 24/7 trading, but still tracks `trading_window` field

## How It Works

1. **`check_golden_hours_block()`** (in `src/enhanced_trade_logging.py`):
   - Always returns `trading_window` ("golden_hour" or "24_7")
   - Only blocks if `restrict_to_golden_hour: true` AND outside golden hours
   - When restriction is disabled, never blocks but still tracks window type

2. **Position Tracking** (in `src/position_manager.py`):
   - Every position stores `trading_window` field
   - Set from `signal_context["trading_window"]`
   - Persisted in `positions_futures.json`

3. **Signal Context Flow**:
   - `unified_recovery_learning_fix.py` sets `ctx["trading_window"]` from `check_golden_hours_block()`
   - `full_integration_blofin_micro_live_and_paper.py` passes `trading_window` through `signal_context`
   - `position_manager.py` stores `trading_window` in position metadata

## Dashboard Integration

The `cockpit.py` dashboard needs a new tab "24/7 Trading" that:
- Filters trades by `trading_window` field
- Shows comparison metrics (win rate, P&L, profit factor)
- Displays daily/weekly comparisons
- Tracks both golden hour and 24/7 performance separately

**Status:** Dashboard tab implementation pending (see TODO list)

## Usage

### Enable 24/7 Trading

1. Edit `feature_store/golden_hour_config.json`:
   ```json
   {
     "restrict_to_golden_hour": false
   }
   ```

2. Restart the bot (or wait for next cycle)

3. Trades will now execute 24/7, but `trading_window` field will still track "golden_hour" vs "24_7"

### Re-enable Golden Hour Restriction

1. Edit `feature_store/golden_hour_config.json`:
   ```json
   {
     "restrict_to_golden_hour": true
   }
   ```

2. Restart the bot (or wait for next cycle)

3. Only trades during 09:00-16:00 UTC will execute

## Analysis

Use the existing `analyze_golden_hour_trades.py` script to compare performance:

```bash
python3 analyze_golden_hour_trades.py
```

This script will:
- Analyze all trades with `trading_window` field
- Compare golden hour vs 24/7 performance
- Generate comparison reports

## Files Modified

1. `src/enhanced_trade_logging.py` - Added `get_golden_hour_config()` and updated `check_golden_hours_block()`
2. `src/unified_recovery_learning_fix.py` - Updated to extract and pass `trading_window`
3. `src/full_integration_blofin_micro_live_and_paper.py` - Updated to pass `trading_window` through `signal_context`
4. `src/position_manager.py` - Added `trading_window` field storage
5. `src/bot_cycle.py` - Added `trading_window` to `signal_context`
6. `feature_store/golden_hour_config.json` - NEW config file

## Next Steps

1. ✅ Configuration system implemented
2. ✅ Tracking implemented
3. ⏳ Dashboard tab (pending - see TODO)
4. ⏳ Daily/weekly comparison functions (pending - see TODO)

---

**Date:** December 26, 2025  
**Status:** Core implementation complete, dashboard integration pending

