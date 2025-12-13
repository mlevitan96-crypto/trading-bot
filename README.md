# Crypto Trading Bot

## Overview
This project is a multi-strategy cryptocurrency futures trading bot designed for autonomous 24/7 operation on the BloFin exchange. Its primary purpose is to achieve consistent profitability through sophisticated self-optimization, robust risk management, and fee-aware execution. The bot prioritizes quality trades over quantity, targeting 5-20 positions per day with sizes ranging from $200-$2,000. It is currently in PAPER TRADING mode for validation before live deployment, aiming for significant market potential through its advanced features.

## Current Status (Dec 11, 2025)
**Mode**: Paper Trading (Demo Account)
**Positions**: 10/10 open (all valid with proper timestamps)
**Total Closed Trades**: 1070
**Wallet Balance**: ~$9,900

### Recent Actions (Dec 11, 2025)
- Fixed Flask endpoint conflict (`api_open_positions_snapshot` duplicate) preventing bot startup
- Cleaned up zombie positions with corrupted null timestamps
- Bot now running with genuine OFI signals, real Kelly sizing, and sector correlation guards
- All positions have proper `direction` and `opened_at` fields

### Verification Status
Run `python verify_phase2_activity.py` for full pre-flight check:
| Test | Status | Details |
|------|--------|---------|
| Kelly Sizing Bootstrap | PASS | Returns 0.50% for 70% confidence |
| Sector Guard State | PASS | Consistent: 10 positions across 6 sectors |
| Alpha Signal Pulse | PASS | Engine initialized |
| OFI Data Outage | PASS | DATA_OUTAGE protection configured |
| Zombie Position Fix | PASS | Null timestamps allow immediate exit |
| Financial Integrity | WARN | Discrepancy from zombie cleanup |
| Operational Health | PASS | All gates open, circuit breaker active |

## User Preferences
- All changes in Python
- Detailed explanations required for code changes
- Ask before major architectural changes
- Validate changes before live deployment
- Autonomous 24/7 trading is critical - trading stalls are emergencies
- Strategic Advisor mindset: Proactively surface risks and opportunities
- No "inversion" terminology - signals indicate correct direction directly
- Quality over quantity in trade execution

## System Architecture

### UI/UX Decisions
The system includes a Flask P&L dashboard accessible on port 5000, offering real-time P&L tracking, position status, learning system health, and phase status indicators.

### Technical Implementations
The bot operates on a 60-second main loop, processing all enabled symbols. It features a sophisticated signal generation system with a 10-signal multi-factor engine (e.g., Liquidation Cascade, Funding Rate, OI Velocity) and a weighted signal aggregator for conviction scoring. Regime detection, based on the Hurst Exponent, dynamically filters strategies (e.g., Mean Reversion, Trending). Position sizing utilizes advanced methods like Kelly Sizing, Predictive Sizing (Half-Kelly + volatility scaling), and Profit-Seeking Sizing.

### Feature Specifications
-   **Trading Engine**: Orchestrates the main trading loop, handles signal processing, and executes fee-aware orders with regime filtering.
-   **Position Management**: Tracks open/closed positions, enforces sizing rules ($200-$2,000 range, Kelly-based allocation), and calculates real-time P&L with fee deductions. Includes NaN protection for all numeric operations.
-   **Trading Strategies**: Incorporates Active Strategies like Sentiment-Fusion (45% allocation), Trend-Conservative (35%), and Breakout-Aggressive (20%). These are governed by execution gates requiring multi-timeframe confirmation, minimum ROI, win rate thresholds, and streak filters.
-   **Risk Management**: Implements strict position limits (max 10 concurrent, 10% per symbol, 60% total futures exposure), dynamic exit logic (trailing stops, time exits, profit locks), and circuit breakers for session/daily loss limits, kill switches, and auto-recovery.
-   **Phase Architecture**: The system is modularized into several feature phases, including:
    -   **Phase 2 (Offensive Architecture)**: Introduces Hurst-based regime gating and predictive sizing.
    -   **Phase 7.x (Predictive Intelligence)**: Focuses on self-tuning execution, adaptive parameters, and outcome monitoring.
    -   **Phase 8.x (Full Autonomy)**: Implements self-healing watchdogs, edge compounding, and drift detection.
    -   **Phase 9.x (Autonomy Controller)**: Governs health scoring, capital scaling, and adaptive governance.
    -   **Phase 10.x (Profit Engine)**: Manages expectancy gates, attribution-weighted allocation, and adaptive risk.
