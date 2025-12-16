# Clean Architecture Implementation Plan
## Step-by-Step Migration to Event-Driven Architecture

**Goal:** Transform fragmented signal flow into clean, event-driven architecture with continuous learning loop.

---

## Current State Analysis

### Signal Flow Issues

1. **Multiple Signal Sources, No Unification**
   - `bot_cycle.py` → `generate_live_alpha_signals()` → writes to `predictive_signals.jsonl`
   - `PredictiveFlowEngine` exists but never called
   - Signals scattered across files

2. **File-Based Handoffs (Fragile)**
   - `predictive_signals.jsonl` → `ensemble_predictions.jsonl` → `signal_outcomes.jsonl`
   - Workers poll files every 30-60s
   - No guaranteed delivery
   - Race conditions possible

3. **Learning Loop is Loose**
   - Learning updates files (`signal_weights.json`, etc.)
   - Signal generation reads files
   - No tight feedback loop
   - Learning doesn't directly improve next signal

4. **Execution Embedded in Signal Generation**
   - `bot_cycle.py` does everything
   - Can't test components independently
   - Hard to add new signal sources

---

## Phase 1: Signal Bus (Foundation) - **START HERE**

### Goal
Create unified signal bus that captures ALL signals, regardless of source.

### Implementation

```python
# src/signal_bus.py
class SignalBus:
    """
    Unified signal bus - single source of truth for all signals.
    Event-sourced, queryable, guaranteed delivery.
    """
    
    def __init__(self):
        self.event_log_path = PathRegistry.get_path("logs", "signal_bus.jsonl")
        self.state_index = {}  # signal_id -> current state
        self._lock = threading.Lock()
    
    def emit_signal(self, signal: Dict) -> str:
        """Emit signal event, returns signal_id"""
        signal_id = f"{signal['symbol']}_{int(time.time()*1000)}_{uuid.uuid4().hex[:8]}"
        
        event = {
            "event_type": "signal_generated",
            "signal_id": signal_id,
            "ts": time.time(),
            "signal": signal,
            "state": "generated"
        }
        
        with self._lock:
            # Write to event log
            with open(self.event_log_path, 'a') as f:
                f.write(json.dumps(event) + '\n')
            
            # Update state index
            self.state_index[signal_id] = {
                "state": "generated",
                "signal": signal,
                "ts": time.time()
            }
        
        return signal_id
    
    def get_signals(self, filters: Dict) -> List[Dict]:
        """Query signals by state, symbol, time, etc."""
        # Implementation: Read event log, filter, return
        pass
    
    def update_state(self, signal_id: str, new_state: str, metadata: Dict = None):
        """Update signal lifecycle state"""
        event = {
            "event_type": "state_change",
            "signal_id": signal_id,
            "old_state": self.state_index.get(signal_id, {}).get("state"),
            "new_state": new_state,
            "ts": time.time(),
            "metadata": metadata or {}
        }
        
        with self._lock:
            with open(self.event_log_path, 'a') as f:
                f.write(json.dumps(event) + '\n')
            
            if signal_id in self.state_index:
                self.state_index[signal_id]["state"] = new_state
                self.state_index[signal_id].update(metadata or {})
```

### Integration Steps

1. **Create `src/signal_bus.py`** with SignalBus class
2. **Modify `bot_cycle.py`** to emit to bus (in addition to files)
3. **Keep file-based flow working** (backward compatibility)
4. **Add monitoring** to verify bus captures all signals

### Success Criteria
- All signals from `bot_cycle` appear in signal bus
- Can query signals by state, symbol, time
- File-based flow still works (no breaking changes)

---

## Phase 2: Explicit State Machine

### Goal
Make signal lifecycle explicit and queryable.

### Implementation

```python
# src/signal_state_machine.py
class SignalState(Enum):
    GENERATED = "generated"
    EVALUATING = "evaluating"
    APPROVED = "approved"
    EXECUTING = "executing"
    EXECUTED = "executed"
    BLOCKED = "blocked"
    EXPIRED = "expired"
    LEARNED = "learned"

class SignalStateMachine:
    """Manages signal lifecycle state transitions"""
    
    def transition(self, signal_id: str, new_state: SignalState, metadata: Dict = None):
        """Transition signal to new state"""
        # Validate transition
        # Update state
        # Emit state change event
        pass
    
    def get_signals_by_state(self, state: SignalState) -> List[str]:
        """Get all signal IDs in given state"""
        pass
```

