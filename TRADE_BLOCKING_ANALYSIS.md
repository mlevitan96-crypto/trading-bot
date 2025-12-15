# Trading Bot Signal Pipeline Analysis
## Why Trades Are Not Executing

**Date:** 2025-12-14  
**Status:** `signals_active = false`, No entries in `signal_outcomes.jsonl`

---

## Signal Pipeline Flow

```
1. predictive_signals.jsonl ✅ (UPDATING)
   └─> PredictiveFlowEngine.generate_signal()
   
2. ensemble_predictions.jsonl ✅ (UPDATING)
   └─> EnsemblePredictor.get_ensemble_prediction()
   
3. Conviction Gate (Weighted Scoring)
   └─> ConvictionGate.evaluate() / should_trade()
   └─> ⚠️ SIGNALS LOGGED HERE via signal_tracker.log_signal()
   
4. Fee Gate
   └─> FeeAwareGate.evaluate_entry() / fee_arbiter()
   
5. Correlation Throttle
   └─> CorrelationThrottle.check_throttle()
   
6. Hold Governor
   └─> pre_entry_check() / unified_pre_entry_gate()
   
7. Final Signal → Trade Execution
   └─> run_entry_flow() → open_order_fn()
   └─> signal_outcomes.jsonl ❌ (NOT UPDATING)
```

---

## CRITICAL FINDING: Signal Logging Location

**`signal_outcomes.jsonl` is ONLY written when:**
1. `signal_tracker.log_signal()` is called (in `conviction_gate.py` line 423)
2. Signals are resolved at forward horizons (1m, 5m, 15m, 30m, 1h)

**The problem:** If signals are blocked BEFORE reaching the conviction gate, OR if the conviction gate isn't being called, signals won't be logged to `signal_outcomes.jsonl`.

---

## Blocking Points Analysis

### 1. **ALPHA SIGNAL POLICY CHECK** (bot_cycle.py:1272-1286)
**Location:** `bot_cycle.py` lines 1272-1286

```python
signal_policy_path = Path("configs/signal_policies.json")
alpha_policy = {}
if signal_policy_path.exists():
    with open(signal_policy_path) as f:
        policy_data = json_mod.load(f)
        alpha_policy = policy_data.get("alpha_trading", {})

alpha_enabled = alpha_policy.get("enabled", False)
enabled_symbols = alpha_policy.get("enabled_symbols", [])

if alpha_enabled and symbol in enabled_symbols:
    # Only then does it proceed to conviction gate
```

**BLOCKING RISK:** HIGH
- If `alpha_trading.enabled = false` → No signals processed
- If symbol not in `enabled_symbols` → Signal skipped
- **FIX:** Check `configs/signal_policies.json` and ensure `alpha_trading.enabled = true` and symbols are listed

---

### 2. **ALPHA COOLDOWN** (bot_cycle.py:1290-1295)
**Location:** `bot_cycle.py` lines 1290-1295

```python
last_alpha_ts = getattr(run_bot_cycle, '_alpha_last_trade', {}).get(symbol, 0)
on_alpha_cooldown = (time.time() - last_alpha_ts) < cooldown_secs

if on_alpha_cooldown:
    print(f"   ⏸️ [ALPHA] {symbol}: On cooldown")
    continue  # SKIPS CONVICTION GATE
```

**BLOCKING RISK:** MEDIUM
- If cooldown is too long, signals are skipped before reaching conviction gate
- **FIX:** Check `alpha_policy.get("cooldown_seconds", 120)` - reduce if too restrictive

---

### 3. **STREAK FILTER** (bot_cycle.py:1300-1304)
**Location:** `bot_cycle.py` lines 1300-1304

```python
streak_allowed, streak_reason, streak_mult = check_streak_gate(symbol, direction, "alpha")
if not streak_allowed:
    print(f"   🔴 [ALPHA] {symbol}: Streak filter blocked ({streak_reason})")
    continue  # SKIPS CONVICTION GATE
```

