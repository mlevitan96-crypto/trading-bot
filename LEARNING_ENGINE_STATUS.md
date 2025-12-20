# Learning Engine Status & Analysis

**Date:** 2025-12-20  
**Question:** What is the learning engine looking at and is it providing updates?

---

## YES - You Have Comprehensive Learning Systems

You have **multiple learning systems** that review everything and provide updates to the trade engine. Here's what they're doing:

---

## Active Learning Systems

### 1. Continuous Learning Controller (Every 12 Hours)

**Location:** `src/continuous_learning_controller.py`  
**Schedule:** Every 12 hours (from `run.py` line 863)  
**Status:** ✅ Running (started in bot_worker)

**What It Analyzes:**
- ✅ Executed trades (last 168 hours / 7 days)
- ✅ Blocked signals (from signal universe)
- ✅ Missed opportunities (counterfactual)
- ✅ Signal outcomes (from signal_outcome_tracker)

**What It Updates:**
1. **Signal Weights** (`feature_store/signal_weights.json`)
   - Adjusts weights based on signal performance
   - Increases weights of profitable signals
   - Decreases weights of unprofitable signals
   - Max change: ±20% per update

2. **Conviction Gate Thresholds**
   - Tightens/loosens gates based on guard effectiveness
   - Adjusts conviction level requirements

3. **Sizing Multipliers**
   - Calibrates conviction → size mapping
   - Adjusts based on realized edge per conviction level

4. **Killed Combos**
   - Identifies symbol+direction combos with poor performance
   - Blocks combos with <40% WR and negative P&L

**How It Works:**
```python
controller = ContinuousLearningController()
state = controller.run_learning_cycle()  # Analyzes everything
controller.apply_adjustments(dry_run=False)  # Updates system files
```

**Current Issue:** 
- Signal weights at defaults (0 outcomes < 50 required)
- Need signal outcome data to optimize weights

---

### 2. Unified Scheduler (Every 10 Minutes + Nightly)

**Location:** `src/scheduler_with_analysis.py`  
**Schedule:** 
- Every 10 minutes: Fee audits, recovery cycles
- Nightly at 07:00 UTC: Comprehensive learning cycle

**What It Analyzes (Nightly):**

**Phase 1: Data Preparation**
- ✅ Data enrichment (joins signals + outcomes)
- ✅ Pipeline self-heal (fixes paths, quarantines dead files)

**Phase 2: Parameter Optimization**
- ✅ Scenario auto-tuner (grid search with WR/PnL gates)
- ✅ Scenario slicer auto-tuner (per-slice optimization)

**Phase 3: Performance Acceleration**
- ✅ Upgrade pack v7.2+ (backtest, regime detect, gate optimizer)
- ✅ Sizing multiplier learners
- ✅ Profitability acceleration learners

**Phase 4: Comprehensive Learning**
- ✅ Counterfactual learning (60m horizon)
- ✅ Multi-horizon attribution (5m, 60m, 1d, 1w)
- ✅ Missed opportunity probe
- ✅ Horizon-weighted evolution
- ✅ Gate complexity monitor
- ✅ Meta-governance watchdogs
- ✅ Multi-agent coordinator (Alpha/EMA allocation)
- ✅ Strategy auto-tuning

**Phase 5: Profit-First Allocation**
- ✅ Profit-driven evolution (attribution-weighted calibration)
- ✅ Profit-first governor (strategy/symbol allocation)

**What It Updates:**
- Signal weights
- Gate thresholds
- Sizing multipliers
- Strategy parameters
- Symbol allocation
- Hold time policies
- Fee gate thresholds
- Edge sizer multipliers

---

### 3. Signal Weight Learner

**Location:** `src/signal_weight_learner.py`  
**Called By:** Continuous Learning Controller  
**Schedule:** Every learning cycle

**What It Analyzes:**
- Signal outcomes from `logs/signal_outcomes.jsonl`
- Signal performance at each horizon (1m, 5m, 15m, 30m, 1h)
- Expected value (EV) contribution per signal

**What It Updates:**
- `feature_store/signal_weights_gate.json`
- Adjusts weights based on EV contribution
- Finds optimal horizon for each signal

**Current Status:**
- Needs 50+ outcomes per signal to adjust
- Currently: 0 outcomes (weights at defaults)

---

### 4. Enhanced Signal Learner

**Location:** `src/enhanced_signal_learner.py`  
**What It Analyzes:**
- Exponentially weighted moving averages (EWMA) for signal EV
- Per-symbol, per-direction signal effectiveness
- Cross-signal correlation (which signals work together)
- Regime-aware performance tracking

**What It Updates:**
- Signal weights based on correlation
- Direction routing recommendations
- Regime-specific adjustments

---

### 5. Daily Intelligence Learner

**Location:** `src/daily_intelligence_learner.py`  
**Schedule:** Nightly (via scheduler)

**What It Analyzes:**
- Executed trades
- Blocked signals
- Missed opportunities
- Counterfactual outcomes

**What It Updates:**
- `feature_store/daily_learning_rules.json`
- Pattern discoveries
- Trading rules

**Current Status:**
- Learning health shows "Daily learning rules file missing"
- May not be running or may have errors

---

### 6. Profit-Driven Evolution

**Location:** `src/profit_driven_evolution.py`  
**Schedule:** Nightly (via scheduler)

**What It Analyzes:**
- Profit attribution (what changes led to profit/loss)
- Runtime config performance
- Policy effectiveness

**What It Updates:**
- Runtime configs
- Trading policies
- Profit targets
- Fee gate thresholds

---

### 7. Profit-First Governor

