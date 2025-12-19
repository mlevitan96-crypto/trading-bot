# Signal Blocking Architecture Analysis

## Current System - Mixed Approach

### Weighted Scoring System (Conviction Gate) ✅
**Location**: `src/conviction_gate.py`

**How it works:**
- Each signal contributes: `weight × confidence × direction_alignment`
- Composite score = sum of all signal contributions
- Score maps to sizing multiplier (0.4x to 2.0x)
- **NEVER BLOCKS** - always returns `should_trade: True`
- Uses continuous sizing curve based on score

**Example signals and weights:**
- liquidation: 0.22
- funding: 0.16
- whale_flow: 0.20
- ofi_momentum: 0.06
- hurst: 0.08
- lead_lag: 0.08
- etc.

**Sizing curve:**
- score >= 0.50 → 2.0x (ultra high conviction)
- score >= 0.35 → 1.5x (high conviction)
- score >= 0.20 → 1.2x (medium conviction)
- score >= 0.10 → 1.0x (baseline)
- score >= 0.00 → 0.6x (low conviction)
- score < 0.00 → 0.4x (minimum)

### Binary Blocking Gates (AFTER Conviction Gate) ⚠️

**Problem**: These gates override the weighted scoring with binary yes/no:

1. **Intelligence Gate** (`bot_cycle.py:529`)
   - Blocks if CoinGlass intelligence doesn't align
   - Binary decision: allowed/blocked
   - Should instead: reduce sizing multiplier

2. **Fee Gate / ROI Checks** (`bot_cycle.py:1750, 1896, 2040`)
   - Blocks if `sub_fee_roi < minimum`
   - Binary decision: pass/fail
   - Should instead: reduce sizing based on fee impact

3. **Phase 2 Regime Filter** (`bot_cycle.py:468`)
   - Blocks based on regime state
   - Binary decision
   - Should instead: adjust sizing by regime

4. **Other gates**:
   - Correlation throttle
   - Hold governor
   - Exchange health
   - Max positions limit
   - Healing escalation kill switch

## The Issue

**1574 blocked signals with "Unknown" reasons** suggests:
1. Signals are being blocked AFTER conviction gate evaluation
2. Blocking gates aren't properly logging `block_reason` and `block_gate` fields
3. The weighted scoring is being overridden by binary gates

## Recommendation

**Option 1: Convert all gates to sizing adjustments** (Preferred)
- Intelligence gate → reduces sizing multiplier (e.g., 0.8x if intel disagrees)
- Fee gate → reduces sizing based on fee drag
- All gates contribute to final sizing, never block
- Weighted score remains primary decision maker

**Option 2: Properly log blocking reasons**
- Ensure all blocking gates set `block_reason` and `block_gate`
- Log to `signals.jsonl` with proper context
- So we can see WHY signals are blocked

**Option 3: Hybrid approach**
- Keep critical safety gates (kill switch, exchange health) as binary blocks
- Convert performance gates (intelligence, fees, regime) to sizing adjustments
- Ensure all blocks are properly logged

## Current Flow

```
1. Signals generated → Multiple weighted signals
2. Conviction Gate → Weighted score calculated → should_trade: TRUE (always)
3. Intelligence Gate → Binary block (❌ overrides weighted score)
4. Fee Gate → Binary block (❌ overrides weighted score)
5. ROI Check → Binary block if sub_fee_roi too low (❌ overrides weighted score)
6. ... more binary gates ...
7. Trade executes OR gets blocked
```

## Ideal Flow (Weighted Scoring All The Way)

```
1. Signals generated → Multiple weighted signals
2. Conviction Gate → Base weighted score
3. Intelligence Gate → Adjusts score/sizing (e.g., -0.1 if intel disagrees)
4. Fee Gate → Adjusts score/sizing (e.g., -0.05 per 0.1% fee drag)
5. ROI Check → Adjusts sizing (reduces position size if low ROI)
6. Final sizing multiplier calculated from all adjustments
7. Trade executes with appropriate sizing (never blocked, just sized appropriately)
```
