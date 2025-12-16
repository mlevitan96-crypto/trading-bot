# Learning Systems Behavior & Outcomes

## Overview

This document explains what the learning systems can and cannot do, ensuring they make **granular adjustments** rather than blocking entire cryptos or timeframes.

---

## ✅ GRANULAR LEARNING SYSTEMS (Primary)

### 1. Signal Weight Learning (`signal_weight_learner.py`)

**What It Does:**
- Adjusts the **importance/weight** of individual signals (liquidation, funding, whale_flow, OFI, etc.)
- Makes small, incremental changes: **±20% max per update**
- Minimum weight floor: **0.05** (signals never fully disappear)

**Possible Outcomes:**
- ✅ Increase weight of profitable signals (e.g., `whale_flow: 0.20 → 0.24`)
- ✅ Decrease weight of unprofitable signals (e.g., `oi_velocity: 0.05 → 0.04`)
- ✅ Adjust optimal horizon for each signal (1m, 5m, 15m, 30m, 1h)
- ❌ **Does NOT block entire symbols**
- ❌ **Does NOT block entire timeframes**
- ❌ **Does NOT disable signals completely** (minimum 0.05 weight)

**Example Adjustments:**
```json
{
  "liquidation": 0.22 → 0.26 (profitable, +18%),
  "funding": 0.16 → 0.13 (unprofitable, -19%),
  "whale_flow": 0.20 → 0.22 (slightly profitable, +10%)
}
```

**Impact:** Signals that work get more influence in decision-making, but all signals still contribute.

---

### 2. Profit Filter Learning (`profit_blofin_learning.py`)

**What It Does:**
- Adjusts **MIN_PROFIT_USD threshold** per symbol
- Adjusts **leverage** and **collateral** per symbol
- Makes incremental changes within bounds

**Possible Outcomes:**
- ✅ Tighten profit filter for unprofitable symbols (e.g., `MIN_PROFIT_USD: $10 → $12`)
- ✅ Ease profit filter for profitable symbols (e.g., `MIN_PROFIT_USD: $10 → $9.50`)
- ✅ Adjust leverage (e.g., `INTERNAL_MAX_LEVERAGE: 10 → 9` if losing)
- ✅ Adjust collateral (e.g., `BASE_COLLATERAL_USD: $500 → $525` if winning)
- ❌ **Does NOT block entire symbols** (only adjusts thresholds)
- ❌ **Does NOT block entire timeframes**

**Example Adjustments:**
```json
{
  "BTCUSDT": {
    "MIN_PROFIT_USD": 10.0 → 11.0 (tightened - symbol losing),
    "INTERNAL_MAX_LEVERAGE": 10 → 9 (reduced risk)
  },
  "ETHUSDT": {
    "MIN_PROFIT_USD": 10.0 → 9.5 (eased - symbol winning),
    "BASE_COLLATERAL_USD": 500 → 525 (increased allocation)
  }
}
```

**Impact:** Unprofitable patterns require higher profit to trade, profitable patterns get easier entry.

---

### 3. Weighted Signal Fusion Learning (`weighted_signal_fusion.py`)

**What It Does:**
- Adjusts weights of signal **components** (OFI, ensemble, MTF, regime, etc.)
- Makes small adjustments: **±5% per trade outcome**
- Minimum weight: **0.02**, Maximum: **0.40**

**Possible Outcomes:**
- ✅ Boost weights of components that contributed to profitable trades
- ✅ Reduce weights of components that contributed to losing trades
- ✅ Adjust entry vs exit signal weights independently
- ❌ **Does NOT block entire symbols**
- ❌ **Does NOT block entire timeframes**

**Example Adjustments:**
```json
{
  "entry_weights": {
    "ofi": 0.25 → 0.26 (contributed to win),
    "ensemble": 0.20 → 0.19 (contributed to loss),
    "mtf_alignment": 0.15 → 0.16 (contributed to win)
  }
}
```

**Impact:** Components that work get more influence, but all components still contribute.

---

### 4. Hold Time Learning (`profitability_acceleration_learner.py`, `hold_time_governor.py`, `hold_time_enforcer.py`)

**What It Does:**
- Adjusts **minimum hold time** per symbol and per symbol+direction
- Learns optimal hold durations from historical P&L data
- Buckets trades by duration (<5min, 5-15min, 15-60min, 1h+) and finds most profitable bucket
- Makes incremental adjustments with guardrails (90th percentile cap)

