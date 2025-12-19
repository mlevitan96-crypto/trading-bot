# Exit Reason Labels - Standard Reference

## Standard Exit Reason Format

All exit reasons should follow these standardized formats to ensure consistent categorization and learning.

## ✅ **Profit Target Exits**

Format: `profit_target_{target}pct[_after_{time}]`

Examples:
- `profit_target_0.5pct`
- `profit_target_0.5pct_after_45min`
- `profit_target_1.0pct`
- `profit_target_1.0pct_after_60min`
- `profit_target_1.5pct`
- `profit_target_1.5pct_after_90min`
- `profit_target_2.0pct`
- `profit_target_2.0pct_after_120min`

**Alternative formats (for legacy compatibility):**
- `tp1` (take profit 1)
- `tp2` (take profit 2)

## ✅ **Time-Based Exits**

Format: `time_stop_{tier}[_{details}]`

Examples:
- `tier1_loss_2.0h_at_-0.75pct` (2h if losing > 0.5%)
- `tier2_stagnant_4.0h_at_0.15pct` (4h if gain < 0.2%)
- `tier3_weak_8.0h_at_0.40pct` (8h if gain < 0.5%)
- `max_hold_12.0h_force_exit` (12h max hold)
- `stagnant_6.0h_with_0.05pct_gain` (legacy format)
- `phase92_time_exit_{reason}`

## ✅ **Trailing Stop Exits**

Format: `trailing_stop_{tier}` or `trailing_{tier}`

Examples:
- `trailing_stop_tight` (< 30 min)
- `trailing_stop_medium` (30-120 min)
- `trailing_stop_wide` (120-240 min)
- `trailing_stop_overnight` (> 240 min)
- `trailing` (generic)

## ✅ **Stop Loss Exits**

Format: `stop_loss` or `stop_{type}`

Examples:
- `stop_loss`
- `stop_loss_-2.5pct`
- `catastrophic_guard_{reason}`
- `catastrophic_loss`

## ✅ **Other Exit Types**

- `manual` - Manual exit
- `signal_expired` - Signal expired/cancelled
- `risk_cap_max_positions` - Risk limit reached
- `risk_cap_asset_exposure` - Asset exposure limit
- `unknown` - Unknown/unclassified

## 🔍 **Categorization Rules**

The system categorizes exits using these rules (in order):

1. **Profit Target**: Contains `profit_target`, `tp1`, `tp2`
2. **Time Stop**: Contains `time`, `tier1`, `tier2`, `tier3`, `max_hold`, `stagnant`
3. **Trailing Stop**: Contains `trailing`, `trail`
4. **Stop Loss**: Contains `stop`, `loss`, `catastrophic`
5. **Unknown**: Default if no match

## 📋 **Files That Use Exit Reasons**

Key files that set/use exit reasons:

1. `src/phase92_profit_discipline.py` - Sets profit target and time stop reasons
2. `src/trailing_stop.py` - Sets trailing stop reasons
3. `src/position_manager.py` - Logs exit events with reasons
4. `src/catastrophic_loss_guard.py` - Sets catastrophic loss reasons
5. `src/exit_learning_and_enforcement.py` - Analyzes exit reasons for learning
6. `analyze_exit_performance.py` - Analyzes exit reasons

## ⚠️ **Consistency Checks**

All exit reasons should:
- Use lowercase
- Use underscores, not dashes or spaces
- Include target percentage where applicable
- Include timing information where relevant
- Be parseable by categorization rules
