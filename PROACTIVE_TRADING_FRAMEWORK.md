# Proactive Trading Framework
**Understanding WHY, Not Just WHAT**

## Philosophy

### Reactive (What We're Avoiding)
- "Hour 1 wins 71% → Loosen gates for hour 1"
- "Sentiment-Fusion loses → Reduce weight"
- **Problem:** We're reacting to correlations without understanding causes

### Proactive (What We're Building)
- "Hour 1 wins because OFI is 0.6+ and regime is Trending during that hour"
- "Trade when OFI >= 0.6 AND regime == Trending, regardless of hour"
- **Solution:** We understand WHY and predict based on current market state

## Causal Analysis Framework

### Step 1: Identify Patterns (WHAT)
- Hour 1: 71% win rate
- Sentiment-Fusion: 35% win rate
- OFI > 0.5: 60% win rate

### Step 2: Understand Causes (WHY)
- **Hour 1 Analysis:**
  - Winners in hour 1: Avg OFI = 0.65, Regime = Trending
  - Losers in hour 1: Avg OFI = 0.25, Regime = Choppy
  - **Causal Factor:** High OFI + Trending regime, not the hour itself

- **Sentiment-Fusion Analysis:**
  - Winners: Avg OFI = 0.55, Regime = Stable
  - Losers: Avg OFI = 0.20, Regime = Volatile
  - **Causal Factor:** Low OFI + Wrong regime, not the strategy itself

### Step 3: Build Predictive Rules (PROACTIVE)
- **Rule 1:** Trade when `OFI >= 0.6 AND regime == Trending` (regardless of hour)
- **Rule 2:** Use Sentiment-Fusion only when `OFI >= 0.5 AND regime == Stable`
- **Rule 3:** Avoid trades when `OFI < 0.3 OR regime == Choppy`

### Step 4: Implement Proactively
- Check current market conditions (OFI, regime, volatility)
- Match against successful patterns
- Trade when conditions match, skip when they don't
- **Not based on hour, but on market state**

## Implementation

### 1. Causal Pattern Analyzer
**File:** `causal_pattern_analyzer.py`
- Analyzes WHY trades succeed/fail
- Identifies market conditions that lead to success
- Generates proactive rules based on understanding

### 2. Proactive Decision Engine
**Integration Point:** `src/conviction_gate.py`
- Before entry, check current market conditions
- Match against causal patterns
- Only trade when conditions match successful patterns
- Skip trades that match losing patterns

### 3. Continuous Learning
- Update causal patterns as new data arrives
- Refine understanding of WHY
- Improve predictive rules over time

## Example: Hour-Based Analysis

### Reactive Approach (WRONG)
```
Hour 1: 71% win rate → Loosen gates for hour 1
Result: We trade more during hour 1, but don't know why it works
```

### Proactive Approach (RIGHT)
```
Hour 1 Analysis:
- Winners: OFI=0.65, Regime=Trending, Volume=High
- Losers: OFI=0.25, Regime=Choppy, Volume=Low

Causal Understanding:
- Hour 1 wins because market conditions are favorable (high OFI + trending)
- Not because it's hour 1

Proactive Rule:
- Trade when OFI >= 0.6 AND regime == Trending (any hour)
- Don't trade just because it's hour 1 if conditions don't match
```

## Benefits

1. **Predictive:** We predict success based on current market state
2. **Adaptive:** Rules work across all hours, not just specific times
3. **Understanding:** We know WHY things work, not just that they work
4. **Proactive:** We act on understanding, not just correlation

## Next Steps

1. Run `causal_pattern_analyzer.py` to identify causal factors
2. Review causal insights to understand WHY
3. Implement proactive rules in conviction_gate.py
4. Test proactive approach in paper trading
5. Monitor if proactive approach improves performance