**BLOCKING RISK:** MEDIUM
- If symbol has recent losses, streak filter blocks before conviction gate
- **FIX:** Check `src/streak_filter.py` - may need to relax thresholds or convert to size reduction instead of blocking

---

### 4. **CONVICTION GATE CALL** (bot_cycle.py:1310-1316)
**Location:** `bot_cycle.py` lines 1310-1316

```python
conviction_result = evaluate_trade_opportunity(
    symbol=symbol,
    alpha_signals=alpha_signals,
    current_price=current_price,
    regime=regime,
    portfolio_value=portfolio.get("current_value", 10000.0)
)
```

**This is where signals SHOULD be logged via `signal_tracker.log_signal()`**

**BLOCKING RISK:** LOW (if reached)
- If `evaluate_trade_opportunity` returns `should_trade = False`, signal is logged but trade doesn't execute
- **CHECK:** Verify `enhanced_signal_router.py` is calling `conviction_should_trade()` correctly

---

### 5. **MTF CONFIDENCE CHECK** (bot_cycle.py:1321-1325)
**Location:** `bot_cycle.py` lines 1321-1325

```python
mtf_conf, mtf_data = get_mtf_confidence_score(
    symbol, "Sentiment-Fusion", blofin, 
    alpha_side=alpha_signals['combined_signal']
)
```

**BLOCKING RISK:** LOW (used for sizing, not blocking)

---

### 6. **ALPHA ENTRY WRAPPER** (bot_cycle.py:1338-1348)
**Location:** `bot_cycle.py` lines 1338-1348

```python
ok, entry_tel = alpha_entry_wrapper(
    symbol=symbol,
    ofi_confidence=ofi_conf,
    ensemble_score=ensemble_score,
    mtf_confidence=mtf_conf,
    expected_edge_hint=conviction_result['expected_edge'],
    base_notional_usd=base_margin * adjusted_size_mult,
    portfolio_value_snapshot_usd=portfolio.get("current_value", 10000.0),
    side="long" if direction == "LONG" else "short",
    open_order_fn=blofin_open_order_fn
)
```

**BLOCKING RISK:** HIGH
- `alpha_entry_wrapper` calls `run_entry_flow()` which has multiple gates
- If any gate blocks, trade doesn't execute
- **FIX:** Check `alpha_entry_wrapper` implementation in `full_integration_blofin_micro_live_and_paper.py`

---

### 7. **RUN_ENTRY_FLOW GATES** (full_integration_blofin_micro_live_and_paper.py:926-1084)

