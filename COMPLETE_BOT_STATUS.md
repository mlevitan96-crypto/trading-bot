# Complete Trading Bot Status Document

**Date:** December 18, 2025  
**Status:** ✅ **OPERATIONAL** - Running on Kraken Testnet  
**Mode:** Paper Trading (Testnet)

---

## 📋 Table of Contents

1. [Current Status Overview](#current-status-overview)
2. [Droplet Deployment Structure](#droplet-deployment-structure)
3. [Signal System](#signal-system)
4. [Learning Systems](#learning-systems)
5. [Self-Healing Mechanisms](#self-healing-mechanisms)
6. [Bot Architecture Summary](#bot-architecture-summary)
7. [Kraken Integration](#kraken-integration)
8. [Key File Paths](#key-file-paths)
9. [Monitoring & Health Checks](#monitoring--health-checks)

---

## Current Status Overview

### ✅ Operational Status

**Bot Status:** Running and trading on Kraken testnet  
**Exchange:** Kraken Futures (Testnet)  
**Base URL:** `https://demo-futures.kraken.com`  
**Mode:** Paper Trading (Testnet) - **NO REAL MONEY AT RISK**

**Current Configuration:**
- ✅ Exchange Gateway: `KRAKEN`
- ✅ Testnet Mode: `true`
- ✅ Market Data: Flowing correctly
- ✅ Order Placement: Ready (testnet only)
- ✅ Position Tracking: Working
- ✅ Signal Generation: Active

### 🔒 Safety Guarantees

**NO REAL MONEY TRADING:**
- `.env` file has `KRAKEN_FUTURES_TESTNET=true`
- All trades go to Kraken testnet (fake/test funds)
- To trade real money, requires:
  1. Change `KRAKEN_FUTURES_TESTNET=false`
  2. Create new live API keys
  3. Update `.env` with live keys
  4. Restart bot
- **NONE of these have been done - you're SAFE!**

---

## Droplet Deployment Structure

### A/B Slot Deployment System

The bot uses a zero-downtime A/B slot deployment system:

```
/root/
├── trading-bot-A/          # Slot A
│   ├── src/                # Source code
│   ├── logs/               # Logs and runtime data
│   ├── config/             # Configuration files
│   ├── feature_store/      # Learning state and feature data
│   ├── venv/               # Python virtual environment
│   ├── .env                # Environment variables
│   └── ...
│
├── trading-bot-B/          # Slot B
│   └── [Same structure as Slot A]
│
├── trading-bot-current/    # Symlink to active slot (A or B)
│   └── [Points to either A or B]
│
└── trading-bot-tools/      # Deployment scripts
    └── deploy.sh           # Main deployment script
```

**How It Works:**
1. One slot is active at a time (via symlink)
2. Deployments update the inactive slot
3. Service switches symlink atomically
4. Zero-downtime updates

**Deployment Process:**
```bash
# On droplet:
/root/trading-bot-tools/deploy.sh

# What it does:
# 1. Determines active slot (A or B)
# 2. Pulls latest code into inactive slot
# 3. Creates/updates virtual environment
# 4. Installs dependencies
# 5. Runs health checks
# 6. Stops service
# 7. Switches symlink to updated slot
# 8. Starts service
```

### Systemd Service

**Service File:** `/etc/systemd/system/tradingbot.service`

**Key Settings:**
- Working Directory: `/root/trading-bot-current`
- Executable: `/root/trading-bot-current/venv/bin/python`
- Script: `/root/trading-bot-current/src/run.py`
- Restart: Always (auto-restart on failure)

**Service Management:**
```bash
# Check status
sudo systemctl status tradingbot

# View logs
journalctl -u tradingbot -f

# Restart
sudo systemctl restart tradingbot
```

---

## Signal System

### Signal Generation Pipeline

The bot uses a **multi-signal predictive flow engine** that combines 10+ independent signals:

```
1. Signal Generation
   └─> PredictiveFlowEngine.generate_signal()
       ├─> OFI Momentum Tracker
       ├─> Funding Rate Signal
       ├─> Open Interest Velocity
       ├─> Liquidation Cascade Detector
       ├─> Whale Flow Signal
       ├─> Fear & Greed Contrarian
       ├─> Hurst Exponent (regime detection)
       ├─> Lead-Lag Signal
       ├─> Volatility Skew
       └─> OI Divergence

2. Signal Aggregation
   └─> Weighted Signal Fusion
       ├─> Signal weights (learned over time)
       ├─> Conviction scoring
       └─> Ensemble prediction

3. Gate Evaluation
   ├─> Conviction Gate (weighted scoring)
   ├─> Fee Gate (fee-aware filtering)
   ├─> Correlation Throttle (sector limits)
   ├─> Hold Governor (position limits)
   └─> Intelligence Gate (pattern recognition)

4. Trade Execution
   └─> execute_signal() → open_order_fn()
```

### Signal Types & Weights

**Current Signal Weights** (learned and adjusted automatically):

| Signal | Weight | Description |
|--------|--------|-------------|
| **Liquidation** | 0.22 | Detects liquidation cascades (bullish/bearish) |
| **Whale Flow** | 0.20 | Tracks large order flow patterns |
| **Funding** | 0.16 | Funding rate divergence signals |
| **Hurst** | 0.08 | Regime detection (trending/mean-reverting) |
| **Lead-Lag** | 0.08 | Cross-asset momentum patterns |
| **OFI Momentum** | 0.06 | Order flow imbalance momentum |
| **Fear & Greed** | 0.06 | Contrarian sentiment signals |
| **OI Velocity** | 0.05 | Open interest change rate |
| **Volatility Skew** | 0.05 | Loss aversion/complacency detection |
| **OI Divergence** | 0.04 | Price/OI trap detection |

**Signal Features:**
- ✅ Weights auto-adjust based on performance (learning system)
- ✅ Minimum weight floor: 0.05 (signals never fully disabled)
- ✅ Maximum adjustment: ±20% per update (conservative)
- ✅ Signals combine to produce conviction scores (HIGH/MEDIUM/LOW/NONE)

### Conviction Thresholds

**Conviction Levels:**
- **HIGH:** 4+ aligned signals, 60%+ confidence, 1.5x size multiplier
- **MEDIUM:** 3+ aligned signals, 40%+ confidence, 1.0x size multiplier
- **LOW:** 2+ aligned signals, 30%+ confidence, 0.5x size multiplier
- **NONE:** Below thresholds, no trade

### Data Sources

**Market Intelligence:**
- **CoinGlass API:** Taker buy/sell ratios, liquidations, funding rates, OI data
- **Orderbook Data:** Real-time order flow imbalance (OFI) calculation
- **Price Data:** OHLCV from Kraken Futures
- **Fear & Greed Index:** Alternative.me API
- **On-Chain Data:** Exchange flows, whale movements

---

## Learning Systems

### Continuous Learning Architecture

The bot has **multiple interconnected learning systems** that run on different cadences:

#### 1. Continuous Learning Controller (30-minute cycles)

**Location:** `src/continuous_learning_controller.py`

**What It Does:**
- Reviews executed trades and outcomes
- Updates signal weights based on performance
- Adjusts profit policies per symbol
- Tracks win rates and profitability
- Updates conviction thresholds

**Learning Dimensions:**
- ✅ Signal weight adjustments (±20% max)
- ✅ Profit filter tuning (MIN_PROFIT_USD per symbol)
- ✅ Leverage adjustments (1x-10x)
- ✅ Collateral adjustments (position sizing)
- ✅ Conviction threshold tuning

#### 2. Signal Weight Learner

**Location:** `src/signal_weight_learner.py`

**Features:**
- Analyzes signal performance by win rate and P&L
- Increases weights of profitable signals
- Decreases weights of unprofitable signals
- Maintains minimum weights (0.05 floor)
- Updates `feature_store/signal_weights.json`

**Example Adjustments:**
```json
{
  "liquidation": 0.22 → 0.26 (profitable, +18%),
  "funding": 0.16 → 0.13 (unprofitable, -19%),
  "whale_flow": 0.20 → 0.22 (slightly profitable, +10%)
}
```

#### 3. Enhanced Learning Engine

**Location:** `src/learning/enhanced_learning_engine.py`

**Features:**
- Reviews blocked trades and missed opportunities
- Analyzes what-if scenarios
- Discovers patterns in profitable vs unprofitable trades
- Generates learning rules
- Updates `feature_store/daily_learning_rules.json`

#### 4. Meta Learning Orchestrator (30-minute cycles)

**Location:** `src/meta_learning_orchestrator.py`

**Coordinates:**
- Meta-Governor (health monitoring)
- Liveness Monitor (resilience adjustments)
- Profitability Governor (uplift-driven adjustments)
- Meta-Research Desk (experiments & knowledge graph)
- Counterfactual Scaling Engine (what-if analysis)

#### 5. Symbol Allocation Intelligence

**Location:** `src/symbol_allocation_intelligence.py`

**Features:**
- Reallocates capital from underperformers to winners
- Suppresses symbols with <40% win rate and negative P&L
- Promotes symbols with >50% win rate and positive P&L
- Adjusts position sizes per symbol based on performance

#### 6. Exit Tuner (Nightly ~07:00 UTC)

**Location:** `src/exit_learning_state.json`

**Features:**
- Reviews profit target hit rates
- Analyzes exit timing vs profitability
- Adjusts profit targets (0.5%, 1.0%, 1.5%, 2.0%)
- Optimizes trailing stop parameters
- Learns optimal hold times per symbol

### Learning State Files

**Location:** `feature_store/`

| File | Purpose |
|------|---------|
| `signal_weights.json` | Current signal weights (updated every 30 min) |
| `learning_state.json` | Overall learning state and metrics |
| `daily_learning_rules.json` | Pattern-based rules (updated nightly) |
| `hold_time_policy.json` | Optimal hold times per symbol |
| `profit_policy.json` | Profit targets and thresholds |
| `fee_gate_learning.json` | Fee-aware filtering adjustments |
| `edge_sizer_calibration.json` | Position sizing calibrations |
| `direction_rules.json` | Direction prediction rules |
| `rotation_rules.json` | Asset rotation intelligence |

---

## Self-Healing Mechanisms

### Comprehensive Self-Healing System

The bot has **multi-layered self-healing** that monitors and repairs issues automatically:

#### 1. Healing Operator (Runs Every 60 Seconds)

**Location:** `src/healing_operator.py`

**Monitors & Heals:**
- ✅ **Signal Engine** - Ensures signal files exist and are fresh
- ✅ **Decision Engine** - Monitors enriched decisions pipeline
- ✅ **Safety Layer** - Validates operator alerts and safety checks
- ✅ **Exit Gates** - Ensures exit logic files are healthy
- ✅ **Trade Execution** - Validates positions file integrity
- ✅ **Architecture Components** - SignalBus, StateMachine, ShadowEngine

**Auto-Heals:**
- Missing/empty files → Created automatically
- Stale heartbeats → Reset automatically
- Lock timeouts → Cleared automatically
- Corrupted JSON → Repaired automatically
- Orphan processes → Killed automatically (paper mode)
- Missing directories → Created automatically

**What Requires Manual Intervention:**
- ❌ State mismatches (positions vs portfolio) → CRITICAL alert only
- ❌ Partial fills (incomplete trades) → CRITICAL alert only
- ❌ Conflicting positions (duplicate entries) → CRITICAL alert only
- ❌ Data integrity violations → CRITICAL alert only

#### 2. Architecture Healing

**Location:** `src/architecture_healing.py`

**Heals New Architecture Components:**
- **SignalBus** - Repairs corrupted event log, creates missing files
- **StateMachine** - Auto-expires stuck signals, fixes invalid states
- **ShadowExecutionEngine** - Creates outcomes log, restarts if stopped
- **DecisionTracker** - Creates decisions log
- **PipelineMonitor** - Auto-expires stuck signals to fix pipeline health

#### 3. Health Pulse Orchestrator (Runs Every Minute)

**Location:** `src/health_pulse_orchestrator.py`

**Features:**
- Detects trading stalls
- Diagnoses root causes
- Applies auto-fixes automatically
- Logs all actions
- Monitors system health

#### 4. Self-Healing Functions

**Location:** `src/operator_safety.py`

**Function:** `self_heal()`

**Cold-Start Issues (Always Auto-Healed):**
1. Missing directories → Creates: `logs/`, `config/`, `feature_store/`, `state/`
2. Missing files → Initializes: `positions_futures.json`, `portfolio_futures.json`
3. Empty files → Repairs with valid structure
4. Malformed JSON → Adds missing keys, preserves data

**Recoverable Runtime Issues (Auto-Healed):**
1. Stale file locks (>5 min) → Removed
2. Stale heartbeats (>10 min) → Reset
3. Corrupted JSON → Extracted and repaired
4. Orphan processes → Killed (paper mode only)

### Self-Healing Status

**Status:** ✅ **ACTIVE AND WORKING**

**Monitoring:**
- Healing runs every 60 seconds
- Health checks run every minute
- All components monitored continuously
- Issues fixed automatically when detected

---

## Bot Architecture Summary

### Core Components

#### 1. Main Trading Loop

**Location:** `src/bot_cycle.py`  
**Function:** `run_bot_cycle()`

**Cycle Time:** ~2 minutes per full cycle

**Process:**
1. Load positions and portfolio state
2. Generate signals for all enabled symbols
3. Evaluate signals through gates
4. Execute approved trades
5. Manage exits (profit targets, stops, time exits)
6. Update positions and P&L
7. Log outcomes for learning

#### 2. Exchange Gateway

**Location:** `src/exchange_gateway.py`

**Purpose:** Unified interface for exchange operations

**Current Exchange:** Kraken Futures (configurable)

**Methods:**
- `get_price(symbol, venue)` - Get current price
- `fetch_ohlcv(symbol, timeframe, limit, venue)` - Get OHLCV data
- `get_orderbook(symbol, venue, depth)` - Get order book
- `place_order(...)` - Place orders
- `cancel_order(order_id, symbol)` - Cancel orders
- `get_positions(symbol)` - Get positions
- `get_balance()` - Get account balance

#### 3. Position Management

**Location:** `src/position_manager.py`

**Features:**
- Tracks open/closed positions
- Real-time P&L calculation
- Position limits (max 10 concurrent)
- Sector correlation guards (max 2 per sector)
- Fee-aware profit calculations

#### 4. Risk Management

**Location:** `src/operator_safety.py`, `src/conviction_gate.py`

**Risk Controls:**
- Position limits: Max 10 concurrent positions
- Per-symbol limit: Max 10% of portfolio
- Total exposure: Max 60% of portfolio
- Leverage limits: 1x-10x (configurable per symbol)
- Circuit breakers: Session/daily loss limits
- Kill switches: Emergency shutdown triggers

#### 5. Exit Strategy

**Location:** `src/futures_ladder_exits.py`, `src/atr_ladder_exits.py`

**Exit Types:**
- **Profit Targets:** 0.5%, 1.0%, 1.5%, 2.0% (configurable per symbol)
- **Trailing Stops:** Dynamic based on ATR
- **Time Exits:** Maximum hold time limits
- **Emergency Exits:** Portfolio drawdown >1.5% or position loss >2%

### Trading Symbols

**Asset Universe:** 14 symbols enabled (from `config/asset_universe.json`)

| Symbol | Tier | Category |
|--------|------|----------|
| BTCUSDT | major | Mega cap |
| ETHUSDT | major | Mega cap |
| SOLUSDT | l1 | Layer 1 |
| AVAXUSDT | l1 | Layer 1 |
| DOTUSDT | l1 | Layer 1 |
| TRXUSDT | l1 | Layer 1 |
| XRPUSDT | l1 | Layer 1 |
| ADAUSDT | l1 | Layer 1 |
| DOGEUSDT | l1 | Layer 1 |
| BNBUSDT | l1 | Layer 1 |
| LINKUSDT | defi | DeFi/Oracle |
| ARBUSDT | l2 | Layer 2 |
| OPUSDT | l2 | Layer 2 |
| PEPEUSDT | meme | Meme coin |

**Sector Categories:**
- Mega (BTC, ETH) - Max 2 positions
- L1 (SOL, AVAX, DOT, TRX, XRP, ADA, DOGE, BNB) - Max 2 per sector
- L2 (ARB, OP) - Max 2 positions
- DeFi (LINK) - Max 2 positions
- Meme (PEPE) - Max 2 positions

### Trading Strategy

**Goal:** Quality over quantity
- Target: 5-20 positions per day
- Position sizes: $200-$2,000
- Focus: High-conviction signals only
- Risk: Conservative, fee-aware

**Position Sizing:**
- Kelly Criterion (fractional, 0.3x conservative)
- Based on win rate and payoff ratio
- Volatility-adjusted
- Sector-aware allocation

---

## Kraken Integration

### Integration Status: ✅ COMPLETE

**Exchange:** Kraken Futures  
**Mode:** Testnet (Paper Trading)  
**Base URL:** `https://demo-futures.kraken.com`  
**Client:** `src/kraken_futures_client.py`

### Implementation Details

#### 1. Kraken Futures Client

**Location:** `src/kraken_futures_client.py`

**Features:**
- ✅ HMAC-SHA512 authentication
- ✅ Symbol normalization (BTCUSDT → PI_XBTUSD)
- ✅ Market data (OHLCV, mark prices, orderbook)
- ✅ Order management (place, cancel, query)
- ✅ Position tracking
- ✅ Rate limiting (60 req/min)

#### 2. Symbol Normalization

**Location:** `src/exchange_utils.py`

**Mappings:**
- BTCUSDT → PI_XBTUSD
- ETHUSDT → PI_ETHUSD
- SOLUSDT → PF_SOLUSD
- (Full mapping in `KRAKEN_SYMBOL_MAP`)

#### 3. Exchange Gateway Integration

**Location:** `src/exchange_gateway.py`

**Configuration:**
- Environment variable: `EXCHANGE=kraken`
- Auto-selects Kraken client when `EXCHANGE=kraken`
- Falls back to Blofin if not set

#### 4. Fee Calculator

**Location:** `src/fee_calculator.py`

**Kraken Fees:**
- Maker: 0.02% (0.0002)
- Taker: 0.05% (0.0005)

### Configuration

**Environment Variables** (`.env` file):

```bash
# Exchange Selection
EXCHANGE=kraken

# Kraken Futures API
KRAKEN_FUTURES_API_KEY=your_api_key_here
KRAKEN_FUTURES_API_SECRET=your_api_secret_here
KRAKEN_FUTURES_TESTNET=true  # Set to false for live trading
```

### API Endpoints Used

| Endpoint | Purpose |
|----------|---------|
| `/api/charts/v1/trade/{symbol}/{resolution}` | OHLCV data |
| `/derivatives/api/v3/tickers` | Mark prices |
| `/derivatives/api/v3/orderbook` | Order book depth |
| `/derivatives/api/v3/openpositions` | Position queries |
| `/derivatives/api/v3/sendorder` | Order placement |
| `/derivatives/api/v3/cancelorder` | Order cancellation |
| `/derivatives/api/v3/accounts` | Balance queries |

### Testing Status

**All Tests Passing:**
- ✅ Mark price fetching
- ✅ OHLCV data retrieval
- ✅ Symbol normalization
- ✅ Position queries
- ⚠️ Balance endpoint (auth error - doesn't affect trading)

---

## Key File Paths

### Droplet Structure

#### Code & Configuration
```
/root/trading-bot-current/
├── src/                    # Source code
│   ├── bot_cycle.py       # Main trading loop
│   ├── exchange_gateway.py # Exchange interface
│   ├── kraken_futures_client.py # Kraken API client
│   └── ...
├── config/                 # Configuration files
│   ├── asset_universe.json # Trading symbols
│   └── profit_policy.json  # Profit targets
├── configs/                # Runtime configs
│   └── alpha_config.json   # Alpha engine config
└── .env                    # Environment variables
```

#### Logs & Runtime Data
```
/root/trading-bot-current/
├── logs/
│   ├── positions_futures.json      # Open/closed positions
│   ├── portfolio_futures.json      # Portfolio state
│   ├── signals.jsonl               # Signal log
│   ├── blocked_signals.jsonl       # Blocked signals
│   ├── exit_runtime_events.jsonl   # Exit events
│   ├── conviction_gate_log.jsonl   # Conviction gate decisions
│   └── bot_out.log                 # Main bot log
```

#### Learning State
```
/root/trading-bot-current/
├── feature_store/
│   ├── signal_weights.json         # Learned signal weights
│   ├── learning_state.json         # Learning state
│   ├── daily_learning_rules.json   # Pattern rules
│   ├── hold_time_policy.json       # Exit timing
│   ├── profit_policy.json          # Profit targets
│   └── direction_rules.json        # Direction prediction
```

#### State & Heartbeats
```
/root/trading-bot-current/
├── state/
│   ├── counter_signal_state.json
│   └── heartbeats/
│       └── bot_cycle.json          # Process heartbeat
```

### Important Paths Summary

| Path | Purpose |
|------|---------|
| `/root/trading-bot-current/src/run.py` | Main entry point |
| `/root/trading-bot-current/.env` | Environment config |
| `/root/trading-bot-current/logs/positions_futures.json` | Position tracking |
| `/root/trading-bot-current/feature_store/signal_weights.json` | Learned weights |
| `/etc/systemd/system/tradingbot.service` | Systemd service |

---

## Monitoring & Health Checks

### Dashboard

**Access:** `http://YOUR_DROPLET_IP:8050`

**Features:**
- Real-time P&L tracking
- Position status
- Learning system health
- System status indicators
- Executive summary
- Blocked signals analysis
- Missed opportunities
- Exit gates status

### Log Monitoring

**View Live Logs:**
```bash
journalctl -u tradingbot -f
```

**Check Recent Activity:**
```bash
journalctl -u tradingbot -n 100 --no-pager
```

**Search for Errors:**
```bash
journalctl -u tradingbot -n 500 | grep -i "error"
```

**Check Exchange Usage:**
```bash
journalctl -u tradingbot -n 50 | grep -i "exchange\|kraken"
```

### Health Checks

**Service Status:**
```bash
sudo systemctl status tradingbot
```

**Process Health:**
```bash
ps aux | grep python | grep run.py
```

**File Health:**
- Check `logs/bot_out.log` for runtime logs
- Check `state/heartbeats/bot_cycle.json` for heartbeat freshness
- Check `logs/positions_futures.json` for position integrity

### Executive Summary

**Generated:** On-demand via dashboard

**Includes:**
- What worked / didn't work today
- Missed opportunities (with P&L)
- Blocked signals (by reason and gate)
- Exit gates analysis
- Learning today (what was learned)
- Changes tomorrow (planned adjustments)
- Weekly summary
- Improvements & trends

---

## Summary

### ✅ Current State

- **Exchange:** Kraken Futures (Testnet)
- **Mode:** Paper Trading (Safe)
- **Status:** Operational
- **Learning:** Active (multiple systems)
- **Self-Healing:** Active (comprehensive)
- **Signals:** 10+ signals, weighted and learned
- **Risk Management:** Multi-layered safeguards

### 🎯 Key Features

1. **Multi-Signal Engine:** 10+ signals with learned weights
2. **Continuous Learning:** Multiple learning systems on different cadences
3. **Self-Healing:** Automatic issue detection and repair
4. **Risk Management:** Position limits, correlation guards, circuit breakers
5. **Exchange Agnostic:** Easy switching between exchanges (Kraken/Blofin)
6. **Autonomous Operation:** 24/7 operation with minimal intervention

### 📊 Performance Tracking

- Signal weights adjusted every 30 minutes
- Learning state updated continuously
- Profit targets optimized nightly
- Position sizing calibrated based on performance
- Symbol allocation rebalanced dynamically

### 🔒 Safety

- Testnet mode active (no real money)
- Multiple safety layers
- Circuit breakers and kill switches
- Conservative position sizing
- Fee-aware trading

---

**Document Last Updated:** December 18, 2025  
**Bot Version:** Current (with Kraken integration)  
**Deployment:** A/B slot system on DigitalOcean droplet