**Possible Outcomes:**
- ✅ Increase minimum hold time if early exits are losing money (e.g., `30min → 45min`)
- ✅ Decrease minimum hold time if longer holds are unprofitable (e.g., `45min → 35min`)
- ✅ Adjust per symbol (e.g., `BTCUSDT: 30min`, `ETHUSDT: 45min`)
- ✅ Adjust per direction (e.g., `BTCUSDT|SHORT: 30min`, `BTCUSDT|LONG: 45min`)
- ✅ Adjust based on quick vs medium trade performance
- ❌ **Does NOT block entire symbols**
- ❌ **Does NOT block entire timeframes**

**Example Adjustments:**
```json
{
  "BTCUSDT": {
    "min_hold_seconds": 1800 → 2700 (30min → 45min),
    "reason": "Early exits (<30min) losing money, 15-60min bucket most profitable"
  },
  "ETHUSDT|SHORT": {
    "min_hold_minutes": 30 → 20,
    "reason": "Quick exits profitable for SHORT, medium holds losing"
  }
}
```

**Impact:** Prevents premature exits that lose money, but allows exits after minimum hold time.

**Key Insight:** Early exits (0-2min) historically lost -$294.58, so learning increases minimum hold to prevent this.

---

### 5. Exit Timing Learning (`exit_timing_intelligence.py`, `exit_learning_and_enforcement.py`)

**What It Does:**
- Adjusts **take-profit levels** (TP1, TP2) per symbol and pattern
- Adjusts **trailing stop distance** based on volatility
- Adjusts **stop-loss levels** based on MAE (Max Adverse Excursion)
- Adjusts **minimum hold time** if frequent time-stops occur
- Uses MFE (Max Favorable Excursion) analysis to learn optimal exit points

**Possible Outcomes:**
- ✅ Adjust TP1/TP2 ROI targets (e.g., `TP1: 0.5% → 0.6%` if too many time-stops)
- ✅ Adjust trailing stop distance (e.g., `TRAIL_ATR_MULT: 1.5 → 1.8` in high volatility)
- ✅ Adjust stop-loss (e.g., `STOP_LOSS_ROI: -0.5% → -0.6%` if premature stops)
- ✅ Adjust minimum hold time (e.g., `MIN_HOLD_MINUTES: 30 → 40` if frequent time-stops)
- ❌ **Does NOT block entire symbols**
- ❌ **Does NOT block entire timeframes**

**Example Adjustments:**
```json
{
  "BTCUSDT": {
    "TP1_ROI": 0.005 → 0.006 (0.5% → 0.6%),
    "TP2_ROI": 0.010 → 0.009 (1.0% → 0.9%),
    "MIN_HOLD_MINUTES": 30 → 40,
    "TRAIL_ATR_MULT": 1.5 → 1.8,
    "reason": "High volatility, frequent time-stops before TP1"
  }
}
```

**Impact:** Optimizes exit points to capture more profit while protecting against losses.

---

## ⚠️ TEMPORARY SUPPRESSION (Secondary - With Safeguards)

### 6. Symbol Suppression (`unified_self_governance_bot.py`)

**What It Does:**
- **Temporarily suppresses** symbols that are persistently unprofitable
- **Duration:** 12 hours (not permanent)
- **Decay/Reactivation:** Automatically reactivates after duration

**Conditions for Suppression:**
- `avg_profit_usd < 0` AND
- `win_rate < 45%` AND
- `trades >= 25` (needs sufficient data)

**Possible Outcomes:**
- ⚠️ **Temporarily blocks symbol for 12 hours** (if persistently losing)
- ✅ **Automatically reactivates** after 12 hours
- ✅ **Also tightens profit filter** (granular adjustment) instead of just blocking
- ❌ **Does NOT block permanently**
- ❌ **Does NOT block entire timeframes**

**Example:**
```
BTCUSDT: avg_profit=-$2, win_rate=40%, trades=30
→ Suppressed for 12 hours
→ MIN_PROFIT_USD tightened: $10 → $11
→ After 12 hours: Reactivated, can trade again
```

**Impact:** Gives losing symbols a "cooldown" period, but they can come back.

---

## ❌ WHAT LEARNING SYSTEMS **DO NOT** DO