### Integration Steps

1. **Create state machine module**
2. **Integrate with SignalBus**
3. **Update bot_cycle** to use state transitions
4. **Add monitoring** for stuck signals

---

## Phase 3: Separated Execution Layer

### Goal
Extract execution from signal generation.

### Implementation

```python
# src/execution_engine.py
class ExecutionEngine:
    """Handles all trade execution"""
    
    def __init__(self, signal_bus: SignalBus):
        self.signal_bus = signal_bus
    
    def execute_approved_signal(self, signal_id: str) -> ExecutionResult:
        """Execute signal that has been approved"""
        # Get signal from bus
        # Run entry flow
        # Place order
        # Update signal state
        pass
```

### Integration Steps

1. **Create ExecutionEngine class**
2. **Move execution logic from bot_cycle**
3. **Make bot_cycle call ExecutionEngine**
4. **Test execution independently**

---

## Phase 4: Unified Learning Loop

### Goal
Create tight feedback loop where learning directly improves signals.

### Implementation

```python
# src/learning_engine.py
class LearningEngine:
    """Unified learning system with direct feedback"""
    
    def __init__(self, signal_bus: SignalBus):
        self.signal_bus = signal_bus
        self.feedback_cache = {}  # symbol -> latest feedback
    
    def analyze_outcome(self, signal_id: str, outcome: TradeOutcome):
        """Analyze trade outcome and generate feedback"""
        # Analyze P&L
        # Update signal weights
        # Generate feedback
        # Store in feedback cache
        pass
    
    def get_feedback(self, symbol: str, signal_type: str) -> Dict:
        """Get latest learning feedback for symbol/signal"""
        return self.feedback_cache.get(f"{symbol}_{signal_type}", {})
    
    def apply_feedback_to_signal(self, signal: Dict) -> Dict:
        """Apply learning feedback to signal before evaluation"""
        symbol = signal['symbol']
        feedback = self.get_feedback(symbol, signal.get('type', 'alpha'))
        
        # Apply weight adjustments
        # Apply direction inversions
        # Apply threshold adjustments
        return modified_signal
```

### Integration Steps

1. **Create LearningEngine class**
2. **Consolidate all learning into it**
3. **Make signal generation read feedback**
4. **Ensure feedback updates immediately**

---

## Phase 5: Complete Migration

### Goal
Remove file-based handoffs, use event bus exclusively.

### Steps

1. **Migrate ensemble predictor** to read from bus
2. **Migrate signal resolver** to read from bus
3. **Remove file polling** workers
4. **Add real-time event processing**

---

## Immediate Action Items (Before Real Money)

### Critical (Do Now)

1. ✅ **Create SignalBus** - Foundation for everything
2. ✅ **Make bot_cycle emit to bus** - Capture all signals
3. ✅ **Add state tracking** - Know where signals are
4. ✅ **Add monitoring** - Dashboard for signal pipeline health

### Important (Do Soon)

5. **Separate execution** - Extract from bot_cycle
6. **Unify learning** - Single learning engine
7. **Tight feedback loop** - Learning improves signals immediately

### Nice to Have (Later)

8. **Real-time event bus** - Replace file polling
9. **Event replay** - Debug any point in time
10. **Advanced queries** - Complex signal filtering

---

## Risk Mitigation

### Backward Compatibility
- Keep file-based flow working during migration
- Run both systems in parallel
- Switch over gradually

### Testing Strategy
- Unit tests for each component
- Integration tests for signal flow
- End-to-end tests for learning loop

### Rollback Plan
- Keep old code until new is proven
- Feature flags for new vs old
- Can revert quickly if issues

---

## Success Metrics

### Before Real Money, Verify:

1. **Signal Capture**: 100% of signals captured in bus
2. **State Tracking**: All signals have explicit state
3. **Learning Loop**: Feedback improves next signals
4. **Execution Separation**: Execution is testable independently
5. **Monitoring**: Can see pipeline health in real-time

---

## Timeline Estimate

- **Phase 1 (Signal Bus)**: 2-3 days
- **Phase 2 (State Machine)**: 1-2 days
- **Phase 3 (Execution Separation)**: 2-3 days
- **Phase 4 (Learning Loop)**: 3-4 days
- **Phase 5 (Complete Migration)**: 2-3 days

**Total: 10-15 days** for complete migration

**Minimum for Real Money**: Phase 1 + Phase 2 (3-5 days)

