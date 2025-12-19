# Binary Blocking Gates → Sizing Adjustments Conversion

## Overview

All binary blocking gates have been converted to sizing adjustments to align with the weighted scoring system architecture. The system now uses continuous sizing multipliers instead of pass/fail decisions.

## Converted Gates

### 1. ✅ Intelligence Gate (`src/intelligence_gate.py`)
**Before**: Blocked trades if intel conflicted with confidence >= 0.6  
**After**: Always allows, reduces sizing:
- Strong conflict (confidence >= 0.6) → 0.4x sizing
- Moderate conflict (confidence 0.4-0.6) → 0.6x sizing
- Weak conflict (confidence < 0.4) → 0.8x sizing

### 2. ✅ Fee Gate (`src/fee_aware_gate.py`)
**Before**: Blocked if expected_move < min_required (including fees)  
**After**: Always allows, reduces sizing:
- Negative EV → 0.3x sizing
- Insufficient buffer → 0.5x to 0.8x sizing (interpolated)
- Good edge → 1.0x sizing

### 3. ✅ Streak Filter (`src/streak_filter.py`)
**Before**: Blocked trades after loss streaks  
**After**: Always allows, adjusts sizing:
- 3+ wins → 1.1x to 1.5x sizing boost
- 3+ losses → 0.5x sizing
- 2 losses → 0.7x sizing
- 1 loss → 0.85x sizing
- Neutral → 1.0x sizing

### 4. ✅ Phase 2 Regime Filter (`src/regime_filter.py`, `src/phase_2_orchestrator.py`)
**Before**: Blocked strategies that didn't match regime  
**After**: Always allows, reduces sizing:
- Regime mismatch → 0.6x sizing
- Regime match → 1.0x sizing

### 5. ✅ Correlation Throttle (`src/correlation_throttle.py`)
**Already using sizing adjustments** - no blocking, only size reductions based on correlation clusters.

### 6. ✅ ROI Checks (`src/bot_cycle.py`)
**Before**: Blocked if ROI below threshold  
**After**: Always trades, reduces sizing:
- Partial confirmation below threshold → 0.4x to 0.8x sizing (interpolated)
- ROI check failures → 0.5x sizing

## Remaining Binary Blocks (Safety Gates)

These gates remain as binary blocks for safety reasons:
- **Healing Escalation Kill Switch** - System health protection
- **Exchange Health Monitor** - Exchange degradation protection
- **Venue Guard** - Execution safety checks
- **Self Validation** - Critical pre-trade validation

## Sizing Multiplier Combination

All sizing multipliers are combined multiplicatively:

```
final_size = base_size × conviction_mult × streak_mult × intel_mult × regime_mult × roi_mult × fee_mult
```

Minimum floor: $200 (enforced by position manager)  
Maximum cap: 2.5x (enforced by conviction gate)

## Integration Points

1. **Conviction Gate** (`src/conviction_gate.py`):
   - Always returns `should_trade: True`
   - Provides base sizing multiplier (0.4x to 2.0x) based on weighted score

2. **Bot Cycle** (`src/bot_cycle.py`):
   - Combines all sizing multipliers from gates
   - Applies to final position size
   - Logs sizing adjustments for dashboard

3. **Dashboard** (`src/pnl_dashboard.py`):
   - Updated to show "sizing adjustments" instead of "blocks"
   - Logs include `sizing_multiplier` and `adjustment_reason`

## Testing Requirements

1. Verify conviction gate always returns `should_trade: True`
2. Verify all gates provide sizing multipliers
3. Verify sizing multipliers combine correctly
4. Verify minimum $200 floor is enforced
5. Verify dashboard shows sizing adjustments
6. Verify logs include sizing adjustment reasons

## Next Steps

1. Test end-to-end execution flow
2. Monitor sizing adjustments in production
3. Adjust sizing multiplier ranges based on performance
4. Update dashboard to better visualize sizing adjustments
