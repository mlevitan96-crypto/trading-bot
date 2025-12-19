# Learning Optimization Plan

## Critical Findings

### 1. Hard-Coded Sizing Multipliers (Just Converted - Need Learning)

**Intelligence Gate:**
- Strong conflict: 0.4x (HARDCODED)
- Moderate conflict: 0.6x (HARDCODED)
- Weak conflict: 0.8x (HARDCODED)
- **Impact:** These values are guesses - should learn from intel alignment → P&L data

**Streak Filter:**
- 3+ wins: 1.5x max, 0.1x per win (HARDCODED)
- 3+ losses: 0.5x (HARDCODED)
- 2 losses: 0.7x (HARDCODED)
- 1 loss: 0.85x (HARDCODED)
- **Impact:** May be too conservative or too aggressive - need historical data

**Fee Gate:**
- Negative EV: 0.3x (HARDCODED)
- Insufficient buffer: 0.5x-0.8x (HARDCODED curve)
- Buffer multiplier: 1.2x (HARDCODED)
- **Impact:** Fee gate has learning, but sizing multipliers aren't learned

**Regime Filter:**
- Mismatch: 0.6x (HARDCODED)
- **Impact:** Maybe 0.6x is too conservative - some mismatches might still be profitable

### 2. Conviction Gate Hard-Coded Values

**Score-to-Sizing Curve:**
- ULTRA (0.50): 2.0x (HARDCODED)
- HIGH (0.35): 1.5x (HARDCODED)
- MEDIUM (0.20): 1.2x (HARDCODED)
- BASELINE (0.10): 1.0x (HARDCODED)
- LOW (0.00): 0.6x (HARDCODED)
- MINIMUM (-999): 0.4x (HARDCODED)
- **Impact:** Thresholds and multipliers should be optimized per symbol/regime

**Signal Weights:**
- ✅ PARTIALLY LEARNED via `signal_weight_learner.py`
- But defaults are still hard-coded fallbacks
- No per-symbol/per-regime weights

### 3. Unused Logged Data (High Value)

**Signal Universe Tracker** (`logs/signals.jsonl`):
- Logs: CoinGlass taker_ratio, liquidation_bias, fear_greed, full intelligence context
- NOT USED: Pattern analysis for optimal entry timing, contrarian opportunities

**Blocked Signals** (`logs/blocked_signals.jsonl`):
- Logs: All blocked signals with counterfactual outcomes
- NOT USED: Gate effectiveness analysis (which gates are correct/wrong)

**Fee Gate Log** (`logs/fee_gate_learning.json`):
- Logs: Every fee decision with expected move, edge ratio
- NOT USED: Sizing multiplier optimization

**Enriched Decisions** (`logs/enriched_decisions.jsonl`):
- Logs: 50+ ML features, signal breakdown, outcomes
- PARTIALLY USED: Analyzed by expansive analyzer, but not used for real-time gate optimization

---

## Implementation Priority

### Phase 1: Sizing Multiplier Learners (HIGH IMPACT)

Create learners that analyze sizing multiplier effectiveness:
1. `IntelligenceGateSizingLearner` - Learn optimal multipliers for intel conflicts
2. `StreakSizingLearner` - Learn optimal multipliers for streaks
3. `RegimeSizingLearner` - Learn optimal multiplier for regime mismatches
4. Extend `FeeGateLearning` - Learn sizing multipliers, not just allow/block

### Phase 2: Conviction Curve Optimization

5. `ConvictionCurveLearner` - Optimize score thresholds and multipliers
6. Per-symbol/per-regime curves

### Phase 3: Leverage Unused Data

7. Feed Signal Universe data into profitability analyzer
8. Gate effectiveness analysis from blocked signals
9. Real-time gate optimization from enriched decisions

---

## Next Steps

See `HARDCODED_VALUES_AUDIT.md` for complete details and implementation plan.
