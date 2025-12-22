# Trading Bot Architecture Map
**Complete System Architecture and Data Flow Documentation**

---

## 📋 Table of Contents

1. [System Overview](#system-overview)
2. [Component Architecture](#component-architecture)
3. [Data Flow Pipeline](#data-flow-pipeline)
4. [Worker Process Architecture](#worker-process-architecture)
5. [Learning Loop Architecture](#learning-loop-architecture)
6. [File System Map](#file-system-map)
7. [Component Dependencies](#component-dependencies)
8. [Signal Flow Diagram](#signal-flow-diagram)
9. [Trade Execution Flow](#trade-execution-flow)
10. [Learning Feedback Loop](#learning-feedback-loop)

---

## 1. System Overview

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    TRADING BOT SYSTEM                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐   │
│  │   DATA       │    │   SIGNAL     │    │   TRADE      │   │
│  │   SOURCES    │───▶│   GENERATION │───▶│   EXECUTION  │   │
│  └──────────────┘    └──────────────┘    └──────────────┘   │
│         │                   │                     │           │
│         │                   │                     │           │
│         ▼                   ▼                     ▼           │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐   │
│  │   LEARNING   │◀───│   OUTCOME    │◀───│   PORTFOLIO  │   │
│  │   ENGINE     │    │   TRACKING   │    │   TRACKER    │   │
│  └──────────────┘    └──────────────┘    └──────────────┘   │
│         │                                                       │
│         ▼                                                       │
│  ┌──────────────┐                                             │
│  │   FEEDBACK   │                                             │
│  │   INJECTION  │                                             │
│  └──────────────┘                                             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Core Principles

1. **Multi-Process Architecture**: Workers run in separate processes for isolation
2. **Event-Driven**: Components react to data changes and events
3. **Learning-Driven**: Continuous improvement through outcome analysis
4. **Fail-Safe**: Health monitoring and auto-remediation
5. **Data-Centric**: All state stored in files for persistence

---

## 2. Component Architecture

### 2.1 Signal Generation Layer

```
┌─────────────────────────────────────────────────────────────┐
│              SIGNAL GENERATION PIPELINE                     │
└─────────────────────────────────────────────────────────────┘

┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Data Sources   │────▶│  Predictive      │────▶│  Ensemble       │
│                 │     │  Engine          │     │  Predictor      │
│  - Kraken API   │     │  (Worker)        │     │  (Worker)       │
│  - CoinGlass    │     │                  │     │                 │
│  - Market Data  │     │  Output:         │     │  Output:        │
│                 │     │  predictive_    │     │  ensemble_     │
│                 │     │  signals.jsonl   │     │  predictions.   │
│                 │     │                  │     │  jsonl          │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                                │                         │
                                │                         │
                                ▼                         ▼
                        ┌──────────────────────────────────────┐
                        │     Signal Outcome Tracker          │
                        │     (Logs to pending_signals.json)  │
                        └──────────────────────────────────────┘
```

**Components:**
- `src/predictive_flow_engine.py`: Generates predictive signals
- `src/ensemble_predictor.py`: Creates ensemble predictions
- `src/signal_outcome_tracker.py`: Logs and tracks signals

**Worker Processes:**
- `_worker_predictive_engine()`: Runs predictive engine
- `_worker_ensemble_predictor()`: Runs ensemble predictor
- `_worker_signal_resolver()`: Resolves signal outcomes

---

### 2.2 Trade Execution Layer

```
┌─────────────────────────────────────────────────────────────┐
│              TRADE EXECUTION PIPELINE                       │
└─────────────────────────────────────────────────────────────┘

┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Signal Input   │────▶│  Conviction     │────▶│  Trade          │
│                 │     │  Gate           │     │  Executor       │
│  - Predictive   │     │                 │     │                 │
│  - Ensemble     │     │  Validation:    │     │  - Kraken API   │
│  - Pending      │     │  - OFI Check    │     │  - Position     │
│                 │     │  - Fee Gate     │     │    Management   │
│                 │     │  - Correlation  │     │                 │
│                 │     │  - Intelligence  │     │  Output:         │
│                 │     │  - Pre-Entry   │     │  positions_     │
│                 │     │                 │     │  futures.json   │
│                 │     │  Output:        │     │                 │
│                 │     │  should_trade   │     │                 │
│                 │     │  position_size  │     │                 │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                                │
                                │
                                ▼
                        ┌─────────────────┐
                        │  Portfolio      │
                        │  Tracker        │
                        │                 │
                        │  - Open/Closed  │
                        │  - P&L          │
                        │  - Fees         │
                        └─────────────────┘
```

**Components:**
- `src/conviction_gate.py`: Validates and sizes trades
- `src/futures_portfolio_tracker.py`: Tracks positions and P&L
- `src/bot_cycle.py`: Main trading cycle orchestrator

---

### 2.3 Learning Layer

```
┌─────────────────────────────────────────────────────────────┐
│              LEARNING PIPELINE                               │
└─────────────────────────────────────────────────────────────┘

┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Outcome Data   │────▶│  Continuous     │────▶│  Adjustment    │
│                 │     │  Learning       │     │  Generator      │
│  - Executed     │     │  Controller     │     │                 │
│  - Blocked      │     │                 │     │  - Weights      │
│  - Missed       │     │  Analyzes:      │     │  - Thresholds   │
│  - Counterfact  │     │  - Profitability│     │  - Sizing       │
│                 │     │  - Patterns     │     │  - Timing       │
│                 │     │  - Regimes      │     │                 │
│                 │     │                 │     │  Output:        │
│                 │     │  Output:        │     │  adjustments   │
│                 │     │  insights       │     │                 │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                                │
                                │
                                ▼
                        ┌─────────────────┐
                        │  Feedback       │
                        │  Injector       │
                        │                 │
                        │  - Updates      │
                        │    weights      │
                        │  - Updates      │
                        │    policies     │
                        │  - Updates      │
                        │    configs      │
                        └─────────────────┘
```

**Components:**
- `src/continuous_learning_controller.py`: Main learning orchestrator
- `src/signal_weight_learner.py`: Updates signal weights
- `src/profitability_analyzer.py`: Analyzes trade outcomes
- `src/data_enrichment_layer.py`: Enriches signals with outcomes

---

## 3. Data Flow Pipeline

### 3.1 Complete Signal-to-Trade Flow

```
STEP 1: DATA COLLECTION
────────────────────────
Kraken API ──┐
CoinGlass ───┼──▶ Feature Builder ──▶ feature_store/
Market Data ─┘

STEP 2: SIGNAL GENERATION
─────────────────────────
Features ──▶ Predictive Engine ──▶ predictive_signals.jsonl
                │
                └──▶ Ensemble Predictor ──▶ ensemble_predictions.jsonl

STEP 3: SIGNAL LOGGING
──────────────────────
predictive_signals.jsonl ──┐
ensemble_predictions.jsonl ┼──▶ Signal Outcome Tracker ──▶ pending_signals.json
                            └──▶ signals_universe.jsonl

STEP 4: SIGNAL VALIDATION
─────────────────────────
pending_signals.json ──▶ Conviction Gate ──▶ should_trade (True/False)
                            │
                            ├──▶ OFI Check (long_ofi_requirement ≥ 0.5)
                            ├──▶ Fee Gate
                            ├──▶ Correlation Throttle
                            ├──▶ Intelligence Gate
                            └──▶ Pre-Entry Gate

STEP 5: TRADE EXECUTION
───────────────────────
should_trade=True ──▶ Trade Executor ──▶ Kraken Futures API
                        │
                        └──▶ Position Opened

STEP 6: POSITION TRACKING
─────────────────────────
Position Opened ──▶ Portfolio Tracker ──▶ positions_futures.json
                        │
                        ├──▶ Open Positions
                        ├──▶ Closed Positions
                        └──▶ P&L + Fees

STEP 7: OUTCOME TRACKING
────────────────────────
Closed Position ──▶ Signal Outcome Tracker ──▶ signal_outcomes.jsonl
                        │
                        └──▶ Data Enrichment Layer ──▶ enriched_decisions.jsonl

STEP 8: LEARNING
────────────────
enriched_decisions.jsonl ──▶ Continuous Learning Controller
                                │
                                ├──▶ Profitability Analyzer
                                ├──▶ Signal Weight Learner
                                └──▶ Adjustment Generator

STEP 9: FEEDBACK
───────────────
Adjustments ──▶ Feedback Injector ──▶ signal_weights_gate.json
                                    └──▶ signal_policies.json
                                    └──▶ configs/

STEP 10: LOOP BACK
──────────────────
Updated Weights/Configs ──▶ Conviction Gate (next trade) ──▶ STEP 4
```

---

## 4. Worker Process Architecture

### 4.1 Worker Process Map

```
┌─────────────────────────────────────────────────────────────┐
│              WORKER PROCESSES (src/run.py)                  │
└─────────────────────────────────────────────────────────────┘

Main Process (bot_worker)
│
├──▶ Worker 1: Predictive Engine
│   └──▶ Function: _worker_predictive_engine()
│   └──▶ Output: logs/predictive_signals.jsonl
│   └──▶ Restart: Yes (on crash)
│
├──▶ Worker 2: Feature Builder
│   └──▶ Function: _worker_feature_builder()
│   └──▶ Output: feature_store/features_*.json
│   └──▶ Restart: Yes (on crash)
│
├──▶ Worker 3: Ensemble Predictor
│   └──▶ Function: _worker_ensemble_predictor()
│   └──▶ Output: logs/ensemble_predictions.jsonl
│   └──▶ Restart: Yes (on crash)
│   └──▶ STATUS: ❌ NOT RUNNING (needs diagnosis)
│
├──▶ Worker 4: Signal Resolver
│   └──▶ Function: _worker_signal_resolver()
│   └──▶ Output: feature_store/pending_signals.json
│   └──▶ Restart: Yes (on crash)
│
└──▶ Worker Monitor Thread
    └──▶ Function: _monitor_worker_processes()
    └──▶ Purpose: Restart crashed workers
    └──▶ Interval: Continuous monitoring
```

### 4.2 Worker Startup Sequence

```
1. bot_worker() called
   │
2. _start_all_worker_processes() called
   │
3. For each worker:
   │
   ├──▶ _start_worker_process(name, target_func)
   │   │
   │   ├──▶ Create Process object
   │   ├──▶ Start process
   │   ├──▶ Register in _worker_processes dict
   │   └──▶ Log startup message
   │
4. Worker Monitor Thread started
   │
5. Workers run independently
   │
6. If worker crashes:
   │
   └──▶ Monitor detects crash
       └──▶ Restart worker (if restart_on_crash=True)
```

---

## 5. Learning Loop Architecture

### 5.1 Learning Cycle Flow

```
┌─────────────────────────────────────────────────────────────┐
│              LEARNING CYCLE (Every 12 Hours)                │
└─────────────────────────────────────────────────────────────┘

TRIGGER: Continuous Learning Controller
│
├──▶ STEP 1: Capture Outcomes
│   │
│   ├──▶ Load Executed Trades (last 168 hours)
│   ├──▶ Load Blocked Signals (last 168 hours)
│   ├──▶ Load Missed Opportunities (last 168 hours)
│   └──▶ Load Counterfactual Outcomes
│
├──▶ STEP 2: Analyze Profitability
│   │
│   ├──▶ Profitability Analyzer
│   │   ├──▶ Calculate P&L by direction (LONG/SHORT)
│   │   ├──▶ Calculate P&L by strategy (OFI/Sentiment)
│   │   ├──▶ Calculate P&L by regime
│   │   ├──▶ Calculate win rates
│   │   └──▶ Identify patterns
│   │
│   └──▶ Output: profitability_metrics
│
├──▶ STEP 3: Generate Adjustments
│   │
│   ├──▶ Adjustment Generator
│   │   ├──▶ Update Signal Weights
│   │   ├──▶ Update OFI Thresholds
│   │   ├──▶ Update Sizing Rules
│   │   └──▶ Update Timing Rules
│   │
│   └──▶ Output: adjustments[]
│
├──▶ STEP 4: Apply Adjustments
│   │
│   ├──▶ Feedback Injector
│   │   ├──▶ Update signal_weights_gate.json
│   │   ├──▶ Update signal_policies.json
│   │   ├──▶ Update configs/
│   │   └──▶ Log changes
│   │
│   └──▶ Output: applied_adjustments[]
│
└──▶ STEP 5: Wait for Next Cycle (12 hours)
```

### 5.2 Learning Components

| Component | File | Purpose | Frequency |
|-----------|------|---------|-----------|
| Continuous Learning Controller | `src/continuous_learning_controller.py` | Orchestrates learning | Every 12h |
| Signal Weight Learner | `src/signal_weight_learner.py` | Updates signal weights | Every 12h |
| Profitability Analyzer | `src/profitability_analyzer.py` | Analyzes outcomes | Every 12h |
| Data Enrichment Layer | `src/data_enrichment_layer.py` | Enriches signals | Continuous |
| Feedback Injector | `src/continuous_learning_controller.py` | Applies adjustments | Every 12h |

---

## 6. File System Map

### 6.1 Data Files Structure

```
trading-bot/
│
├── logs/
│   ├── predictive_signals.jsonl          # Raw predictive signals
│   ├── ensemble_predictions.jsonl        # Ensemble predictions
│   ├── signal_outcomes.jsonl             # Signal outcome tracking
│   ├── positions_futures.json           # Open/closed positions
│   ├── conviction_gate.jsonl            # Conviction gate decisions
│   └── trading_frozen.flag               # Trading freeze flag
│
├── feature_store/
│   ├── pending_signals.json              # Pending signal queue
│   ├── signals_universe.jsonl            # All signals (executed + blocked)
│   ├── enriched_decisions.jsonl          # Signals + outcomes
│   ├── signal_weights_gate.json         # Learned signal weights
│   ├── daily_learning_rules.json        # Daily learning rules
│   └── learning_state.json               # Learning controller state
│
├── configs/
│   ├── signal_policies.json              # Signal validation policies
│   │   ├── long_ofi_requirement: 0.5
│   │   ├── short_ofi_requirement: 0.5
│   │   └── ...other policies
│   └── ...other configs
│
└── src/
    ├── run.py                            # Main entry point
    ├── conviction_gate.py                # Trade validation
    ├── signal_outcome_tracker.py          # Signal tracking
    ├── continuous_learning_controller.py  # Learning orchestrator
    └── ...other modules
```

### 6.2 File Flow Map

```
INPUT FILES (Read Only)
───────────────────────
configs/signal_policies.json ──▶ Conviction Gate
feature_store/signal_weights_gate.json ──▶ Conviction Gate

OUTPUT FILES (Written)
──────────────────────
logs/predictive_signals.jsonl ◀─── Predictive Engine
logs/ensemble_predictions.jsonl ◀─── Ensemble Predictor
feature_store/pending_signals.json ◀─── Signal Resolver
logs/positions_futures.json ◀─── Portfolio Tracker
logs/signal_outcomes.jsonl ◀─── Signal Outcome Tracker

FEEDBACK FILES (Updated by Learning)
────────────────────────────────────
feature_store/signal_weights_gate.json ◀─── Signal Weight Learner
configs/signal_policies.json ◀─── Feedback Injector
feature_store/daily_learning_rules.json ◀─── Learning Controller
```

---

## 7. Component Dependencies

### 7.1 Dependency Graph

```
run.py (Main Entry)
│
├──▶ bot_worker()
│   │
│   ├──▶ _start_all_worker_processes()
│   │   │
│   │   ├──▶ _worker_predictive_engine()
│   │   │   └──▶ predictive_flow_engine.py
│   │   │
│   │   ├──▶ _worker_ensemble_predictor()
│   │   │   └──▶ ensemble_predictor.py
│   │   │       └──▶ predictive_signals.jsonl (reads)
│   │   │
│   │   └──▶ _worker_signal_resolver()
│   │       └──▶ signal_outcome_tracker.py
│   │
│   └──▶ ContinuousLearningController()
│       └──▶ continuous_learning_controller.py
│           ├──▶ signal_weight_learner.py
│           ├──▶ profitability_analyzer.py
│           └──▶ data_enrichment_layer.py
│
└──▶ bot_cycle()
    └──▶ conviction_gate.py
        ├──▶ signal_weights_gate.json (reads)
        └──▶ signal_policies.json (reads)
```

### 7.2 Critical Dependencies

| Component | Depends On | Purpose |
|-----------|------------|---------|
| Conviction Gate | `signal_weights_gate.json` | Uses learned weights |
| Conviction Gate | `signal_policies.json` | Uses OFI thresholds |
| Ensemble Predictor | `predictive_signals.jsonl` | Reads input signals |
| Signal Resolver | `pending_signals.json` | Processes pending queue |
| Learning Controller | `enriched_decisions.jsonl` | Analyzes outcomes |
| Learning Controller | `positions_futures.json` | Gets trade data |

---

## 8. Signal Flow Diagram

### 8.1 Complete Signal Journey

```
┌─────────────────────────────────────────────────────────────┐
│                    SIGNAL LIFECYCLE                          │
└─────────────────────────────────────────────────────────────┘

1. GENERATION
   ┌──────────────┐
   │ Market Data  │
   └──────┬───────┘
          │
          ▼
   ┌──────────────┐
   │ Predictive   │───▶ predictive_signals.jsonl
   │ Engine       │
   └──────┬───────┘
          │
          ▼
   ┌──────────────┐
   │ Ensemble     │───▶ ensemble_predictions.jsonl
   │ Predictor    │
   └──────┬───────┘

2. LOGGING
          │
          ▼
   ┌──────────────┐
   │ Signal       │───▶ pending_signals.json
   │ Tracker      │───▶ signals_universe.jsonl
   └──────┬───────┘

3. VALIDATION
          │
          ▼
   ┌──────────────┐
   │ Conviction   │
   │ Gate         │
   │              │
   │ Checks:      │
   │ - OFI ≥ 0.5  │
   │ - Fees       │
   │ - Correlation│
   │ - Intelligence│
   └──────┬───────┘
          │
          ├──▶ should_trade = True ──▶ EXECUTE
          │
          └──▶ should_trade = False ──▶ BLOCK

4. EXECUTION (if should_trade = True)
          │
          ▼
   ┌──────────────┐
   │ Trade        │───▶ positions_futures.json
   │ Executor     │
   └──────┬───────┘

5. OUTCOME TRACKING
          │
          ▼
   ┌──────────────┐
   │ Portfolio    │───▶ Closed Position
   │ Tracker      │
   └──────┬───────┘
          │
          ▼
   ┌──────────────┐
   │ Signal       │───▶ signal_outcomes.jsonl
   │ Outcome      │
   │ Tracker      │
   └──────┬───────┘

6. LEARNING
          │
          ▼
   ┌──────────────┐
   │ Data         │───▶ enriched_decisions.jsonl
   │ Enrichment   │
   └──────┬───────┘
          │
          ▼
   ┌──────────────┐
   │ Learning     │───▶ Updates weights/policies
   │ Controller   │
   └──────┬───────┘

7. FEEDBACK (Loop Back)
          │
          ▼
   ┌──────────────┐
   │ Updated      │───▶ Next Signal Uses
   │ Weights/     │    Updated Rules
   │ Policies     │
   └──────────────┘
```

---

## 9. Trade Execution Flow

### 9.1 Trade Decision Process

```
Signal Arrives
│
├──▶ Conviction Gate
│   │
│   ├──▶ Load Learned Weights
│   │   └──▶ signal_weights_gate.json
│   │
│   ├──▶ Load Policies
│   │   └──▶ signal_policies.json
│   │       ├──▶ long_ofi_requirement: 0.5
│   │       └──▶ short_ofi_requirement: 0.5
│   │
│   ├──▶ Calculate Signal Score
│   │   └──▶ Uses learned weights
│   │
│   ├──▶ Check OFI Threshold
│   │   ├──▶ If LONG: abs(ofi) ≥ 0.5?
│   │   └──▶ If SHORT: abs(ofi) ≥ 0.5?
│   │
│   ├──▶ Check Fee Gate
│   ├──▶ Check Correlation Throttle
│   ├──▶ Check Intelligence Gate
│   └──▶ Check Pre-Entry Gate
│
├──▶ Decision
│   │
│   ├──▶ should_trade = True
│   │   └──▶ Calculate Position Size
│   │       └──▶ Execute Trade
│   │
│   └──▶ should_trade = False
│       └──▶ Log Blocked Signal
│
└──▶ Outcome Tracking
    └──▶ Log to signal_outcomes.jsonl
```

---

## 10. Learning Feedback Loop

### 10.1 Complete Feedback Cycle

```
┌─────────────────────────────────────────────────────────────┐
│              LEARNING FEEDBACK LOOP                          │
└─────────────────────────────────────────────────────────────┘

TRADES EXECUTE
│
├──▶ Outcomes Captured
│   └──▶ positions_futures.json
│
├──▶ Signals Enriched
│   └──▶ enriched_decisions.jsonl
│
├──▶ Learning Cycle Runs (Every 12h)
│   │
│   ├──▶ Profitability Analyzed
│   │   └──▶ Patterns Identified
│   │       Example: "LONG trades with OFI < 0.5 lose money"
│   │
│   ├──▶ Adjustments Generated
│   │   └──▶ Example: "Set long_ofi_requirement = 0.5"
│   │
│   └──▶ Adjustments Applied
│       │
│       ├──▶ signal_weights_gate.json updated
│       ├──▶ signal_policies.json updated
│       └──▶ Configs updated
│
└──▶ NEXT TRADE USES UPDATED RULES
    │
    └──▶ Conviction Gate loads updated weights/policies
        └──▶ Better decisions made
            └──▶ Better outcomes
                └──▶ Loop continues
```

---

## 11. Troubleshooting Map

### 11.1 Common Issues and Where to Look

| Issue | Component | File to Check | Fix |
|-------|-----------|---------------|-----|
| Signals not generating | Predictive Engine | `logs/predictive_signals.jsonl` | Check worker process |
| Ensemble not updating | Ensemble Predictor | `logs/ensemble_predictions.jsonl` | Restart worker |
| Trades not executing | Conviction Gate | `logs/conviction_gate.jsonl` | Check should_trade logic |
| Learning not running | Learning Controller | `feature_store/learning_state.json` | Check cycle timing |
| Weights not updating | Signal Weight Learner | `feature_store/signal_weights_gate.json` | Check learning cycle |
| OFI threshold not enforced | Conviction Gate | `src/conviction_gate.py` | Check should_trade logic |

---

## 12. Best Practices

### 12.1 SDLC Principles Applied

1. **Separation of Concerns**
   - Signal generation separate from execution
   - Learning separate from trading
   - Workers isolated in separate processes

2. **Single Responsibility**
   - Each component has one clear purpose
   - Conviction Gate: validation only
   - Learning Controller: learning only

3. **Data-Driven Decisions**
   - All decisions based on data files
   - No hardcoded business logic
   - Configurable thresholds

4. **Observability**
   - All actions logged to files
   - Outcome tracking for every signal
   - Learning state persisted

5. **Fail-Safe Design**
   - Workers restart on crash
   - Health monitoring
   - Trading freeze mechanism

---

## 13. Quick Reference

### 13.1 Key Files

| File | Purpose | Updated By |
|------|---------|-------------|
| `logs/predictive_signals.jsonl` | Raw signals | Predictive Engine |
| `logs/ensemble_predictions.jsonl` | Ensemble predictions | Ensemble Predictor |
| `feature_store/pending_signals.json` | Pending queue | Signal Resolver |
| `logs/positions_futures.json` | Trade data | Portfolio Tracker |
| `feature_store/signal_weights_gate.json` | Learned weights | Signal Weight Learner |
| `configs/signal_policies.json` | Policies | Feedback Injector |

### 13.2 Key Components

| Component | File | Purpose |
|-----------|------|---------|
| Main Entry | `src/run.py` | Orchestrates everything |
| Signal Validation | `src/conviction_gate.py` | Validates trades |
| Learning Orchestrator | `src/continuous_learning_controller.py` | Coordinates learning |
| Signal Tracking | `src/signal_outcome_tracker.py` | Tracks outcomes |
| Trade Tracking | `src/futures_portfolio_tracker.py` | Tracks positions |

---

**Last Updated:** December 22, 2025  
**Version:** 1.0
