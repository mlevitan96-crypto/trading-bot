# Enhanced Learning Engine Documentation
## Comprehensive Learning System for Trading Bot

**Purpose:** Review everything - blocked trades, missed opportunities, what-if scenarios, guard effectiveness, and strategy performance.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│ SIGNAL GENERATION                                            │
│  └─> Emits signals to SignalBus with granular metadata      │
└─────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────┐
│ DECISION TRACKER                                             │
│  - Tracks every decision (approved/blocked)                 │
│  - Captures market snapshot                                 │
│  - Records blocker component and reason                     │
│  - Emits SignalDecisionEvent                                │
└─────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────┐
│ SHADOW EXECUTION ENGINE                                      │
│  - Simulates ALL signals (even blocked ones)                │
│  - Tracks hypothetical P&L                                  │
│  - Enables what-if analysis                                 │
└─────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────┐
│ ENHANCED LEARNING ENGINE                                     │
│  - Analyzes blocked trades                                   │
│  - Evaluates guard effectiveness                            │
│  - Runs what-if scenarios                                   │
│  - Generates feedback for signal generation                 │
└─────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────┐
│ ANALYTICS REPORT GENERATOR                                   │
│  - Blocked opportunity cost                                 │
│  - Signal decay analysis                                    │
│  - Strategy leaderboard                                     │
│  - Guard effectiveness report                               │
└─────────────────────────────────────────────────────────────┘
```

---

## Components

### 1. Event Schemas (`src/events/schemas.py`)

**Purpose:** Structured event schemas for all trading events.

**Key Schemas:**
- `SignalDecisionEvent` - Tracks why signals are approved/blocked
- `SignalEvent` - Enhanced signal with granular attribution
- `ShadowTradeOutcomeEvent` - Hypothetical trade outcomes
- `MarketSnapshot` - Market state at decision time

**Usage:**
```python
from src.events.schemas import create_decision_event, MarketSnapshot

# Create decision event
decision = create_decision_event(
    signal_id="BTC_1234567890_abc123",
    decision="BLOCKED",
    blocker_component="VolatilityGuard",
    blocker_reason="Current vol 0.05 > Max 0.04",
    market_snapshot=MarketSnapshot(price=50000, spread=2.5, spread_bps=0.5)
)
```

---

### 2. Decision Tracker (`src/learning/decision_tracker.py`)

**Purpose:** Tracks all signal decisions with full context.

**Features:**
- Captures market snapshot at decision time
- Records blocker component and reason
- Emits to SignalBus for event sourcing
- Enables what-if analysis later

**Usage:**
```python
from src.learning.decision_tracker import get_decision_tracker

tracker = get_decision_tracker()

# Track a blocked signal
tracker.track_block(
    signal_id="BTC_1234567890_abc123",
    blocker_component="VolatilityGuard",
    blocker_reason="Current vol 0.05 > Max 0.04",
    symbol="BTCUSDT",
    signal_metadata={"strategy": "MeanReversion", "rsi": 24.5}
)

# Track an approved signal
tracker.track_approval(
    signal_id="BTC_1234567890_abc123",
    approved_by="AllGates",
    symbol="BTCUSDT"
)
```

**Integration with Guards:**
```python
# In your guard function:
def volatility_guard(signal):
    if current_vol > max_vol:
        # Track the block
        tracker = get_decision_tracker()
        tracker.track_block(
            signal_id=signal["signal_id"],
            blocker_component="VolatilityGuard",
            blocker_reason=f"Current vol {current_vol} > Max {max_vol}",
            symbol=signal["symbol"]
        )
        return False
    return True
```

---

### 3. Shadow Execution Engine (`src/shadow_execution_engine.py`)

**Purpose:** Simulates ALL signals (even blocked ones) to enable what-if analysis.

**Features:**
- Subscribes to SignalBus
- Simulates entry at market snapshot price
- Tracks exit using actual market prices
- Calculates hypothetical P&L
- Logs ShadowTradeOutcomeEvent

**Usage:**
```python
from src.shadow_execution_engine import get_shadow_engine

# Start shadow engine (in run.py or startup)
shadow_engine = get_shadow_engine()
shadow_engine.start()

