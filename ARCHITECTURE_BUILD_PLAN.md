# Clean Architecture Build Plan
## Step-by-Step Implementation Guide

**Status:** Ready to begin full implementation  
**Timeline:** 3-5 days for Phase 1+2 (minimum for real money)

---

## 🎯 Phase 1: Complete Signal Bus (Days 1-2)

### Current Status
- ✅ SignalBus class exists and works
- ✅ Alpha signals emit to bus
- ⚠️ Need to verify all signal sources
- ⚠️ Need monitoring dashboard

### Tasks

#### Task 1.1: Audit All Signal Sources
- [ ] Find all places signals are generated
- [ ] List: Alpha signals ✅, PredictiveFlowEngine ❓, Others ❓
- [ ] Ensure all emit to SignalBus

#### Task 1.2: Add Signal Pipeline Monitoring
- [ ] Create dashboard endpoint for signal health
- [ ] Show signals by state
- [ ] Show stuck signals
- [ ] Show signal flow metrics

#### Task 1.3: Verify 100% Capture
- [ ] Compare file-based vs bus-based counts
- [ ] Ensure no signals lost
- [ ] Add validation checks

---

## 🎯 Phase 2: Complete State Machine (Day 3)

### Current Status
- ✅ SignalState enum exists
- ✅ Basic state transitions work
- ⚠️ Need explicit state machine class
- ⚠️ Need stuck signal monitoring

### Tasks

#### Task 2.1: Create SignalStateMachine Class
- [ ] Validate state transitions
- [ ] Prevent invalid transitions
- [ ] Add transition history

#### Task 2.2: Add Stuck Signal Monitoring
- [ ] Detect signals stuck > 1 hour
- [ ] Alert on stuck signals
- [ ] Auto-expire old signals

#### Task 2.3: Use State Transitions in bot_cycle
- [ ] Update state at each stage
- [ ] GENERATED → EVALUATING → APPROVED → EXECUTING → EXECUTED
- [ ] Track state changes consistently

---

## 🎯 Phase 3: Execution Separation (Days 4-6)

### Tasks

#### Task 3.1: Create ExecutionEngine Class
- [ ] Extract execution logic from bot_cycle
- [ ] Read approved signals from SignalBus
- [ ] Update signal state after execution

#### Task 3.2: Integrate ExecutionEngine
- [ ] Wire into bot_cycle
- [ ] Keep backward compatibility
- [ ] A/B test

---

## 🚀 Let's Start Building!

**Next Steps:**
1. Complete Phase 1 (Signal Bus) - 1-2 days
2. Complete Phase 2 (State Machine) - 1 day
3. Test everything - 1 day

**Total: 3-4 days to get to minimum viable architecture**

