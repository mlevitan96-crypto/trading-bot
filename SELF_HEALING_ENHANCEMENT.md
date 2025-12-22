# Self-Healing Enhancement
**Comprehensive Architecture-Aware Self-Healing System**

---

## Overview

We've created a comprehensive self-healing system that uses the `ARCHITECTURE_MAP.md` to understand the entire system structure and automatically diagnose and fix issues.

---

## What Was Created

### 1. Architecture-Aware Healing (`src/architecture_aware_healing.py`)

A new healing system that:
- **Understands the architecture** - Uses knowledge from `ARCHITECTURE_MAP.md`
- **Monitors all components** - Workers, files, configs, dependencies
- **Diagnoses issues** - Knows what should be running and what files should exist
- **Automatically fixes** - Restarts workers, creates missing files, fixes configs
- **Reports comprehensively** - Shows what was fixed, what failed, what needs attention

### 2. Integration with Existing Healing

The architecture-aware healing is integrated into the existing `HealingOperator`:
- Runs first in each healing cycle
- Complements existing component-specific healing
- Uses architecture knowledge to fix issues the existing healing might miss

### 3. Manual Healing Script (`run_architecture_healing.py`)

A script to run architecture-aware healing manually:
```bash
python3 run_architecture_healing.py
```

---

## What It Heals

### 1. Worker Processes

**Checks:**
- Is the worker process running?
- Is the output file being updated?
- Are dependencies available?

**Fixes:**
- Restarts dead workers
- Verifies dependencies before restarting
- Reports on worker health

**Workers Monitored:**
- `predictive_engine` - Generates predictive signals
- `ensemble_predictor` - Creates ensemble predictions (CRITICAL - this was failing)
- `signal_resolver` - Resolves signal outcomes
- `feature_builder` - Builds features

### 2. File Staleness

**Checks:**
- Do critical files exist?
- Are files being updated within expected timeframes?

**Fixes:**
- Creates missing critical files
- Reports on stale files
- Identifies which producer should be updating each file

**Files Monitored:**
- `logs/predictive_signals.jsonl` - Should update every 5 min
- `logs/ensemble_predictions.jsonl` - Should update every 5 min (CRITICAL)
- `feature_store/pending_signals.json` - Should update every 5 min
- `logs/positions_futures.json` - Should update every 60 min
- `feature_store/signal_weights_gate.json` - Should update every 24 hours
- `configs/signal_policies.json` - Should exist and have required fields

### 3. Configuration Issues

**Checks:**
- Do required config fields exist?
- Are config values within expected ranges?

**Fixes:**
- Creates missing config files with defaults
- Updates configs with required fields
- Backs up configs before modifying

**Configs Monitored:**
- `configs/signal_policies.json` - Must have `long_ofi_requirement` and `short_ofi_requirement`

### 4. Dependencies

**Checks:**
- Are upstream dependencies available?
- Are dependencies stale?

**Fixes:**
- Reports on missing dependencies
- Identifies dependency chains
- Prevents restarting workers if dependencies aren't ready

**Dependencies Tracked:**
- `ensemble_predictor` depends on `predictive_signals.jsonl`
- `signal_resolver` depends on `ensemble_predictions.jsonl`
- `conviction_gate` depends on `signal_weights_gate.json` and `signal_policies.json`

---

## How It Works

### Architecture Knowledge

The healing system has built-in knowledge of:
1. **Worker Processes** - What workers exist, what they produce, what they depend on
2. **File System** - What files should exist, who produces them, how often they should update
3. **Dependencies** - What depends on what, dependency chains
4. **Configuration** - Required fields, default values, validation rules

### Healing Cycle

```
1. Check Worker Processes
   ├── Is process running?
   ├── Is output file updating?
   └── Are dependencies available?
   └── Fix: Restart if needed

2. Check File Staleness
   ├── Does file exist?
   ├── Is file being updated?
   └── Fix: Create missing files

3. Check Configuration
   ├── Do required fields exist?
   ├── Are values valid?
   └── Fix: Update configs

4. Check Dependencies
   ├── Are dependencies available?
   ├── Are dependencies stale?
   └── Report: Warn if issues
```

### Integration

The architecture-aware healing runs as part of the existing `HealingOperator`:
- Runs every 60 seconds (same as existing healing)
- Runs first in the healing cycle
- Complements existing component-specific healing
- Uses architecture knowledge to catch issues existing healing might miss

---

## Usage

### Automatic (Already Running)

The architecture-aware healing is integrated into the existing healing operator and runs automatically every 60 seconds.

### Manual (For Immediate Fixes)

Run manually to fix current issues:
```bash
cd /root/trading-bot-current
git pull origin main
python3 run_architecture_healing.py
```

This will:
1. Check all workers
2. Check all files
3. Check all configs
4. Check all dependencies
5. Fix what it can
6. Report what needs manual intervention

---

## Current Issue: Ensemble Predictor

### Problem
The ensemble predictor worker is not running, so `ensemble_predictions.jsonl` is not being updated.

### What Architecture-Aware Healing Will Do

1. **Detect Issue:**
   - Check if `ensemble_predictor` process is running → NO
   - Check if `ensemble_predictions.jsonl` is updating → NO (41+ hours old)

2. **Check Dependencies:**
   - Check if `predictive_signals.jsonl` exists → YES
   - Check if `predictive_signals.jsonl` is updating → YES

3. **Fix:**
   - Restart the ensemble predictor worker
   - Verify it starts successfully
   - Monitor that `ensemble_predictions.jsonl` starts updating

4. **Report:**
   - Success: "Restarted ensemble_predictor worker"
   - Or failure: "Failed to restart ensemble_predictor worker" (needs manual intervention)

---

## Benefits

### 1. Comprehensive Coverage

- Monitors entire pipeline, not just individual components
- Understands relationships between components
- Knows what should be running and what files should exist

### 2. Automatic Fixes

- Restarts dead workers automatically
- Creates missing files
- Fixes configuration issues
- No manual intervention needed for most issues

### 3. Architecture Knowledge

- Uses `ARCHITECTURE_MAP.md` knowledge to understand system
- Knows dependencies and relationships
- Prevents fixing things in wrong order

### 4. Better Reporting

- Shows what was fixed
- Shows what failed (needs manual intervention)
- Shows warnings (non-critical issues)
- Provides actionable information

---

## Next Steps

1. **Run Immediate Fix:**
   ```bash
   python3 run_architecture_healing.py
   ```

2. **Verify Fix:**
   ```bash
   python3 verify_full_pipeline.py
   ```

3. **Monitor:**
   - Architecture-aware healing runs automatically every 60 seconds
   - Check `feature_store/healing_results.json` for healing history
   - Monitor logs for healing activity

---

## Future Enhancements

1. **Parse ARCHITECTURE_MAP.md** - Automatically load architecture knowledge from markdown
2. **More Sophisticated Fixes** - Fix more complex issues automatically
3. **Predictive Healing** - Fix issues before they become problems
4. **Learning from Fixes** - Remember what fixes work and apply them proactively

---

**Last Updated:** December 22, 2025  
**Status:** ✅ Active and Integrated