#### 7a. **Counter-Signal Orchestrator** (lines 953-965)
- May invert signal direction
- **BLOCKING RISK:** LOW (modifies, doesn't block)

#### 7b. **Streak Filter** (lines 972-985)
- **BLOCKING RISK:** MEDIUM
- In "EXPLORATION MODE" it reduces size instead of blocking, but check if mode is active

#### 7c. **Intelligence Gate** (lines 1007-1018)
- **BLOCKING RISK:** MEDIUM
- In "EXPLORATION MODE" it reduces size instead of blocking, but check if mode is active

#### 7d. **Fee-Aware Gate** (lines 1028-1039)
- **BLOCKING RISK:** LOW (sizing only in exploration mode)

#### 7e. **Symbol Allowed Check** (lines 1041-1045)
```python
allowed = rt.get("allowed_symbols_mode", [])
if allowed and symbol not in allowed:
    return False, {"reason": "symbol_not_allowed_in_mode"}
```
**BLOCKING RISK:** HIGH
- If `allowed_symbols_mode` is set and symbol not in list → BLOCKED
- **FIX:** Check `live_config.json` → `runtime.allowed_symbols_mode`

#### 7f. **Pre-Entry Check** (lines 1047-1053)
```python
ok, ctx = pre_entry_check(symbol, strategy_id, final_notional, ...)
if not ok:
    # In exploration mode: reduces to $200 minimum
    final_notional = 200.0
```
**BLOCKING RISK:** MEDIUM
- May block if not in exploration mode
- **FIX:** Check `pre_entry_check()` implementation

#### 7g. **Correlation Throttle** (lines 1058-1073)
- **BLOCKING RISK:** LOW (reduces size, doesn't block)

---

### 8. **EXECUTION GATES** (execution_gates.py:51-103)

#### 8a. **MTF Confirmation** (line 95)
```python
if not mtf_confirmed:
    return _log_block(symbol, predicted_roi, "mtf_not_confirmed", ts)
```
**BLOCKING RISK:** HIGH
- If multi-timeframe confirmation fails → BLOCKED
- **FIX:** Check MTF confirmation logic

#### 8b. **ROI Gate** (lines 99-100)
```python
if predicted_roi < roi_gate:
    return _log_block(symbol, predicted_roi, f"roi_below_{roi_gate:.4f}", ts)
```
**BLOCKING RISK:** HIGH
- If predicted ROI below threshold → BLOCKED
- **FIX:** Check ROI thresholds in:
  - `logs/execution_governor.json`
  - `logs/fee_arbiter.json`
  - `logs/correlation_throttle.json`

#### 8c. **Hourly Cap** (line 103)
```python
if not can_trade_now(max_trades_hour):
    return _log_block(symbol, predicted_roi, "hourly_cap_exceeded", ts)
```
**BLOCKING RISK:** MEDIUM
- If hourly trade limit reached → BLOCKED
- **FIX:** Check `max_trades_hour` in governor files

---

### 9. **SIGNAL OUTCOME TRACKER RESOLUTION**

**Even if signals are logged, `signal_outcomes.jsonl` only updates when:**
1. `signal_tracker.resolve_pending_signals()` is called periodically
2. Signals reach their resolution horizons (1m, 5m, 15m, 30m, 1h)

**BLOCKING RISK:** MEDIUM
- If resolution function isn't being called → outcomes never written
- **FIX:** Check if `resolve_pending_signals()` is scheduled in main loop

---

## Root Cause Analysis

### Primary Suspects (In Order of Likelihood):

1. **SIGNAL RESOLUTION NOT RUNNING FREQUENTLY** (85% confidence)
   - `resolve_pending_signals()` only called in learning cycles (not every minute)
   - Signals logged to `pending_signals.json` but not resolved → `signal_outcomes.jsonl` never updates
   - **IMPACT:** `signals_active = false` because outcomes file not updating
   - **FIX:** Ensure `signal_tracker.resolve_pending_signals()` runs every 60 seconds

2. **SIGNALS BLOCKED BEFORE CONVICTION GATE** (75% confidence)
   - Alpha cooldown, streak filter, or OFI threshold blocking signals
   - **IMPACT:** Signals never reach conviction gate → never logged
   - **FIX:** Check `min_ofi_confidence` (0.5) and `cooldown_seconds` (120) in signal_policies.json

3. **MTF CONFIRMATION FAILING** (70% confidence)
   - Multi-timeframe confirmation always returning `False`
   - **IMPACT:** Execution gates block all trades
   - **FIX:** Check MTF confirmation logic and thresholds

4. **ROI GATE TOO STRICT** (60% confidence)
   - ROI thresholds set too high (0.5% = 0.005)
   - **IMPACT:** All signals blocked by ROI gate
   - **FIX:** Lower ROI thresholds for paper trading (0.05% = 0.0005)

5. **ALPHA ENTRY WRAPPER BLOCKING** (55% confidence)
   - `alpha_entry_wrapper()` or `run_entry_flow()` blocking before execution
   - **IMPACT:** Signals pass conviction gate but blocked in entry flow
   - **FIX:** Check `alpha_entry_wrapper` implementation and gate logs

6. **SYMBOL RESTRICTIONS** (50% confidence)
   - `live_config.json` → `runtime.allowed_symbols_mode` restricts symbols
   - **IMPACT:** Signals blocked in `run_entry_flow()` before execution
   - **FIX:** Ensure `allowed_symbols_mode` is empty or includes all symbols

---

## Diagnostic Commands

Run these on your DigitalOcean droplet to diagnose:

```bash
# 1. Check alpha signal policy
cat configs/signal_policies.json | jq '.alpha_trading'

# 2. Check allowed symbols
cat live_config.json | jq '.runtime.allowed_symbols_mode'

# 3. Check ROI thresholds
cat logs/execution_governor.json | jq '.roi_threshold'
cat logs/fee_arbiter.json | jq '.roi_gate'
cat logs/correlation_throttle.json | jq '.roi_threshold'

# 4. Check hourly trade cap
cat logs/execution_governor.json | jq '.max_trades_hour'

# 5. Check if signals are being logged (pending signals)
cat feature_store/pending_signals.json | jq 'keys | length'

# 6. Check recent signal activity
tail -20 logs/predictive_signals.jsonl | jq -r '.symbol, .direction, .conviction'

# 7. Check if conviction gate is being called
grep -r "evaluate_trade_opportunity" logs/*.log | tail -10

# 8. Check execution gate blocks
grep -r "blocked\|rejected" logs/*.jsonl | tail -20
```

---

## Proposed Fixes

### Fix 1: Enable Alpha Trading Policy
**File:** `configs/signal_policies.json`

```json
{
  "alpha_trading": {
    "enabled": true,
    "min_ofi_confidence": 0.3,
    "min_ensemble_score": 0.2,
    "initial_size_multiplier": 0.5,
    "enabled_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT", "DOTUSDT", "TRXUSDT"],
    "cooldown_seconds": 60
  }
}
```

### Fix 2: Remove Symbol Restrictions
**File:** `live_config.json`

```json
{
  "runtime": {
    "allowed_symbols_mode": []  // Empty = all symbols allowed
  }
}
```

### Fix 3: Lower ROI Thresholds (Paper Trading Mode)
**Files:** `logs/execution_governor.json`, `logs/fee_arbiter.json`

```json
{
  "roi_threshold": 0.0005,  // 0.05% instead of 0.5%
  "max_trades_hour": 10     // Increase from 2
}
```

### Fix 4: Ensure Signal Resolution Runs
**File:** `src/bot_cycle.py` or scheduler

Add to main loop:
```python
from src.signal_outcome_tracker import signal_tracker
signal_tracker.resolve_pending_signals()
```

### Fix 5: Add Diagnostic Logging
**File:** `src/bot_cycle.py` (around line 1286)

Add logging before alpha signal processing:
```python
if not alpha_enabled:
    print(f"⚠️ [DIAGNOSTIC] Alpha trading DISABLED in signal_policies.json")
if symbol not in enabled_symbols:
    print(f"⚠️ [DIAGNOSTIC] {symbol} not in enabled_symbols list")
```

---

## Verification Steps

After applying fixes:

1. **Monitor signal generation:**
   ```bash
   tail -f logs/predictive_signals.jsonl
   ```

2. **Monitor conviction gate:**
   ```bash
   tail -f logs/conviction_gate.jsonl
   ```

3. **Monitor execution gates:**
   ```bash
   tail -f logs/execution_gates.jsonl
   ```

4. **Monitor signal outcomes:**
   ```bash
   tail -f logs/signal_outcomes.jsonl
   ```

5. **Check pending signals:**
   ```bash
   watch -n 5 'cat feature_store/pending_signals.json | jq "keys | length"'
   ```

---

## Summary

**Most Likely Root Cause:**
Alpha trading is disabled in `configs/signal_policies.json`, OR symbols are restricted in `live_config.json`, preventing signals from reaching the conviction gate where they would be logged to `signal_outcomes.jsonl`.

**Quick Fix:**
1. Enable alpha trading: `configs/signal_policies.json` → `alpha_trading.enabled = true`
2. Remove symbol restrictions: `live_config.json` → `runtime.allowed_symbols_mode = []`
3. Lower ROI thresholds for paper trading mode
4. Verify signal resolution is running

**Expected Result:**
- Signals flow through conviction gate → logged to pending_signals.json
- Signals resolve at horizons → written to signal_outcomes.jsonl
- Trades execute when gates pass

