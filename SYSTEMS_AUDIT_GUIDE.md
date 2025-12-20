# Comprehensive Systems Audit Guide

## Overview

The `comprehensive_systems_audit.py` script performs a **complete systems audit** to find:

1. **Bugs and File Mismatches** - Missing files, path issues, import errors
2. **Missing Integrations** - Systems that should call each other but don't
3. **Missing Logging/Analysis** - Data that should be collected but isn't
4. **Hardcoded Values** - Thresholds that should be learned but are fixed
5. **Profitability Gaps** - Areas not optimizing for profitability

---

## What It Checks

### 1. File Path Mismatches

- Checks if all expected learning files exist:
  - `feature_store/learning_state.json`
  - `feature_store/signal_weights.json`
  - `logs/learning_audit.jsonl`
  - `logs/signal_outcomes.jsonl`
  - `logs/enriched_decisions.jsonl`
  - `logs/positions_futures.json`
  - `logs/signals.jsonl`

- Verifies DataRegistry paths match actual files

### 2. Missing Integrations

- **Signal Tracking**: Verifies `signal_tracker.log_signal()` is called in:
  - `conviction_gate.py`
  - `unified_stack.py`
  - `bot_cycle.py`

- **Post-Trade Learning**: Checks if post-trade updates are called:
  - `unified_on_trade_close()`
  - Learning system updates
  - Profit attribution

- **Learning Schedule**: Verifies learning controller is scheduled in `run.py`

### 3. Missing Logging/Analysis

- **Signal Outcomes**: Checks if `signal_outcomes.jsonl` exists and has data
- **Enriched Decisions**: Checks if `enriched_decisions.jsonl` exists and has data
- **Learning Audit**: Checks if `learning_audit.jsonl` exists and has data

### 4. Hardcoded Values

- **Win Rate Thresholds**: Finds hardcoded win rate checks (0.40, 0.50, 0.60, etc.)
- **Signal Weights**: Finds hardcoded signal weights that should be learned
- **Thresholds**: Finds hardcoded threshold values in gate logic

### 5. Profitability Gaps

- **Sizing**: Checks if position sizing uses profitability (win rate, P&L, expectancy)
- **Exits**: Checks if exit decisions use profitability (optimal hold time, profit targets)
- **Learning**: Checks if learning systems optimize for profitability

---

## How to Run

### On Local Machine

```bash
cd /path/to/trading-bot
python3 comprehensive_systems_audit.py
```

### On Droplet

```bash
cd /root/trading-bot-current
git pull origin main
python3 comprehensive_systems_audit.py
```

---

## Output

The script outputs:

1. **Real-time Progress**: Shows what's being checked and results
2. **Issue Summary**: Counts of issues by category
3. **Detailed Report**: JSON file saved to `reports/systems_audit_report.json`
4. **Critical Issues**: Highlights issues that must be fixed

### Report Format

```json
{
  "timestamp": "2025-12-20T...",
  "total_issues": 15,
  "issues": {
    "file_mismatches": [...],
    "missing_integrations": [...],
    "missing_logging": [...],
    "hardcoded_values": [...],
    "profitability_gaps": [...],
    "bugs": [...]
  },
  "summary": {
    "file_mismatches": 3,
    "missing_integrations": 5,
    "missing_logging": 4,
    "hardcoded_values": 2,
    "profitability_gaps": 1,
    "bugs": 0
  }
}
```

---

## Issue Severity Levels

- **CRITICAL**: Must be fixed immediately (e.g., learning not running, missing signal tracking)
- **HIGH**: Should be fixed soon (e.g., missing data files, profitability gaps)
- **MEDIUM**: Should be addressed (e.g., hardcoded thresholds, minor integrations)

---

## Common Issues Found

### 1. Missing Signal Tracking

**Problem**: Signals not being logged for outcome tracking

**Fix**: Ensure `signal_tracker.log_signal()` is called in:
- `conviction_gate.py` (line 423) ✅
- `unified_stack.py` (line 213) ✅
- Anywhere signals are generated

### 2. Empty Signal Outcomes

**Problem**: `signal_outcomes.jsonl` exists but is empty

**Fix**: 
- Ensure `signal_tracker.log_signal()` is being called
- Ensure `signal_tracker.resolve_pending_signals()` is running
- Check if signal resolver worker is running

### 3. Hardcoded Win Rate Thresholds

**Problem**: Win rate thresholds (0.40, 0.50, 0.60) are hardcoded instead of learned

**Fix**: 
- Move thresholds to config files
- Use learning systems to adjust thresholds
- Load from `feature_store/learned_rules.json`

### 4. Missing Post-Trade Learning

**Problem**: Trades close but learning systems aren't updated

**Fix**: Ensure `unified_on_trade_close()` is called after every trade closure

### 5. Sizing Not Profitability-Aware

**Problem**: Position sizing doesn't use win rate or profitability

**Fix**: 
- Use historical win rate in sizing calculations
- Apply profitability multipliers
- Load from learned rules

---

## Next Steps After Audit

1. **Review Report**: Read `reports/systems_audit_report.json`
2. **Prioritize Fixes**: Start with CRITICAL issues
3. **Fix Issues**: Address each issue systematically
4. **Re-run Audit**: Verify fixes worked
5. **Monitor**: Ensure issues don't return

---

## Integration with Fix Scripts

After running the audit, use:

- `fix_learning_system.py` - Fixes learning system issues
- `diagnose_learning_system.py` - Diagnoses specific problems

---

**The audit is designed to find everything that's broken, missing, or not optimized for profitability. Run it regularly to ensure the system is working correctly.**
