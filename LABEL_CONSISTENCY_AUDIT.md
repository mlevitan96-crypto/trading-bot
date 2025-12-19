# Label Consistency Audit - Exit Reasons

## ✅ **Standardized Exit Reason Format**

All exit reasons MUST follow these exact formats:

### **Profit Target Exits**
- Format: `profit_target_{target}pct[_after_{time}min]`
- Examples:
  - `profit_target_0.5pct`
  - `profit_target_0.5pct_after_45min`
  - `profit_target_1.0pct`
  - `profit_target_1.0pct_after_60min`
  - `profit_target_1.5pct`
  - `profit_target_1.5pct_after_90min`
  - `profit_target_2.0pct`
  - `profit_target_2.0pct_after_120min`

**Files that create these:**
- `src/trailing_stop.py` (lines 160, 165, 170, 175)
- `src/phase92_profit_discipline.py` (lines 382, 387, 392, 397)

### **Time-Based Exits**
- Format: `tier{N}_{type}_{time}h_at_{pnl}pct` or `max_hold_{time}h_force_exit`
- Examples:
  - `tier1_loss_2.0h_at_-0.75pct`
  - `tier2_stagnant_4.0h_at_0.15pct`
  - `tier3_weak_8.0h_at_0.40pct`
  - `max_hold_12.0h_force_exit`
  - `stagnant_6.0h_with_0.05pct_gain` (legacy, still acceptable)
  - `phase92_time_exit_{rec_reason}` (composite format)

**Files that create these:**
- `src/phase92_profit_discipline.py` (lines 403, 408, 413, 418, 423)
- `src/bot_cycle.py` (line 1169) - adds `phase92_time_exit_` prefix

### **Trailing Stop Exits**
- Format: `trailing_stop_{tier}` or `trailing_{tier}`
- Examples:
  - `trailing_stop_tight` (< 30 min)
  - `trailing_stop_medium` (30-120 min)
  - `trailing_stop_wide` (120-240 min)
  - `trailing_stop_overnight` (> 240 min)

**Files that create these:**
- `src/trailing_stop.py` (line 205) - adds tier suffix

### **Stop Loss Exits**
- Format: `stop_loss` or `catastrophic_guard_{reason}`
- Examples:
  - `stop_loss`
  - `stop_loss_-2.5pct`
  - `catastrophic_guard_{reason}`
  - `catastrophic_loss`

**Files that create these:**
- `src/catastrophic_loss_guard.py`
- `src/exit_learning_and_enforcement.py` (line 138)

## 🔍 **Categorization Rules (Standardized)**

All categorization logic should use these rules (in priority order):

1. **Profit Target**: Contains `profit_target`, `tp1`, `tp2`
2. **Time Stop**: Contains `time`, `tier1`, `tier2`, `tier3`, `max_hold`, `stagnant`
3. **Trailing Stop**: Contains `trailing`, `trail`
4. **Stop Loss**: Contains `stop`, `loss`, `catastrophic` (but NOT `trailing_stop`)
5. **Unknown**: Default fallback

**Implementation locations:**
- `src/profitability_trader_persona.py::_categorize_exit_type()` (lines 370-385)
- `analyze_exit_performance.py` (lines 103-157)
- `src/position_manager.py` (lines 821-830)

## ✅ **Verified Consistent Labels**

### **Exit Type Constants** (for exit_type field)
- `profit_target` (or `tp1`, `tp2` for legacy compatibility)
- `time_stop`
- `trailing_stop` (or `trailing`)
- `stop_loss` (or `stop`)
- `closed` (default/unknown)
- `unknown` (fallback)

**Used in:**
- `src/position_manager.py` (exit_type field)
- `src/exit_learning_and_enforcement.py` (ExitTuner analysis)
- `analyze_exit_performance.py` (categorization)
- `src/profitability_trader_persona.py` (analysis)

## ⚠️ **Known Inconsistencies (To Monitor)**

1. **Legacy formats still in use:**
   - `tp1`, `tp2` (instead of `profit_target`)
   - These are handled by categorization rules but should migrate to full format

2. **Composite reasons:**
   - `phase92_time_exit_{reason}` - Contains nested reason string
   - Categorization should parse inner reason

## 📋 **Files That MUST Use Standardized Labels**

1. `src/trailing_stop.py` - Sets profit_target and trailing_stop reasons
2. `src/phase92_profit_discipline.py` - Sets profit_target and time_stop reasons
3. `src/bot_cycle.py` - Passes through exit reasons
4. `src/position_manager.py` - Logs exit events with reasons
5. `src/catastrophic_loss_guard.py` - Sets catastrophic exit reasons
6. `src/exit_learning_and_enforcement.py` - Analyzes exit reasons

## ✅ **Verification Check**

Run this to verify label consistency:
```python
# Check all exit reasons in recent trades
from src.data_registry import DataRegistry as DR
positions = DR.get_closed_positions(hours=168)

exit_reasons = set([p.get("exit_reason", "unknown") for p in positions])

# Check for non-standard formats
non_standard = [r for r in exit_reasons if not any([
    "profit_target" in r.lower(),
    "time" in r.lower() and ("tier" in r.lower() or "stagnant" in r.lower()),
    "trailing" in r.lower(),
    "stop" in r.lower() or "loss" in r.lower(),
    r == "manual",
    r == "unknown"
])]

if non_standard:
    print(f"⚠️  Non-standard exit reasons found: {non_standard}")
```
