# Hard-Coded Values Audit & Learning Opportunities

## Executive Summary

This audit identifies:
1. **Hard-coded thresholds/multipliers** that should be learned dynamically
2. **Unused logged data** that contains valuable learning signals
3. **Gaps in learning integration** where logged data isn't being consumed
4. **Recommendations** for converting hard-coded values to learned parameters

---

## 1. Hard-Coded Sizing Multipliers (Recently Converted Gates)

### Intelligence Gate (`src/intelligence_gate.py`)
**Current Hard-Coded Values:**
```python
# Line 138: Strong conflict boost
sizing_mult = 1.0 + (intel_confidence * 0.3)  # HARDCODED: 0.3 multiplier

# Line 152-158: Conflict size reductions
sizing_mult = 0.4  # Strong conflict (>=0.6) - HARDCODED
sizing_mult = 0.6  # Moderate conflict (0.4-0.6) - HARDCODED  
sizing_mult = 0.8  # Weak conflict (<0.4) - HARDCODED
```

**What Should Be Learned:**
- Optimal sizing multipliers for each intel conflict level
- Per-symbol intel alignment effectiveness
- Dynamic adjustment based on historical performance

**Logged Data Available (Not Used):**
- `logs/intelligence_gate.log` - All intel gate decisions with outcomes
- `logs/enriched_decisions.jsonl` - Trade outcomes with intel alignment data
- `feature_store/intelligence/summary.json` - Intel signals with confidence

**Action:** Create `IntelligenceGateLearner` that analyzes intel alignment → P&L correlation to optimize multipliers

---

### Fee Gate (`src/fee_aware_gate.py`)
**Current Hard-Coded Values:**
```python
# Line 53: Buffer multiplier
MIN_BUFFER_MULTIPLIER = 1.2  # HARDCODED

# Line 226-231: Size reductions based on fee drag
sizing_mult = 0.3  # Negative EV - HARDCODED
sizing_mult = 0.5 + (0.3 * buffer_ratio)  # Insufficient buffer - HARDCODED (0.5, 0.3)
```

**What Should Be Learned:**
- Optimal buffer multiplier per symbol/volatility regime
- Size reduction curves for different fee drag levels
- Fee impact on profitability (maybe fees are acceptable for high-conviction trades)

**Logged Data Available (Not Used):**
- `logs/fee_gate_learning.json` - Fee gate decisions with outcomes
- `logs/enriched_decisions.jsonl` - Trades with fee cost vs actual P&L
- `feature_store/fee_gate_state.json` - Fee gate statistics

**Action:** Fee gate already has learning (`src/profitability_acceleration_learner.py`), but sizing multipliers aren't learned

---

### Streak Filter (`src/streak_filter.py`)
**Current Hard-Coded Values:**
```python
# Line 149: Win streak boost
mult = min(1.5, 1.0 + (cons_wins * 0.1))  # HARDCODED: 1.5 max, 0.1 per win

# Line 155-165: Loss streak reductions
mult = 0.5  # 3+ losses - HARDCODED
mult = 0.7  # 2 losses - HARDCODED
mult = 0.85  # 1 loss - HARDCODED
```