# Get shadow performance
performance = shadow_engine.get_shadow_performance(hours=24)
print(f"Shadow trades: {performance['total_trades']}")
print(f"Win rate: {performance['win_rate']*100:.1f}%")
print(f"Total P&L: ${performance['total_pnl']:.2f}")
```

**What It Enables:**
- "What if I disabled the Volatility Guard?" → Check shadow outcomes for signals blocked by VolatilityGuard
- "How much money did guards save/lose?" → Compare real vs shadow performance
- "What's the unfiltered performance?" → Shadow performance shows all signals

---

### 4. Enhanced Learning Engine (`src/learning/enhanced_learning_engine.py`)

**Purpose:** Comprehensive learning that reviews everything.

**Features:**
1. **Blocked Trade Analysis** - What did we miss?
2. **Missed Opportunity Tracking** - What would have happened?
3. **What-If Scenarios** - Different weights/parameters
4. **Guard Effectiveness** - Which guards help/hurt?
5. **Strategy Performance** - Which strategies work best?
6. **Feedback Loop** - Directly improve signal generation

**Usage:**
```python
from src.learning.enhanced_learning_engine import get_enhanced_learning_engine

engine = get_enhanced_learning_engine()

# Run full learning cycle
learnings = engine.run_learning_cycle(hours=24)

# Access learnings
print(f"Blocked opportunity cost: ${learnings['blocked_analysis']['net_opportunity_cost']:.2f}")
print(f"Effective guards: {len(learnings['guard_effectiveness']['effective_guards'])}")
print(f"Top strategy: {learnings['strategy_performance']['top_strategy']}")
```

**What It Reviews:**
- **Blocked Trades:** How much money did we miss by blocking?
- **Missed Opportunities:** Signals that expired before execution
- **What-If Scenarios:**
  - What if Volatility Guard was disabled?
  - What if ROI threshold was 0.5% instead of 1%?
  - What if signal weights were optimized?
- **Guard Effectiveness:** Which guards save money vs cost money?
- **Strategy Performance:** Which strategies are most profitable?

---

### 5. Analytics Report Generator (`src/analytics/report_generator.py`)

**Purpose:** Generate comprehensive analytics reports.

**Features:**
- Blocked Opportunity Cost
- Signal Decay (time to execution)
- Strategy Leaderboard
- Guard Effectiveness

**Usage:**
```python
from src.analytics.report_generator import generate_report

# Generate full report
report = generate_report(hours=24)

# Access specific metrics
blocked_cost = report["blocked_opportunity_cost"]
print(f"Missed profit: ${blocked_cost['missed_profit']:.2f}")
print(f"Avoided loss: ${blocked_cost['avoided_loss']:.2f}")
print(f"Net cost: ${blocked_cost['net_opportunity_cost']:.2f}")

signal_decay = report["signal_decay"]
print(f"Average decay: {signal_decay['avg_decay_seconds']/60:.1f} minutes")

strategy_leaderboard = report["strategy_leaderboard"]
for strategy, stats in sorted(strategy_leaderboard.items(), 
                            key=lambda x: x[1]['total_pnl'], reverse=True):
    print(f"{strategy}: ${stats['total_pnl']:.2f} | {stats['win_rate']*100:.1f}% WR")
```

**Command Line:**
```bash
python3 -c "from src.analytics.report_generator import generate_report; generate_report(hours=24)"
```

---

## Integration Guide

### Step 1: Integrate Decision Tracker into Guards

Modify your guard functions to track decisions:

```python
from src.learning.decision_tracker import get_decision_tracker

def volatility_guard(signal: dict) -> bool:
    tracker = get_decision_tracker()
    signal_id = signal.get("signal_id")
    symbol = signal.get("symbol")
    
    current_vol = get_current_volatility(symbol)
    max_vol = get_max_volatility(symbol)
    
    if current_vol > max_vol:
        # Track the block
        tracker.track_block(
            signal_id=signal_id,
            blocker_component="VolatilityGuard",
            blocker_reason=f"Current vol {current_vol:.4f} > Max {max_vol:.4f}",
            symbol=symbol,
            signal_metadata=signal.get("metadata", {})
        )
        return False
    
    # Track approval
    tracker.track_approval(
        signal_id=signal_id,
        approved_by="VolatilityGuard",
        symbol=symbol
    )
    return True