### They Do NOT:
1. ❌ **Block entire cryptos permanently** (only temporary 12h suppression)
2. ❌ **Block entire timeframes** (no timeframe blocking exists)
3. ❌ **Disable signals completely** (minimum weights ensure all signals contribute)
4. ❌ **Block entire strategies** (strategies can be disabled by regime, but not by learning)
5. ❌ **Make large, sudden changes** (all changes are incremental and bounded)

---

## 📊 SUMMARY OF POSSIBLE ADJUSTMENTS

| System | What It Adjusts | Granularity | Can Block? |
|--------|----------------|-------------|------------|
| **Signal Weight Learning** | Signal importance (0.05-1.0) | ±20% per update | ❌ No |
| **Profit Filter Learning** | MIN_PROFIT_USD per symbol | Incremental | ❌ No (only tightens) |
| **Signal Fusion Learning** | Component weights (0.02-0.40) | ±5% per trade | ❌ No |
| **Hold Time Learning** | MIN_HOLD_MINUTES per symbol/direction | Incremental (30-120min range) | ❌ No (only adjusts minimum) |
| **Exit Timing Learning** | TP1/TP2, trailing stops, stop-loss | Incremental | ❌ No (only adjusts targets) |
| **Symbol Suppression** | Temporary symbol block | 12 hours | ⚠️ Temporary only |

---

## 🎯 HOW TO VERIFY LEARNING IS GRANULAR

### Check Signal Weights:
```bash
cat feature_store/signal_weights_gate.json
# Should show weights between 0.05-1.0, not 0 or 1
```

### Check Profit Filters:
```bash
cat config/profit_policy.json
# Should show MIN_PROFIT_USD adjustments per symbol, not "disabled": true
```

### Check Symbol Suppression:
```bash
grep "symbol_suppressed" logs/unified_events.jsonl | tail -5
# Should show temporary suppressions with duration_hours=12
```

### Check Hold Time Adjustments:
```bash
cat feature_store/hold_time_policy.json
# Should show min_hold_seconds per symbol, typically 300-3600 (5min-1h)
```

### Check Exit Timing Adjustments:
```bash
cat feature_store/exit_timing_rules.json
# Should show TP1/TP2, MIN_HOLD_MINUTES, trailing stop adjustments per symbol
```

---

## 🔍 MONITORING LEARNING BEHAVIOR

### What to Watch For:
1. ✅ **Signal weights gradually adjusting** (not jumping to 0 or 1)
2. ✅ **Profit thresholds tightening/easing** (not blocking completely)
3. ✅ **Symbol suppressions are temporary** (12h max, then reactivate)
4. ❌ **No permanent symbol blocks** (if you see this, it's a bug)
5. ❌ **No timeframe blocks** (if you see this, it's a bug)

### Red Flags:
- 🚨 Signal weight = 0.0 (should never happen - minimum is 0.05)
- 🚨 Symbol permanently disabled (should only be temporary 12h)
- 🚨 Entire timeframe blocked (should never happen)
- 🚨 Large weight changes (>50% in one update)

---

## 💡 DESIGN PHILOSOPHY

**The learning systems are designed to:**
1. **Make small, incremental adjustments** (not big swings)
2. **Keep all signals active** (minimum weights ensure contribution)
3. **Temporarily suppress** (not permanently block)
4. **Learn from outcomes** (not from arbitrary rules)
5. **Self-correct** (reactivate suppressed symbols if conditions improve)

**This ensures:**
- ✅ Bot continues to explore all opportunities
- ✅ Learning is gradual and stable
- ✅ No single bad period causes permanent damage
- ✅ System can recover from mistakes

---

## 📝 CONCLUSION

**Learning systems make granular adjustments, not broad blocks:**
- ✅ Signal weights adjust (not disable)
- ✅ Profit thresholds adjust (not block)
- ✅ **Hold time adjusts** (minimum hold per symbol/direction, not block)
- ✅ **Exit timing adjusts** (TP1/TP2, trailing stops, not block)
- ✅ Symbol suppression is temporary (12h, not permanent)
- ❌ No timeframe blocking exists
- ❌ No permanent symbol blocking (except manual overrides)

**The bot will continue to trade all symbols and timeframes, but with adjusted parameters based on what's working:**
- **Entry:** Signal weights, profit thresholds
- **Hold:** Minimum hold time per symbol/direction
- **Exit:** Take-profit levels, trailing stops, stop-loss levels