**What Should Be Learned:**
- Optimal sizing after wins/losses (maybe we're too conservative/aggressive)
- Per-symbol streak effectiveness
- Time-decay for streak effects

**Logged Data Available (Not Used):**
- `state/streak_state_alpha.json` - Streak state but no outcome correlation
- `logs/positions_futures.json` - Trades with streak context at entry
- `logs/enriched_decisions.jsonl` - Trade outcomes with streak state

**Action:** Create `StreakSizingLearner` that analyzes streak state → P&L to optimize multipliers

---

### Regime Filter (`src/regime_filter.py`)
**Current Hard-Coded Values:**
```python
# New method get_regime_sizing_multiplier()
return 0.6  # Regime mismatch - HARDCODED
return 1.0  # Regime match - HARDCODED
```

**What Should Be Learned:**
- Optimal sizing multiplier for regime mismatches (maybe 0.6 is too conservative)
- Per-strategy regime effectiveness
- Dynamic regime thresholds

**Logged Data Available (Not Used):**
- `logs/enriched_decisions.jsonl` - Trades with regime context
- `feature_store/rotation_rules.json` - Regime patterns
- `logs/positions_futures.json` - Trades with regime at entry

**Action:** Create `RegimeSizingLearner` that analyzes regime alignment → P&L

---

## 2. Conviction Gate Hard-Coded Values

### Signal Weights (`src/conviction_gate.py`)
**Current Hard-Coded Values:**
```python
# Line 57-68: Signal weights
DEFAULT_SIGNAL_WEIGHTS = {
    'liquidation': 0.22,  # HARDCODED
    'funding': 0.16,      # HARDCODED
    'oi_velocity': 0.05,  # HARDCODED
    'whale_flow': 0.20,   # HARDCODED
    'ofi_momentum': 0.06, # HARDCODED
    'fear_greed': 0.06,   # HARDCODED
    'hurst': 0.08,        # HARDCODED
    'lead_lag': 0.08,     # HARDCODED
    'volatility_skew': 0.05,  # HARDCODED
    'oi_divergence': 0.04     # HARDCODED
}
```

**Status:** ✅ **PARTIALLY LEARNED** - `src/signal_weight_learner.py` updates these, but:
- Defaults are still hard-coded fallbacks
- Learning might not be aggressive enough
- No per-symbol/per-regime weights

**Logged Data Available (Used):**
- `logs/conviction_gate.jsonl` - Decision with score breakdown
- `logs/enriched_decisions.jsonl` - Outcomes with signal contributions
- `feature_store/signal_weights_gate.json` - Learned weights (updated nightly)

**Action:** Verify learning is working and optimize learning rate/aggressiveness

---

### Score-to-Sizing Curve (`src/conviction_gate.py`)
**Current Hard-Coded Values:**
```python
# Line 240-255: SCORE_TO_SIZE_CURVE
SCORE_TO_SIZE_CURVE = [
    (0.50, 2.0, 'ULTRA'),    # HARDCODED thresholds
    (0.35, 1.5, 'HIGH'),
    (0.20, 1.2, 'MEDIUM'),
    (0.10, 1.0, 'BASELINE'),
    (0.00, 0.6, 'LOW'),
    (-999, 0.4, 'MINIMUM')
]
```

**What Should Be Learned:**
- Optimal score thresholds (maybe 0.50 is too high/low)
- Optimal sizing multipliers for each conviction level
- Per-symbol/per-regime curves

**Logged Data Available (Not Used):**
- `logs/conviction_gate.jsonl` - Score → conviction → outcome
- `logs/positions_futures.json` - Actual P&L vs conviction level

**Action:** Create `ConvictionCurveLearner` that optimizes thresholds and multipliers

---

## 3. ROI/Fee Thresholds

### ROI Thresholds (`src/bot_cycle.py`)
**Current Hard-Coded Values:**
```python
# Multiple locations: ROI threshold checks
roi_threshold = 0.0005  # HARDCODED: 0.05% minimum
roi_sizing_mult = max(0.4, min(0.8, ...))  # HARDCODED sizing reduction
```

**What Should Be Learned:**
- Optimal ROI thresholds per symbol/strategy
- Dynamic thresholds based on market volatility
- Fee drag tolerance (maybe we can accept lower ROI if signal quality is high)

**Logged Data Available (Not Used):**
- `logs/enriched_decisions.jsonl` - ROI at signal vs actual outcome
- `logs/positions_futures.json` - Entry ROI vs exit P&L

**Action:** Create `ROIThresholdLearner` that finds optimal thresholds

---

## 4. Unused Logged Data

### Signal Universe Tracker (`logs/signals.jsonl` via `src/signal_universe_tracker.py`)
**What's Logged:**
- Every signal with full intelligence context (OFI, ensemble, MTF, CoinGlass, fear/greed, taker ratio, liquidation bias)
- Entry price, disposition (EXECUTED/BLOCKED/SKIPPED)
- Counterfactual tracking pending status

**What's NOT Being Used:**
- ❌ CoinGlass taker_ratio patterns → profitability correlation
- ❌ Liquidation bias patterns → optimal entry timing
- ❌ Fear/greed extremes → contrarian opportunities
- ❌ Multi-signal combinations (OFI + CoinGlass + MTF) → optimal combinations

**Action:** Feed this into `ExpansiveMultiDimensionalProfitabilityAnalyzer` or create dedicated analyzer

---

### Blocked Signals (`logs/blocked_signals.jsonl`)
**What's Logged:**
- All blocked signals with block_reason, block_gate, signal context
- Counterfactual outcomes (what would have happened)

**What's NOT Being Used:**
- ❌ Block reason effectiveness analysis (which blocks were correct/wrong)
- ❌ Gate-level profitability attribution (did this gate save money or cost money?)
- ❌ Dynamic gate threshold optimization

**Action:** `beta_learning_system.py` has counterfactual analysis, but not used for gate optimization

---

### Enriched Decisions (`logs/enriched_decisions.jsonl`)
**What's Logged:**
- Full signal context (50+ ML features)
- Entry/exit prices
- P&L and fees
- Signal breakdown (which signals contributed)
- Regime, volatility, volume patterns
- CoinGlass data at entry

**What's NOT Being Used:**
- ✅ Partially used by `expansive_multi_dimensional_profitability_analyzer.py`
- ❌ Not used for real-time gate optimization
- ❌ Not used for dynamic threshold adjustment
- ❌ Not used for per-symbol/per-strategy parameter learning

**Action:** Create real-time learning feedback loop that updates gates based on recent decisions

---

### Fee Gate Log (`logs/fee_gate_learning.json`)
**What's Logged:**
- Every fee gate decision (ALLOW/BLOCK)
- Expected move, breakeven move, edge ratio
- Fee cost in USD and %
- Decision timestamp

**What's NOT Being Used:**
- ❌ Size reduction optimization (sizing multipliers aren't learned)
- ❌ Per-symbol fee tolerance (maybe BTC can handle lower ROI due to lower fees)
- ❌ Dynamic buffer multiplier based on market conditions

**Action:** Extend `profitability_acceleration_learner.py` to learn sizing multipliers

---

## 5. Recommendations

### Priority 1: Convert Sizing Multipliers to Learned Parameters

1. **Create `IntelligenceGateSizingLearner`**
   - Analyze intel alignment → P&L correlation
   - Optimize multipliers for strong/moderate/weak conflicts
   - Update `feature_store/intelligence_gate_sizing.json`

2. **Create `StreakSizingLearner`**
   - Analyze streak state → P&L correlation
   - Optimize win/loss streak multipliers
   - Update `feature_store/streak_sizing_weights.json`

3. **Create `RegimeSizingLearner`**
   - Analyze regime alignment → P&L correlation
   - Optimize mismatch multiplier (currently 0.6)
   - Update `feature_store/regime_sizing_weights.json`

4. **Extend Fee Gate Learning**
   - Learn sizing multipliers for fee drag levels
   - Per-symbol fee tolerance
   - Dynamic buffer multiplier

### Priority 2: Optimize Conviction Gate Curves

5. **Create `ConvictionCurveLearner`**
   - Optimize score thresholds (0.50, 0.35, 0.20, etc.)
   - Optimize sizing multipliers (2.0x, 1.5x, 1.2x, etc.)
   - Per-symbol/per-regime curves

### Priority 3: Leverage Unused Logged Data

6. **Feed Signal Universe Data to Analyzer**
   - Add CoinGlass patterns analysis
   - Add multi-signal combination optimization
   - Add contrarian opportunity detection

7. **Real-Time Gate Optimization**
   - Continuous feedback loop from `enriched_decisions.jsonl`
   - Dynamic threshold adjustment based on recent outcomes
   - Per-symbol parameter adaptation

### Priority 4: ROI/Fee Threshold Learning

8. **Create `ROIThresholdLearner`**
   - Dynamic ROI thresholds per symbol/strategy
   - Fee drag tolerance based on signal quality
   - Market volatility-adjusted thresholds

---

## 6. Implementation Plan

### Phase 1: Sizing Multiplier Learners (High Impact, Medium Effort)
- Create 4 new learner modules
- Integrate into nightly learning cycle
- Test with historical data

### Phase 2: Conviction Curve Optimization (High Impact, High Effort)
- Create curve learner
- Validate with backtesting
- Gradual rollout

### Phase 3: Unused Data Integration (Medium Impact, Low Effort)
- Extend existing analyzers
- Add new analysis dimensions
- Feed insights back to gates

### Phase 4: Real-Time Learning (High Impact, High Effort)
- Create continuous feedback loop
- Real-time parameter updates
- Safety guardrails

---

## Summary

**Hard-Coded Values Found:**
- 20+ sizing multipliers that should be learned
- 10 signal weights (partially learned)
- 6 score-to-sizing thresholds
- Multiple ROI/fee thresholds

**Unused Logged Data:**
- Signal universe tracker data (rich intelligence context)
- Blocked signals counterfactuals
- Fee gate decision history
- Enriched decisions (partially used)

**Next Steps:**
1. Implement sizing multiplier learners
2. Optimize conviction gate curves
3. Integrate unused logged data into learning
4. Create real-time feedback loops
