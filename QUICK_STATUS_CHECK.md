# Quick Status Check Commands

## Correct Command (Use `python3`, not `python`)

```bash
cd /root/trading-bot-current
git pull origin main
python3 monitor_learning_status.py
```

---

## All Monitoring Commands

### Quick Status (Run Anytime)
```bash
python3 monitor_learning_status.py
```
Shows: Learning status, recent adjustments, performance metrics

### Full Verification (Run Daily)
```bash
python3 verify_learning_and_performance.py
```
Shows: Complete system check, all issues, recommendations

### See Learning Changes
```bash
# Signal weight changes
cat feature_store/signal_weights_gate.json | python3 -m json.tool

# Learning adjustments
cat feature_store/learning_state.json | python3 -m json.tool

# Learning cycle activity
tail -20 logs/learning_audit.jsonl | python3 -m json.tool
```

---

## Can You Stop Scripts?

### Main Bot (DO NOT STOP)
- `run.py` - Main trading bot
- `bot_cycle.py` - Trading cycle
- **Stopping these stops all trading and learning**

### Monitoring Scripts (SAFE TO STOP)
- `monitor_learning_status.py` - Read-only monitoring
- `verify_learning_and_performance.py` - Read-only verification
- `fix_learning_system.py` - Can stop (but let it finish first)

---

## What the Monitor Shows

1. **Learning Status** - Is learning running? Last cycle time?
2. **Recent Adjustments** - What changes were made?
3. **Signal Weight Changes** - Which signals got more/less weight?
4. **Performance Trends** - Win rate and P&L improving?
5. **Data Collection** - Signals, trades, enriched decisions

---

## Next Steps

1. **Run the monitor** - `python3 monitor_learning_status.py`
2. **Let bot run** - Don't stop the main bot
3. **Check daily** - Monitor progress over time
4. **Track trends** - Watch win rate and P&L improve
