# Sizing Multiplier Learners - Deployment Guide

## What Was Implemented

### Phase 1: Sizing Multiplier Learners ✅ COMPLETE

**5 New Learners Created:**
1. `IntelligenceGateSizingLearner` - Learns optimal multipliers for intel conflicts
2. `StreakSizingLearner` - Learns optimal multipliers for win/loss streaks
3. `RegimeSizingLearner` - Learns optimal multiplier for regime mismatches
4. `FeeGateSizingLearner` - Learns optimal multipliers for fee drag levels
5. `ROISizingLearner` - Learns optimal multipliers for ROI threshold violations

**Gate Updates:**
- All gates now **load learned multipliers** with fallback to defaults
- Gates use caching (5-minute TTL) for performance
- Multipliers are loaded from `feature_store/*.json` files

**Data Capture Enhanced:**
- `bot_cycle.py` captures gate states (intel_reason, streak_reason, regime_reason, fee_reason, roi_reason)
- `position_manager.py` stores `gate_attribution` in positions for learning
- `alpha_entry_wrapper` captures gate attribution from unified_pre_entry_gate

**Integration:**
- Learners run nightly via `scheduler_with_analysis.py`
- Analyzes last 7 days of trades
- Uses EWMA smoothing to prevent oscillation
- Saves learned multipliers to `feature_store/`

---

## Deployment Instructions

### Step 1: Pull Latest Changes

```bash
cd /root/trading-bot-current
git pull origin main
```

### Step 2: Verify Files

```bash
# Check new learner module exists
ls -la src/sizing_multiplier_learners.py

# Check gate files were updated
grep -n "LEARNED\|_load_learned" src/intelligence_gate.py | head -5
grep -n "LEARNED\|_load_learned" src/streak_filter.py | head -5
grep -n "LEARNED\|_load_learned" src/regime_filter.py | head -5
grep -n "LEARNED\|_load_learned" src/fee_aware_gate.py | head -5

# Check scheduler integration
grep -n "sizing_multiplier_learners\|SIZING-LEARNER" src/scheduler_with_analysis.py
```

### Step 3: Restart Bot

```bash
sudo systemctl restart tradingbot
```

### Step 4: Verify Startup

```bash
# Check logs for learner module import
journalctl -u tradingbot --since "2 minutes ago" | grep -E "SIZING-LEARNER|sizing_multiplier|Error|Traceback" | head -20

# Verify bot is running
sudo systemctl status tradingbot
```

### Step 5: Test Learning (Optional - Wait for Nightly Cycle)

The learners will run automatically during the nightly cycle (around 7:00 UTC).

To manually test:

```bash
cd /root/trading-bot-current
source venv/bin/activate  # If using venv
python3 -c "from src.sizing_multiplier_learners import run_all_sizing_learners; result = run_all_sizing_learners(); print(f'Learners run: {result[\"summary\"][\"successful_learners\"]}/5 successful, {result[\"summary\"][\"total_multipliers_updated\"]} multipliers updated')"
```

### Step 6: Verify Learned Multipliers

After learning runs (either nightly or manual), check:

```bash
# Check learned multiplier files
ls -la feature_store/*sizing*.json

# View learned multipliers
cat feature_store/intelligence_gate_sizing.json | python3 -m json.tool
cat feature_store/streak_sizing_weights.json | python3 -m json.tool
cat feature_store/regime_sizing_weights.json | python3 -m json.tool
cat feature_store/fee_gate_sizing_multipliers.json | python3 -m json.tool
cat feature_store/roi_threshold_sizing.json | python3 -m json.tool
```

---

## How It Works

### Learning Cycle

1. **Nightly (7:00 UTC):** `scheduler_with_analysis.py` calls `run_all_sizing_learners()`
2. **Data Loading:** Learners load last 7 days of closed trades from `positions_futures.json`
3. **State Extraction:** Extract gate states (intel_reason, streak_reason, etc.) from trade metadata
4. **Performance Analysis:** Group trades by gate state, calculate avg P&L, ROI, win rate
5. **Multiplier Optimization:** Calculate optimal multipliers based on performance
6. **EWMA Smoothing:** Apply exponential weighted moving average to prevent oscillation
7. **Save:** Write learned multipliers to `feature_store/*.json`

### Gate Usage

1. **Gate Called:** When a gate is evaluated (e.g., `intelligence_gate()`)
2. **Load Multipliers:** Gate loads learned multipliers (cached for 5 minutes)
3. **Apply Multiplier:** Uses learned value, falls back to default if learning hasn't run
4. **Log State:** Gate decision logged with state information for future learning

### Data Flow

```
Trade Opens → signal_context captures gate states → position stored in positions_futures.json
                                                         ↓
Trade Closes → P&L recorded → Learner analyzes last 7 days
                                                         ↓
Learner calculates optimal multipliers → Saved to feature_store/*.json
                                                         ↓
Gates load learned multipliers → Applied to new trades
```

---

## Expected Behavior

### First Run (No Learned Data Yet)

- Gates use **default multipliers** (hard-coded fallbacks)
- Learners run but won't have enough data initially (need 5+ trades per category)
- Multiplier files created with default values

### After Learning Runs (5+ trades per category)

- Gates use **learned multipliers** from `feature_store/*.json`
- Multipliers adjust based on historical performance
- Better performing gate states get higher multipliers
- Poor performing gate states get lower multipliers

### Log Messages

You should see:
- `[SIZING-LEARNER] Starting intelligence gate sizing multiplier learning...`
- `Updated X intel gate multipliers`
- `[LEARNED]` tags in gate log messages when using learned multipliers

---

## Troubleshooting

### Learners Not Running

Check scheduler logs:
```bash
journalctl -u tradingbot --since "1 hour ago" | grep -i "sizing.*learner\|nightly"
```

### No Multipliers Updated

Check if enough data exists:
```bash
# Count recent closed trades
python3 -c "
from src.data_registry import DataRegistry as DR
import json
data = DR.read_json(DR.POSITIONS_FUTURES)
closed = data.get('closed_positions', [])
print(f'Closed trades: {len(closed)}')
print(f'Recent (last 7 days): {len([t for t in closed if t.get(\"closed_at\")])}')
"
```

### Gates Not Using Learned Multipliers

Check if multiplier files exist:
```bash
ls -la feature_store/*sizing*.json
```

If files don't exist, learners need to run first (either manually or wait for nightly cycle).

---

## Monitoring

### Check Learning Status

```bash
# View last learning run results
tail -100 logs/*.log | grep -i "sizing.*learner\|multipliers updated"

# Check multiplier files last modified
ls -lth feature_store/*sizing*.json | head -5
```

### Verify Gates Using Learned Values

Look for `[LEARNED]` tags in gate logs:
```bash
journalctl -u tradingbot --since "10 minutes ago" | grep -i "\[LEARNED\]"
```

---

## Summary

✅ **5 sizing multiplier learners implemented**
✅ **All gates updated to use learned multipliers**
✅ **Data capture enhanced for learning**
✅ **Integrated into nightly learning cycle**
✅ **Ready to deploy**

The system will start with default multipliers and gradually learn optimal values as trade data accumulates.