```

### Step 2: Start Shadow Execution Engine

In `src/run.py` or startup:

```python
from src.shadow_execution_engine import get_shadow_engine

# Start shadow engine
shadow_engine = get_shadow_engine()
shadow_engine.start()
```

### Step 3: Run Learning Cycles

Schedule learning cycles (e.g., daily):

```python
from src.learning.enhanced_learning_engine import get_enhanced_learning_engine

# Run learning cycle
engine = get_enhanced_learning_engine()
learnings = engine.run_learning_cycle(hours=24)

# Apply feedback
engine._apply_feedback(learnings["feedback"])
```

### Step 4: Generate Analytics Reports

Add to dashboard or scheduled reports:

```python
from src.analytics.report_generator import generate_report

# Generate report
report = generate_report(hours=24)

# Display in dashboard
# ... dashboard code ...
```

---

## Key Questions Answered

### 1. "How much money would I have made if I disabled the Volatility Guard?"

```python
from src.learning.enhanced_learning_engine import get_enhanced_learning_engine

engine = get_enhanced_learning_engine()
learnings = engine.run_learning_cycle(hours=24)

# Check what-if scenario
what_if = learnings["what_if_scenarios"]["no_volatility_guard"]
print(f"Net P&L if disabled: ${what_if['net_pnl_if_disabled']:.2f}")
```

### 2. "Show me win rate for RSI Divergence signals vs. MACD signals"

```python
from src.analytics.report_generator import generate_report

report = generate_report(hours=24)
strategies = report["strategy_leaderboard"]

rsi_wr = strategies.get("RSI_Divergence", {}).get("win_rate", 0)
macd_wr = strategies.get("MACD", {}).get("win_rate", 0)

print(f"RSI Divergence WR: {rsi_wr*100:.1f}%")
print(f"MACD WR: {macd_wr*100:.1f}%")
```

### 3. "What's the average time between signal generation and execution?"

```python
from src.analytics.report_generator import generate_report

report = generate_report(hours=24)
decay = report["signal_decay"]

print(f"Average decay: {decay['avg_decay_seconds']/60:.1f} minutes")
print(f"Median decay: {decay['median_decay_seconds']/60:.1f} minutes")
```

### 4. "Which guards are saving money vs costing money?"

```python
from src.learning.enhanced_learning_engine import get_enhanced_learning_engine

engine = get_enhanced_learning_engine()
learnings = engine.run_learning_cycle(hours=24)

guards = learnings["guard_effectiveness"]

print("Effective guards (saving money):")
for guard in guards["effective_guards"]:
    print(f"  {guard['guard']}: Saved ${guard['net_saved']:.2f}")

print("\nIneffective guards (costing money):")
for guard in guards["ineffective_guards"]:
    print(f"  {guard['guard']}: Cost ${guard['net_cost']:.2f}")
```

---

## Data Flow

1. **Signal Generated** → SignalBus
2. **Guard Evaluates** → DecisionTracker tracks decision
3. **Shadow Engine** → Simulates trade (even if blocked)
4. **Learning Engine** → Analyzes outcomes, generates feedback
5. **Analytics** → Generates reports
6. **Feedback Applied** → Improves next signals

---

## Files Created

- `src/events/schemas.py` - Event schemas
- `src/shadow_execution_engine.py` - Shadow execution
- `src/analytics/report_generator.py` - Analytics reports
- `src/learning/decision_tracker.py` - Decision tracking
- `src/learning/enhanced_learning_engine.py` - Enhanced learning

---

## Next Steps

1. **Integrate Decision Tracker** into all guards/gates
2. **Start Shadow Engine** in run.py
3. **Schedule Learning Cycles** (daily/hourly)
4. **Add Analytics to Dashboard**
5. **Review Learnings** regularly

---

## Summary

The Enhanced Learning Engine provides:
- ✅ Complete visibility into blocked trades
- ✅ What-if analysis capabilities
- ✅ Guard effectiveness evaluation
- ✅ Strategy performance tracking
- ✅ Direct feedback loop to improve signals

This is the "big wheel" - learning that directly improves signal generation.

