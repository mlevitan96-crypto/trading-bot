# Fix Learning System - Commands

**Problem:** Learning system files don't exist, so it's not learning and not improving profitability.

**Solution:** Run these commands on the droplet to diagnose and fix.

---

## Commands to Run on Droplet

```bash
# 1. Connect to droplet
ssh root@159.65.168.230

# 2. Navigate to correct directory
cd /root/trading-bot-current

# 3. Pull latest code
git pull origin main

# 4. Run diagnostic to see what's broken
python3 diagnose_learning_system.py

# 5. Fix the learning system
python3 fix_learning_system.py
```

---

## What the Fix Script Does

1. **Data Enrichment**: Links signals to trades (creates enriched_decisions.jsonl)
2. **Signal Outcome Tracking**: Resolves pending signal outcomes
3. **Learning Cycle**: Analyzes all trades and signals
4. **Generate Adjustments**: Creates adjustments to improve profitability:
   - Increase signal weights for profitable signals
   - Decrease signal weights for unprofitable signals
   - Tighten gates for low win rate patterns
   - Loosen gates for high win rate patterns
   - Adjust sizing based on win rates
5. **Apply Adjustments**: Updates system files to improve profitability

---

## Goal: Improve Profitability

The learning system is designed to:
- **Increase win rates** by focusing on patterns with >50% WR
- **Decrease losses** by avoiding patterns with <40% WR
- **Optimize signal weights** (more weight on predictive signals)
- **Optimize timing** (focus on best hours, avoid worst hours)
- **Optimize sizing** (size up winners, size down losers)

---

## After Running Fix

The learning system will:
- Run automatically every 12 hours
- Analyze all trades and signals
- Generate adjustments to improve profitability
- Apply adjustments to increase win rates and decrease losses

---

## Verify It's Working

After running the fix, check:

```bash
# Check learning state
cat feature_store/learning_state.json | python3 -m json.tool

# Check learning audit log
tail -20 logs/learning_audit.jsonl

# Check signal outcomes
wc -l logs/signal_outcomes.jsonl

# Check enriched decisions
wc -l logs/enriched_decisions.jsonl
```

---

**The learning system IS comprehensive and CAN improve profitability by increasing win rates and decreasing losses. It just needs to be fixed and running.**