-   **Learning System**: Features a Continuous Learning Controller (12-hour cycle) for adjusting signal weights and conviction thresholds, and a Daily Intelligence Learner for pattern discovery and validation. It incorporates feedback loops to track signal outcomes and automatically disable underperforming symbols.
-   **Self-Healing & Reliability**: Utilizes a supervisor script (`start_bot.sh`) for external watchdog functionality and auto-restarts. Health monitors track process heartbeats, memory usage, and data integrity. A Governance Sentinel monitors kill switches, heartbeats, and venue integrity.

### Forensic Audit Patches (Dec 10, 2025)
Implemented infrastructure hardening based on forensic audit:
-   **Betavariate Crash Protection** (`alpha_lab.py`): Thompson sampling bandit selector validates `a,b > 0` before calling `betavariate()`, preventing ValueError crashes during strategy optimization.
-   **Null-Safety Logic** (`alpha_to_execution_adapter.py`): Added `safe_float()` wrapper for risk_budget, confidence, and slippage values to prevent TypeError/NaN crashes in sizing calculations.
-   **Atomic Writes** (`accounting_sanity_guard.py`): JSON writes use tmp file + fsync + atomic rename pattern to prevent data corruption on system crashes.
-   **Memory-Safe Logging** (`adaptive_intelligence_learner.py`): Added MAX_LOG_ENTRIES=50000 limit enforced both on load and after each append to prevent OOM during long-running operations.

### Resilience Logic Patch (Dec 10, 2025)
Fixes for "Overnight Death Spiral" - bot no longer mistakes quiet markets for system failure:
-   **Synthetic Pulse Injection** (`phase80_coordinator.py`): Emits heartbeat every 20 seconds even when market is silent, telling the watchdog "I am still running".
-   **Soft-Fail Heartbeat Logic** (`phase80_coordinator.py`): Requires 3 consecutive heartbeat failures before triggering incident, filtering out brief network hiccups and Replit throttling.
-   **Null-Safe OFI Signals** (`alpha_signals_integration.py`): Uses `safe_float()` wrapper and defaults to "HOLD" when orderbook returns None, preventing TypeError crashes.
-   **Hold Time Deadlock Breaker** (`hold_time_enforcer.py`): Auto-bypasses minimum hold time when portfolio drawdown >1.5% OR position unrealized loss >2%, allowing emergency exits to free up position slots during market stress. Auto-computes metrics from positions file if not provided by caller.

### Phase 2 Forensic Audit Fixes (Dec 10, 2025)
Addresses "Phantom Architecture" issues - replacing simulated logic with real quantitative models:

**Problem Summary**: The bot was trading on "phantom" data - simulated arbitrage signals, linear sizing instead of Kelly, and no sector diversification. Additionally, 10 positions with corrupted null timestamps were "immortal" and blocked all trading capital.

**Fixes Applied**:
1. **OFI Data Outage Handling** (`alpha_signals_integration.py`):
   - Added 3-retry exponential backoff for orderbook fetch
   - Returns DATA_OUTAGE signal on failure instead of fake neutral data (100,100,0,0)
   - Trading is blocked when real orderbook data is unavailable

2. **Real Kelly Criterion Sizing** (`alpha_to_execution_adapter.py`):
   - Formula: `f* = p - (1-p)/b` where p=win_rate, b=payoff_ratio
   - Uses 0.3x fractional Kelly for conservative growth
   - Pulls metrics from rolling 50-trade strategy memory (`logs/strategy_memory.json`)
   - Falls back to conservative defaults (45% win rate, 1.2 payoff) when insufficient data

3. **Sector Correlation Guard** (`alpha_to_execution_adapter.py`):
   - 7 sector categories: mega, l1, l2, defi, meme, exchange, payment
   - MAX_POSITIONS_PER_SECTOR = 2 to prevent correlated blowups
   - Uses authoritative Tri-Layer position source (`load_futures_positions()`)

