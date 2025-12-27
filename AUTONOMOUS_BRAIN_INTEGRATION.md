# Autonomous Brain Integration Guide

This document describes how to integrate the new autonomous brain components.

## Components Created

1. **Market Regime Classifier** (`src/regime_classifier.py`)
   - Hurst Exponent (100-period rolling)
   - HMM volatility detection
   - Composite regime classification

2. **Shadow Portfolio Engine** (`src/shadow_execution_engine.py`)
   - Virtual execution of all signals
   - Counterfactual tracking
   - Opportunity cost analysis

3. **Bayesian Policy Optimizer** (`src/policy_tuner.py`)
   - Optuna-based optimization
   - Entry threshold and stop loss tuning
   - Sharpe ratio maximization

4. **Feature Drift Detector** (`src/feature_drift_detector.py`)
   - CUSUM algorithm for drift detection
   - Automatic signal quarantine
   - Performance monitoring

5. **Adaptive Signal Optimizer** (`src/adaptive_signal_optimizer.py`)
   - Regime-based weight profiles (TREND, RANGE, CHOP)
   - Dynamic weight switching

## Integration Points

### 1. Regime Classifier Integration

In `src/bot_cycle.py`, update price tracking:

```python
from src.regime_classifier import get_regime_classifier

# In execute_signal or run_bot_cycle:
classifier = get_regime_classifier()
symbol = signal.get('symbol', '')
price = signal.get('price', signal.get('entry_price', 0))
if price > 0:
    classifier.update_price(symbol, price)
    regime_info = classifier.get_regime(symbol)
    active_regime = regime_info['composite_regime']
```

### 2. Shadow Portfolio Integration

In `src/bot_cycle.py`, execute_signal function:

```python
from src.shadow_execution_engine import get_shadow_engine

def execute_signal(signal: dict, wallet_balance: float, rolling_expectancy: float) -> dict:
    # ... existing code ...
    
    # Execute in shadow portfolio (always, even if blocked)
    shadow_engine = get_shadow_engine()
    entry_price = signal.get('entry_price', signal.get('price', 0))
    if entry_price > 0:
        blocked_reason = result.get('reason') if result.get('status') == 'blocked' else None
        shadow_engine.execute_signal(signal, entry_price, blocked_reason)
    
    # ... rest of code ...
```

### 3. 4-Hour Comparison Cycle

Add to `src/run.py` in `run_heavy_initialization()`:

```python
import schedule
from src.shadow_execution_engine import compare_shadow_vs_live_performance

def shadow_comparison_cycle():
    """Compare shadow vs live performance every 4 hours."""
    comparison = compare_shadow_vs_live_performance(days=7)
    
    if comparison.get('should_optimize_guards'):
        print(f"🚨 [SHADOW] Shadow outperforming by {comparison['opportunity_cost_pct']:.1f}% - Guard optimization needed")
        # Trigger guard optimization alert
    
    return comparison

# Schedule every 4 hours
schedule.every(4).hours.do(shadow_comparison_cycle)
```

### 4. Adaptive Signal Optimizer Integration

In signal computation (e.g., `src/conviction_gate.py`):

```python
from src.adaptive_signal_optimizer import get_active_weights

# In _calculate_weighted_score or similar:
symbol = signal.get('symbol', '')
regime_weights = get_active_weights(symbol)

# Use regime_weights instead of static SIGNAL_WEIGHTS
for signal_name, signal_data in signal_map.items():
    weight = regime_weights.get(signal_name, SIGNAL_WEIGHTS.get(signal_name, 0.1))
    # ... rest of calculation ...
```

### 5. Policy Optimizer Integration

Add to nightly scheduler in `src/run.py`:

```python
from src.policy_tuner import run_daily_optimization

# In nightly_learning_scheduler or meta_learning_scheduler:
def run_policy_optimization():
    """Run daily policy optimization."""
    try:
        results = run_daily_optimization()
        if results.get('optimization', {}).get('success'):
            print(f"✅ [POLICY-TUNER] Optimized parameters: {results['optimization']['best_params']}")
    except Exception as e:
        print(f"⚠️ [POLICY-TUNER] Error: {e}")

schedule.every().day.at("03:00").do(run_policy_optimization)  # 3 AM UTC
```

### 6. Feature Drift Detection Integration

Add to learning cycle:

```python
from src.feature_drift_detector import run_drift_detection

# In nightly or continuous learning cycle:
def run_drift_check():
    """Run feature drift detection."""
    try:
        results = run_drift_detection()
        quarantined = results.get('detection', {}).get('total_quarantined', 0)
        if quarantined > 0:
            print(f"⚠️ [DRIFT] {quarantined} signals quarantined")
    except Exception as e:
        print(f"⚠️ [DRIFT] Error: {e}")

# Run every 6 hours
schedule.every(6).hours.do(run_drift_check)
```

### 7. Dashboard Integration

In `src/pnl_dashboard_v2.py`, add new sections:

```python
from src.regime_classifier import get_regime_classifier
from src.shadow_execution_engine import compare_shadow_vs_live_performance
from src.feature_drift_detector import get_drift_monitor

# Regime Health Gauge
regime_classifier = get_regime_classifier()
regime_info = regime_classifier.get_regime('BTCUSDT')  # Or primary symbol
hurst_value = regime_info['hurst_value']

# Shadow Opportunity Cost
comparison = compare_shadow_vs_live_performance(days=7)
opportunity_cost = comparison.get('opportunity_cost_pct', 0.0)

# Signal Drift Status
drift_monitor = get_drift_monitor()
quarantine_state = drift_monitor.quarantine_state
```

## Dependencies

Add to `requirements.txt`:
- `hmmlearn>=0.3.0`
- `optuna>=3.5.0`

## Testing

1. Verify regime classifier updates prices correctly
2. Check shadow portfolio logs shadow executions
3. Confirm policy optimizer runs and updates config
4. Verify drift detector quarantines failing signals
5. Test adaptive optimizer switches weights based on regime

## Next Steps

1. Integrate components into existing codebase
2. Add comprehensive logging
3. Test with live data
4. Monitor performance improvements
5. Adjust thresholds based on results

