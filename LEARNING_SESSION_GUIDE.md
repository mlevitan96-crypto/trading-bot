# Learning Session Guide
**Strategy: Pause Trading → Catch Up Signals → Learn → Resume with Better Signals**

## Why This Works

1. **Signal Generation**: Signals are only generated during active trading cycles
2. **Signal Resolution**: Resolution continues independently, processing backlog
3. **Learning Engine**: Processes resolved signals to update weights/parameters
4. **Result**: Resume trading with improved signal weights and better decisions

## Step-by-Step Process

### 1. Pause Trading

```bash
cd /root/trading-bot-current
git pull origin main
python3 pause_trading_for_learning.py --pause
```

This creates `logs/trading_frozen.flag` which prevents new trades and new signal generation.

### 2. Monitor Signal Resolution Progress

```bash
# Check current status
python3 check_resolution_progress.py

# Run every 5-10 minutes to track progress
watch -n 300 python3 check_resolution_progress.py
```

**Expected Catch-Up Time:**
- Current backlog: ~32,700 signals
- Processing rate: 500 signals/cycle × 1 cycle/minute = 500 signals/minute
- **Time to catch up: ~65 minutes (~1.1 hours)** if no new signals are added

### 3. Wait for Resolution to Complete

The system will:
- ✅ Continue resolving pending signals (no new ones added)
- ✅ Write outcomes to `logs/signal_outcomes.jsonl`
- ✅ Process at 500 signals/minute

**Completion Indicators:**
- Pending signals drops to near zero
- Progress shows "~100% complete"
- Outcomes file stops growing rapidly

### 4. Trigger Learning Cycle

Once signals are resolved, trigger a comprehensive learning cycle:

```bash
# Option 1: Force learning cycle via ContinuousLearningController
python3 -c "
from src.continuous_learning_controller import ContinuousLearningController
clc = ContinuousLearningController()
result = clc.run_learning_cycle(force=True)
print('Learning cycle complete:', result)
"

# Option 2: Run signal weight update directly
python3 -c "
from src.signal_weight_learner import run_signal_weight_update
result = run_signal_weight_update(dry_run=False)
print('Signal weights updated:', result)
"
```

**What the Learning Engine Does:**
- ✅ Reads all resolved signal outcomes from `signal_outcomes.jsonl`
- ✅ Updates signal component weights based on performance
- ✅ Adjusts profit targets and sizing intelligence
- ✅ Updates timing intelligence
- ✅ Saves updated weights to `feature_store/signal_weights_gate.json`

### 5. Verify Learning Updates

```bash
# Check updated signal weights
cat feature_store/signal_weights_gate.json | python3 -m json.tool

# Check learning logs
tail -50 logs/learning_log.jsonl
```

### 6. Resume Trading

```bash
python3 pause_trading_for_learning.py --resume
```

The bot will resume trading with:
- ✅ Updated signal weights (better predictions)
- ✅ Improved profit targets
- ✅ Better sizing intelligence
- ✅ Optimized timing

## Expected Benefits

1. **Better Signal Accuracy**: Weights updated based on actual outcomes
2. **Improved Profitability**: Learning from what worked vs. what didn't
3. **Faster Adaptation**: System has processed all historical signals
4. **Clean Slate**: No backlog interfering with new signal evaluation

## Monitoring During Learning Session

```bash
# Check trading status
python3 pause_trading_for_learning.py --status

# Monitor signal resolution
python3 check_resolution_progress.py

# Check CPU usage (should stay high during resolution)
top -b -n 1 | head -20

# Check learning engine activity
tail -f logs/learning_log.jsonl
```

## Troubleshooting

**If resolution seems stuck:**
- Check CPU usage (should be ~100%)
- Verify bot is running: `sudo systemctl status tradingbot`
- Check for errors: `journalctl -u tradingbot --since "10 minutes ago"`

**If learning cycle fails:**
- Check data files exist: `ls -lh logs/signal_outcomes.jsonl`
- Verify outcomes file has data: `wc -l logs/signal_outcomes.jsonl`
- Check learning logs: `tail -100 logs/learning_log.jsonl`

## Time Estimates

- **Signal Resolution**: ~1.1 hours (32,700 signals ÷ 500/min)
- **Learning Cycle**: ~5-10 minutes (processing outcomes and updating weights)
- **Total Time**: ~1.5 hours for complete learning session

## Best Practices

1. **Run during low market activity** (fewer new signals if something slips through)
2. **Monitor progress** every 10-15 minutes
3. **Verify learning completed** before resuming
4. **Check signal weights changed** to confirm learning worked
5. **Resume during active market** to test improved signals