**Location:** `src/profit_first_governor.py`  
**Schedule:** Nightly (via scheduler)

**What It Analyzes:**
- Realized profits per strategy
- Realized profits per symbol
- Capital allocation effectiveness

**What It Updates:**
- Strategy allocation (promote/demote based on profits)
- Symbol allocation (reallocate capital to winners)
- Venue allocation

---

## What the Learning Systems Are Looking At

### Data Sources Analyzed:

1. **Executed Trades** (`logs/positions_futures.json`)
   - P&L, win/loss
   - Entry/exit timing
   - Symbol, direction, strategy
   - Signal context (if available)

2. **All Signals** (`logs/signals.jsonl`)
   - Executed signals
   - Blocked signals
   - Signal components (OFI, ensemble, etc.)
   - Intelligence data

3. **Signal Outcomes** (`logs/signal_outcomes.jsonl`)
   - Did signal direction match price move?
   - How much did price move?
   - EV contribution at each horizon

4. **Missed Opportunities** (`logs/missed_opportunities.jsonl`)
   - What would have happened if we traded?
   - Counterfactual P&L

5. **Counterfactual Outcomes** (`logs/counterfactual_outcomes.jsonl`)
   - What-if scenarios
   - Alternative outcomes

6. **Enriched Decisions** (`logs/enriched_decisions.jsonl`)
   - Signals + outcomes joined
   - Complete context for learning

---

## Updates Provided to Trade Engine

### 1. Signal Weight Updates
- **File:** `feature_store/signal_weights_gate.json`
- **Used By:** Conviction gate, signal fusion
- **Impact:** Changes which signals have more influence

### 2. Gate Threshold Adjustments
- **Files:** Various gate state files
- **Used By:** Entry gates, fee gates, correlation throttle
- **Impact:** Tightens/loosens entry requirements

### 3. Sizing Multiplier Calibration
- **Files:** Edge sizer calibration, conviction size maps
- **Used By:** Position sizing
- **Impact:** Changes position sizes based on conviction/edge

### 4. Killed Combos
- **File:** `feature_store/blocked_combos.json`
- **Used By:** Entry gates
- **Impact:** Blocks unprofitable symbol+direction combos

### 5. Strategy/Symbol Allocation
- **Files:** Strategy attribution, symbol allocation
- **Used By:** Capital allocation
- **Impact:** Reallocates capital to winners

### 6. Hold Time Policy
- **File:** `feature_store/hold_time_policy.json`
- **Used By:** Exit timing
- **Impact:** Optimizes hold duration

### 7. Fee Gate Thresholds
- **File:** `feature_store/fee_gate_state.json`
- **Used By:** Fee gate
- **Impact:** Adjusts minimum expected edge

---

## Current Status

### What's Working:
- ✅ Learning systems are running (scheduler active)
- ✅ Continuous Learning Controller started (12-hour cycles)
- ✅ Unified Scheduler running (10-min + nightly)
- ✅ Multiple learning modules exist and are scheduled

### What's Not Working:
- ⚠️ Signal weights at defaults (0 outcomes < 50 required)
- ⚠️ 0 enriched decisions (data enrichment may not be running)
- ⚠️ Daily learning rules file missing
- ⚠️ Learning health shows data gaps

### Why:
- **Signal outcome tracking** may not be actively logging outcomes
- **Data enrichment** may not be running (0 enriched decisions)
- **Learning systems need outcome data** to optimize

---

## Verification Commands (On Droplet)

### Check if Learning Systems Are Running:
```bash
cd /root/trading-bot-current

# Check if scheduler is running
ps aux | grep scheduler

# Check learning cycle logs
grep -i "learning" logs/bot_out.log | tail -20
grep -i "CLC" logs/bot_out.log | tail -20

# Check when learning cycles last ran
grep "learning_cycle_complete" logs/learning_audit.jsonl | tail -5
```

### Check Learning State:
```bash
# Check learning state file
cat feature_store/learning_state.json | python3 -m json.tool

# Check signal weights
cat feature_store/signal_weights_gate.json | python3 -m json.tool

# Check learning audit log
tail -20 logs/learning_audit.jsonl
```

### Check Data Collection:
```bash
# Check signal outcomes
wc -l logs/signal_outcomes.jsonl
tail -5 logs/signal_outcomes.jsonl

# Check enriched decisions
wc -l logs/enriched_decisions.jsonl
tail -5 logs/enriched_decisions.jsonl

# Check learning health
cat feature_store/learning_health_status.json | python3 -m json.tool
```

---

## Summary

**YES, you have comprehensive learning systems** that:

1. ✅ **Analyze everything:**
   - Executed trades
   - Blocked signals
   - Missed opportunities
   - Signal outcomes
   - Counterfactual scenarios

2. ✅ **Provide updates:**
   - Signal weights
   - Gate thresholds
   - Sizing multipliers
   - Strategy/symbol allocation
   - Hold time policies
   - Fee gate thresholds

3. ✅ **Are scheduled to run:**
   - Continuous Learning Controller: Every 12 hours
   - Unified Scheduler: Every 10 minutes + nightly at 07:00 UTC

**However:**
- ⚠️ Learning systems need outcome data to optimize
- ⚠️ Signal weights at defaults (need 50+ outcomes)
- ⚠️ Data enrichment may not be running (0 enriched decisions)

**Action Needed:**
1. Verify learning cycles are actually running
2. Check if signal outcome tracking is active
3. Ensure data enrichment is running
4. Verify learning systems are receiving data

---

**The learning engine IS comprehensive and IS designed to review everything and provide updates. It just needs the data pipeline to be working correctly to feed it outcome data.**