4. **Phantom Arbitrage Fix** (`alpha_signals_integration.py`):
   - Removed simulated `cross_venue_price = current_price + spread`
   - Without real secondary venue data, arb detection is disabled
   - Bot now relies on pure OFI (Order Flow Imbalance) signals

5. **Zombie Position Fix** (`hold_time_enforcer.py`):
   - Positions with null/missing entry_time treated as held for 1+ hours
   - Allows immediate exit instead of being immortal
   - Fixes the "10/10 saturation trap" where corrupted positions blocked all capital

### Verification Protocol
**File**: `verify_phase2_activity.py`
**Purpose**: Pre-flight checklist before trading. Tests all Phase 2 logic.
**Usage**: `python verify_phase2_activity.py`

**Tests Performed**:
1. **Kelly Bootstrap** - Verifies sizing returns non-zero for high confidence
2. **Sector Guards** - Checks position count matches sector tracking
3. **Alpha Pulse** - Confirms signal engine initializes
4. **OFI Outage** - Verifies DATA_OUTAGE protection exists
5. **Zombie Fix** - Tests null timestamps allow exit
6. **Financial Integrity** - Ledger reconciliation check
7. **Operational Health** - Gates, circuit breaker, log access

**Expected Result**: All tests PASS for green light to trade.

### Burn-In Protocol (Days 1-7)
The bot has transitioned from "Fragile Prototype" to "Hardened Quantitative System." It is now in **Burn-In Phase**.

**Expectations**:
- Bot will be MUCH quieter - "Real" logic filters out 90% of noise that "Phantom" logic was trading
- Kelly Criterion needs data to learn - starts with conservative defaults until 30+ trades

**Operational Rules**:
1. **No "Vibe Coding"** - Do not tweak parameters or loosen filters. The Adaptive Intelligence module needs 30 consistent data points to learn.
2. **Silence is Golden** - If bot doesn't trade for 12 hours, do NOT intervene. The OFI Filter blocks thin liquidity, Sector Guard blocks high correlation. Silence = saving money.
3. **Manual Intervention Only on Red Flags**:
   - `"Kelly size calculated as 0.0"` - Run bootstrap script
   - `"Heartbeat missed"` - Synthetic pulse failed
   - `"Wallet balance discrepancy > $1.00"` - Accounting guard failed
4. **7-Day Review** - Generate Analysis Report after 7 days
   - Success: Profit Factor > 1.2
   - Fail: Profit Factor < 0.8 triggers strategy reassessment

### System Design Choices
-   **Core Modules**: `bot_cycle.py` (main loop orchestrator), `position_manager.py` (position tracking), `blofin_client.py` (BloFin API), `dashboard_app.py` (Flask dashboard).
-   **Data Architecture**: A tri-layer approach using SQLite (`data/trading_system.db`) for historical data (WAL mode for concurrency) and JSON files for real-time state (`logs/positions_futures.json`, `feature_store/signal_weights.json`). Periodic syncing reconciles these layers.
-   **Configuration**: `config/asset_universe.json` defines enabled trading symbols (15 total, including BTCUSDT, ETHUSDT, SOLUSDT, AVAXUSDT, etc.), and `config/predictive_sizing.json` holds sizing parameters.
-   **Logging**: Runtime logs and state are stored in `logs/` (e.g., `positions_futures.json`, `signals.jsonl`).
-   **Supervisor**: `start_bot.sh` provides auto-restart functionality and health endpoint hosting.

## External Dependencies

### Exchange
-   **BloFin**: Used for futures trading, order execution, and market data. Requires `BLOFIN_API_KEY`, `BLOFIN_API_SECRET`, and `BLOFIN_PASSPHRASE`. Taker fee is 0.06%, Maker fee is 0.02%.

### Market Intelligence
-   **CoinGlass (v4)**: Provides taker buy/sell ratios, liquidations, funding rates, and Open Interest (OI) data.
-   **Alternative.me**: Used to fetch the Fear & Greed Index.
-   **CryptoCompare**: Provides social stats and sentiment data.

### Notifications
-   **SMTP Email**: Used for sending daily reports and alerts. Requires `SMTP_HOST`, `SMTP_USER`, `SMTP_PASS`, and `REPORT_TO_EMAIL`.
=======
