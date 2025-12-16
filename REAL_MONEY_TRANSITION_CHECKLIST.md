# Real Money Transition Checklist

## Mission: Get to Real Money Safely

This checklist ensures a safe transition from paper trading to live trading.

---

## ✅ PRE-TRANSITION REQUIREMENTS

### 1. Profitability Validation (30+ Days)
- [ ] **Paper trading profitable for 30+ consecutive days**
- [ ] **Positive Sharpe ratio** (> 1.0)
- [ ] **Win rate > 50%**
- [ ] **Consistent daily profitability** (no major drawdowns)
- [ ] **All profit filters working correctly**
- [ ] **Exit timing optimized** (taking profits at right times)

**How to Check:**
```bash
# Run profitability audit
python3 scripts/profitability_audit.py

# Check dashboard for 30-day performance
# Dashboard → Executive Summary → Weekly Summary
```

### 2. System Health Validation
- [ ] **All components green** (Signal Engine, Decision Engine, Safety Layer)
- [ ] **Self-healing working** (no manual interventions needed)
- [ ] **No critical alerts** in last 7 days
- [ ] **Learning systems active** (signal weights updating)
- [ ] **Rate limiting working** (no 429 errors)

**How to Check:**
```bash
# Check system health
journalctl -u tradingbot --since "7 days ago" | grep -E "CRITICAL|ERROR|HEALING"

# Verify learning is active
python3 scripts/profitability_audit.py
```

### 3. Safety Mechanisms Validation
- [ ] **Risk guards active** (all guards working)
- [ ] **Position limits enforced** (max positions, max exposure)
- [ ] **Stop losses working** (tested in paper mode)
- [ ] **Kill switch functional** (can freeze trading if needed)
- [ ] **Capital management verified** (proper allocation)

**How to Check:**
```bash
# Review risk guard logs
grep -r "RISK_GUARD\|risk.*guard" logs/ | tail -20

# Check position limits
python3 -c "from src.unified_self_governance_bot import _read_policy; print(_read_policy())"
```

### 4. Signal Quality Validation
- [ ] **Signal profitability verified** (positive EV on all signals)
- [ ] **Best signals prioritized** (weight learning working)
- [ ] **Redundant signals removed**
- [ ] **Signal freshness maintained** (no stale signals)

**How to Check:**
```bash
# Run signal quality audit
python3 scripts/profitability_audit.py

# Check signal outcomes
python3 -c "from src.signal_outcome_tracker import SignalOutcomeTracker; print(SignalOutcomeTracker().get_signal_stats())"
```

### 5. Learning Systems Validation
- [ ] **Signal weight learning active** (weights file exists and updating)
- [ ] **Profit learning enabled** (profit_blofin_learning active)
- [ ] **Strategy performance tracking** (winners promoted, losers suppressed)
- [ ] **Exit learning working** (optimal exit timing)

**How to Check:**
```bash
# Check learning systems
python3 scripts/profitability_audit.py

# Verify weights file exists
ls -la feature_store/signal_weights*.json

# Check profit learning
python3 -c "from src.profit_blofin_learning import is_profit_learning_enabled; print(is_profit_learning_enabled())"
```

---

## 🔄 TRANSITION STEPS

### Step 1: Final Paper Trading Validation (Day Before)
- [ ] Run complete system audit
- [ ] Verify all safety mechanisms
- [ ] Check dashboard for any red indicators
- [ ] Review last 7 days of trades
- [ ] Verify profitability is consistent

### Step 2: Configuration Update
- [ ] **Update `.env` file:**
  ```bash
  TRADING_MODE=real  # Change from 'paper' to 'real'
  ```
- [ ] **Verify API keys are correct:**
  ```bash
  BLOFIN_API_KEY=your_real_key
  BLOFIN_API_SECRET=your_real_secret
  BLOFIN_PASSPHRASE=your_real_passphrase
  ```
- [ ] **Set initial capital:**
  ```bash
  STARTING_CAPITAL=10000  # Or your desired amount
  ```

### Step 3: Safety Limits Review
- [ ] **Review position limits:**
  - Max positions per symbol
  - Max total exposure
  - Max leverage per trade
- [ ] **Review profit targets:**
  - Minimum profit per trade
  - Fee thresholds
- [ ] **Review risk limits:**
  - Max drawdown threshold
  - Stop loss percentages
  - Kill switch triggers

### Step 4: Start Real Trading
- [ ] **Restart bot with real mode:**
  ```bash
  sudo systemctl restart tradingbot
  ```
- [ ] **Monitor first few trades closely:**
  ```bash
  journalctl -u tradingbot -f
  ```
- [ ] **Check dashboard for real-time updates:**
  - Open positions
  - P&L updates
  - System health

### Step 5: Initial Monitoring (First 24 Hours)
- [ ] **Monitor every 2-4 hours** (first day only)
- [ ] **Check for any errors or issues**
- [ ] **Verify trades are executing correctly**
- [ ] **Confirm P&L calculations are accurate**
- [ ] **Ensure all safety mechanisms are working**

---

## 🚨 EMERGENCY PROCEDURES

### If Something Goes Wrong:

1. **Immediate Stop:**
   ```bash
   # Freeze trading (kill switch)
   # Or restart in paper mode
   sudo systemctl restart tradingbot
   # Edit .env: TRADING_MODE=paper
   ```

2. **Check Logs:**
   ```bash
   journalctl -u tradingbot --since "1 hour ago" | grep -E "ERROR|CRITICAL|Exception"
   ```

3. **Review Dashboard:**
   - Check system health
   - Review recent trades
   - Check P&L

4. **If Needed:**
   - Switch back to paper mode
   - Review what went wrong
   - Fix issues
   - Re-test in paper mode before trying real again

---

## 📊 POST-TRANSITION MONITORING

### Daily Checks (First Week):
- [ ] Check dashboard once per day
- [ ] Review Executive Summary
- [ ] Verify profitability
- [ ] Check for any alerts (should be none)

### Weekly Checks (First Month):
- [ ] Review weekly performance
- [ ] Check learning systems are improving
- [ ] Verify signal quality is improving
- [ ] Review any issues that occurred

### Ongoing (After First Month):
- [ ] Check Executive Summary weekly
- [ ] Review monthly performance
- [ ] Verify continuous learning
- [ ] Monitor for any degradation

---

## ✅ SUCCESS CRITERIA

### Before Transition:
- ✅ 30+ days profitable in paper mode
- ✅ All systems green and healthy
- ✅ Learning systems active
- ✅ Signal quality verified
- ✅ Safety mechanisms validated

### After Transition:
- ✅ Real trades executing correctly
- ✅ P&L calculations accurate
- ✅ Safety mechanisms working
- ✅ No critical errors
- ✅ Profitability maintained

---

## 📝 NOTES

- **Start Small**: Consider starting with lower position sizes initially
- **Monitor Closely**: First week requires more attention
- **Trust the System**: After validation, let it run autonomously
- **Review Regularly**: Check Executive Summary weekly
- **Learn from Issues**: Any problems should trigger fixes and re-testing

---

## 🎯 MISSION ALIGNMENT

This checklist ensures:
1. **Make Money** - Only transition when profitable
2. **Get to Real Money** - Safe, validated transition
3. **Set It and Forget It** - After validation, autonomous operation
4. **Autonomous Operation** - Self-healing continues in real mode
5. **Continuous Learning** - Learning systems continue improving
6. **Best Signals** - Only profitable signals are traded

---

**Status**: Ready for use when paper trading is profitable for 30+ days

