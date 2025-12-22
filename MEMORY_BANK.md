# Memory Bank - Trading Bot Knowledge Base
**Last Updated:** 2025-12-20  
**Purpose:** Comprehensive knowledge base for AI assistant to reference in all future conversations

## 🚨 MANDATORY: READ THIS FIRST
**Before making ANY changes to dashboard, data filtering, or date-related code:**
1. Read the "CRITICAL: Disconnect Between Code and Reality" section below
2. Review the December 2024 incident documentation
3. Follow the REQUIRED PROCESS for all date/data changes
4. Test with actual data before claiming fixes
5. Add comprehensive logging to verify behavior

**The user has explicitly stated this scenario "can't keep happening" - it caused extreme frustration.**

## 🚨 CRITICAL: Data Location & Analysis
**IMPORTANT:** When user says "we have trade data" or "we have signals":
- **DO NOT** assume data doesn't exist if local files are empty
- **DO** check server/deployment location (data may be on remote server)
- **DO** use existing analysis tools that are designed to work with actual data sources
- **DO** check MEMORY_BANK.md for canonical data paths first
- **DO NOT** give up easily - data exists, find it or use tools that can access it
- **DO** run existing comprehensive analysis tools (comprehensive_trade_analysis.py, deep_profitability_analyzer.py)
- **DO** check for SQLite database, JSON files, JSONL files in multiple locations
- **DO** use DataRegistry methods which handle path resolution and fallbacks

**User Feedback (2025-12-20):**
- "There is trade data. Find it and run the analysis. Look through all documentation."
- "We have trade data. We have tons of signals. We have deep learning."
- "Review the memory bank and notate this type of reply. Not acceptable."

**REQUIRED:** Always check MEMORY_BANK.md for data locations, use existing analysis tools, and never assume data doesn't exist without thorough investigation.

## 🚨 CRITICAL: Wallet Reset (Dec 18, 2024)
**IMPORTANT:** A wallet reset occurred on December 18, 2024 late in the day. All dashboard calculations MUST:
- Exclude all trades closed before Dec 18, 2024
- Use starting capital of $10,000 (reset amount)
- Only count P&L from trades after the reset date
- Use timestamp comparison to avoid timezone issues

**Dashboard Configuration:**
- `WALLET_RESET_TS = datetime(2024, 12, 18, 0, 0, 0).timestamp()` (Dec 18, 2024 00:00:00 UTC)
- `STARTING_CAPITAL_AFTER_RESET = 10000.0`
- All calculations filter by `closed_ts >= WALLET_RESET_TS`

## ⚠️ CRITICAL LESSON: Date Verification & Testing
**NEVER assume dates without verification!**
- Always verify the actual year (2024 vs 2025) - this caused ALL data to disappear
- Test with actual data before committing - don't just code and hope
- Check logs to see if filters are working correctly
- If all data disappears, the filter date is likely wrong (too far in future/past)
- **ALWAYS verify fixes work before telling user it's fixed**
- **If user says it's not working, BELIEVE THEM and check actual data, don't assume code is correct**

## 🚨 CRITICAL: Disconnect Between Code and Reality - DECEMBER 2024 INCIDENT
**This incident caused EXTREME frustration and must NEVER happen again:**

### What Happened (December 18-20, 2024):
1. **Initial Problem**: Dashboard P&L data showing zeros, wallet balance incorrect after wallet reset on Dec 18, 2024
2. **First "Fix"**: Implemented wallet reset filter with date Dec 18, 2025 (WRONG YEAR - future date)
   - Result: ALL trades filtered out, dashboard showed no data, wallet went negative
   - User: "All closed trades are gone and the wallet is back to negative. None of the other things are right either. FRUSTRATING!"
3. **Second "Fix"**: Disabled reset filter, but summary calculations still showed zeros
   - Result: Closed trades visible, but summary stats (Net P&L, Win Rate, Wins/Losses, Total Trades) all zeros
   - User: "Everything is showing. The data in the summary section is still not working. Everything there is still a 0. I need that data to work. The references are incorrect. Figure that out!!!!"
4. **Root Causes**:
   - Assumed year without checking (2025 vs 2024)
   - Didn't verify date formats in actual data (timezone-aware strings like "2025-12-17T18:08:33.859132-07:00")
   - Didn't test with real data before claiming fixes
   - Summary function had date parsing issues and P&L field name mismatches
   - Silent failures in date parsing (exceptions caught but not logged)

### User's Explicit Feedback:
- "How is there such a disconnect between what you are telling me and what I am seeing??????????????????????????????"
- "I need you to fix it and confirm it is fixed before telling me it is fixed. I have been dealing with this all day copying and pasting back and forth. It shouldn't be this hard. Check your work and make sure it is correct."
- "Put this in the memory bank as something that can't keep happening."

### REQUIRED PROCESS (MANDATORY):
1. **BEFORE making any date-related changes:**
   - Read actual data file to see date formats
   - Check sample positions to verify year, timezone, format
   - Test date parsing with actual data samples
   - Verify filter logic with real timestamps

2. **BEFORE claiming a fix:**
   - Test with actual data (don't just review code)
   - Add comprehensive logging to show what's happening
   - Verify calculations with known good data
   - Check logs after deployment to confirm it works

3. **WHEN user reports issues:**
   - BELIEVE THE USER - if they say it's broken, it's broken
   - Don't assume code is correct just because it looks right
   - Check actual data files, not just code
   - Add debug logging to see what's actually happening
   - Test with real data before responding

4. **For summary/calculation functions:**
   - Check multiple P&L field name variations (`pnl`, `net_pnl`, `realized_pnl`, `profit_usd`, etc.)
   - Handle timezone-aware date strings properly
   - Log parse errors instead of silently failing
   - Verify date comparisons work with actual data formats

### Key Technical Details:
- **Date Format in Data**: `"2025-12-17T18:08:33.859132-07:00"` (timezone-aware ISO format)
- **P&L Field Names**: Primary is `"pnl"`, fallbacks: `"net_pnl"`, `"realized_pnl"`, `"profit_usd"`
- **Wallet Reset Date**: December 18, 2024 (NOT 2025) late in the day
- **Bad Trades Window**: December 18, 2025 1:00 AM - 6:00 AM UTC (deleted via script)

### Final Resolution:
- Disabled reset filter temporarily
- Fixed date parsing to handle timezone-aware strings
- Improved P&L field detection with multiple fallbacks
- Added comprehensive logging for debugging
- Created `scripts/delete_bad_trades.py` to remove bad trades

**THIS MUST BE REFERENCED AT THE START OF EVERY CONVERSATION ABOUT DASHBOARD OR DATA FILTERING**

## 🚨 CRITICAL: Trading Philosophy & Analysis Approach (2025-12-20)
**MANDATORY - READ FIRST BEFORE ANY ANALYSIS:**

### Core Principles:
1. **LEARNING OVER BLOCKING**: We learn from everything - blocked trades, missed opportunities, all angles
2. **PROFITABILITY THROUGH OPTIMIZATION**: Goal is to WIN, not avoid losses by blocking
3. **NO BLOCKING APPROACHES**: Never suggest blocking:
   - ❌ Symbols (BTC, ETH, etc.)
   - ❌ Directions (LONG or SHORT)
   - ❌ Timeframes
   - ❌ Signal types
4. **COMPREHENSIVE DATA USAGE**: Use ALL data sources:
   - Executed trades (winners and losers)
   - Blocked trades (why were they blocked? What would have happened?)
   - Missed opportunities (counterfactual learning)
   - All signals (executed + blocked + skipped)
   - Exit timing data
   - Entry timing data
   - Volume patterns
   - Every signal component and its weights

### Analysis Requirements:
- **MASSIVE DEEP DIVE**: Not surface-level, comprehensive analysis
- **SIGNAL WEIGHT OPTIMIZATION**: Analyze every signal component, how weights can be manipulated
- **TIMING ANALYSIS**: Entry timing, exit timing, hold duration
- **VOLUME ANALYSIS**: Volume patterns, volume at entry/exit
- **LEARNING FROM ALL ANGLES**: What makes winners? What makes losers? How to optimize?
- **RECENT DATA**: Use most recent trade data, not just old analysis
- **TRADER MINDSET**: Put trader hat on - focus on WINNING, not avoiding

### What NOT to Do:
- ❌ Never mention Beta experiment (it's done, move on)
- ❌ Never suggest blocking symbols/directions/timeframes
- ❌ Never take defensive approach (avoiding losses)
- ❌ Never give up on finding data - it exists, find it
- ❌ Never do surface-level analysis - must be comprehensive

### What TO Do:
- ✅ Find ALL data sources (trades, signals, blocked, missed opportunities)
- ✅ Analyze every signal component and weight optimization
- ✅ Analyze exits, timing, volume, all dimensions
- ✅ Learn from everything to improve profitability
- ✅ Focus on profitability through learning and optimization
- ✅ Use recent data, not just historical analysis

**User Feedback (2025-12-20):**
- "We have so much data. We are supposed to be learning from blocked trades, missed opportunities and all angles of trades."
- "We are never going to block long or short or time frames or symbols. We are going to learn from everything in order to trade on the information so we can win."
- "The goal is profitability not avoiding losses."
- "Are you checking every location for trade data and do you have recent trade data? Are you looking at exits, timing, volume, every signal and how it can be manipulated with different weights?"
- "This needs to be massive deep dive analysis."
- "Never bring up beta again. Never talk about disabling symbols, longs or shorts or timeframes."
- "Put your trader hat on and try to win."

**REQUIRED:** Every analysis must be comprehensive, use ALL data sources, focus on learning and optimization for profitability, never suggest blocking approaches.

---

## 🎯 Project Overview

**Project Name:** Crypto Trading Bot  
**Type:** Multi-strategy cryptocurrency futures trading bot  
**Exchange:** BloFin  
**Mode:** Paper Trading (Demo Account) → Live Trading  
**Goal:** Autonomous 24/7 operation with consistent profitability  
**Target:** 5-20 positions/day, $200-$2,000 per position

**Key Metrics:**
- Total Closed Trades: 1070+
- Wallet Balance: ~$9,900 (starting capital: $10,000)
- Max Concurrent Positions: 10
- Main Loop: 60-second cycle

---

## 🏗️ System Architecture

### Core Architecture Pattern: Tri-Layer Data Architecture
1. **Layer 1 (Intelligence)**: Historical data analysis (SQLite with WAL mode)
2. **Layer 2 (Governance)**: Reconciliation and audit logs
3. **Layer 3 (Execution)**: High-frequency trade logging (JSON files)

### Key Directories
```
trading-bot/
├── src/                    # Main source code (474 Python files)
│   └── enhanced_trade_logging.py  # NEW: Enhanced logging module
├── config/                 # Configuration files (asset_universe.json, etc.)
├── configs/               # Strategy configs (38 JSON files)
├── logs/                   # Runtime logs and state
│   ├── positions_futures.json  # AUTHORITATIVE position data (includes volatility_snapshot)
│   ├── signals.jsonl           # All signals (executed + blocked)
│   ├── enriched_decisions.jsonl # Enriched trades with volatility_snapshot
│   ├── executed_trades.jsonl   # Trade records (includes volatility_snapshot)
│   └── predictive_signals.jsonl # Detailed signal components
├── data/                   # SQLite database (trading_system.db)
├── feature_store/          # Signal weights, learning data, analysis exports
│   ├── signal_component_analysis.json  # Analysis results
│   ├── signal_analysis_export.csv      # CSV export
│   └── signal_analysis_summary.json    # JSON summary
├── state/                  # System state snapshots
└── reports/                # Daily reports and analysis
```

### Critical Files (Single Source of Truth)
- **Positions Data**: `logs/positions_futures.json` (AUTHORITATIVE - never read from elsewhere)
- **Data Registry**: `src/data_registry.py` (all path resolution)
- **Path Registry**: `src/infrastructure/path_registry.py` (slot-based deployments)
- **Main Entry**: `src/run.py` (orchestrates everything)
- **Dashboard**: `src/pnl_dashboard_v2.py` (main dashboard, port 8050)
- **Enhanced Logging**: `src/enhanced_trade_logging.py` (volatility snapshots, trading restrictions)
- **Analysis Tools**: `analyze_signal_components.py`, `export_signal_analysis.py`, `display_export_data.py`

---

## 🔑 Key Components

### 1. Trading Engine
- **File**: `src/bot_cycle.py` (main loop orchestrator)
- **Cycle**: 60-second main loop
- **Processes**: All enabled symbols per cycle

### 2. Position Management
- **File**: `src/position_manager.py`
- **Data Source**: `logs/positions_futures.json` (via `load_futures_positions()`)
- **Tracks**: Open/closed positions, real-time P&L, fee calculations
- **Limits**: Max 10 concurrent, 10% per symbol, 60% total futures exposure

### 3. Signal Generation
- **File**: `src/alpha_signals_integration.py`
- **Engine**: 10-signal multi-factor engine
- **Signals**: OFI (Order Flow Imbalance), Liquidation Cascade, Funding Rate, OI Velocity, etc.
- **Output**: `logs/signals.jsonl` (all signals: executed + blocked + skipped)

### 4. Dashboard
- **File**: `src/pnl_dashboard_v2.py`
- **Port**: 8050
- **Framework**: Flask + Dash (Dash Bootstrap Components)
- **Auth**: Password-protected (`Echelonlev2007!`)
- **Tabs**: Daily Summary, Executive Summary
- **URL**: `http://159.65.168.230:8050/`

### 5. Data Registry
- **File**: `src/data_registry.py`
- **Purpose**: Single source of truth for all data paths
- **Usage**: `from src.data_registry import DataRegistry as DR`
- **Key Methods**:
  - `DR.get_closed_positions(hours=168)` - Get closed positions
  - `DR.get_open_positions()` - Get open positions
  - `DR.read_json(path)` - Read JSON with path resolution
  - `DR.POSITIONS_FUTURES` - Canonical path constant

### 6. Path Registry
- **File**: `src/infrastructure/path_registry.py`
- **Purpose**: Handles slot-based deployments (A/B slots)
- **Usage**: `PathRegistry.get_path("logs", "positions.json")`
- **Critical**: Always use PathRegistry for paths in production

### 7. Exchange Client
- **File**: `src/blofin_client.py` (spot), `src/blofin_futures_client.py` (futures)
- **Exchange**: BloFin
- **Fees**: Taker 0.06%, Maker 0.02%
- **API Keys**: `BLOFIN_API_KEY`, `BLOFIN_API_SECRET`, `BLOFIN_PASSPHRASE`

---

## 📋 User Preferences & Constraints

### Critical Rules
1. **All changes in Python** - No shell scripts unless explicitly requested
2. **Detailed explanations required** - Explain what and why for all changes
3. **Ask before major architectural changes** - Don't refactor without permission
4. **Validate before live deployment** - Test thoroughly in paper mode
5. **Autonomous 24/7 trading is critical** - Trading stalls are emergencies
6. **Strategic Advisor mindset** - Proactively surface risks and opportunities
7. **No "inversion" terminology** - Signals indicate correct direction directly
8. **Quality over quantity** - 5-20 positions/day, not high-frequency

### Development Workflow
1. **Always deploy to Git first** - Never make direct changes on droplet
2. **Test locally when possible** - Verify imports, logic, error handling
3. **Use descriptive commit messages** - Follow format in DEPLOYMENT_AND_BEST_PRACTICES.md
4. **Monitor after deployment** - Check logs immediately after restart

### Code Quality Standards
- **Error Handling**: Always use try/except with meaningful messages
- **Memory Management**: Limit data loading (500-1000 records max)
- **Logging**: Use `flush=True` for Dash apps, add context to errors
- **Path Resolution**: Always use PathRegistry or DataRegistry for paths
- **Data Access**: Always use DataRegistry methods, never read JSON directly

---

## 🚀 Deployment Process

### Server Information
- **IP**: `159.65.168.230`
- **SSH**: `ssh root@159.65.168.230`
- **Service**: `tradingbot.service` (systemd)
- **Active Slot**: `/root/trading-bot-current` (symlink to A or B slot)
- **Dashboard URL**: `http://159.65.168.230:8050/`

### Active Directory Confirmation (December 2024)
**CRITICAL**: The bot's active directory is `/root/trading-bot-B`, NOT `/root/trading-bot-current`
- PathRegistry resolves PROJECT_ROOT to `/root/trading-bot-B` based on where `path_registry.py` is located
- Signal tracker and all components use `/root/trading-bot-B/` as the base path
- User may SSH into `/root/trading-bot-current`, but must be aware bot runs from `trading-bot-B`
- To check active directory: `python3 -c "from src.infrastructure.path_registry import PathRegistry; print(PathRegistry.get_root())"`
- Multiple directories exist: `trading-bot-A` (old, 694 signals), `trading-bot-B` (active, 1 signal), `trading-bot-current` (symlink or copy)

### A/B Slot Deployment System
- `/root/trading-bot-A` - Slot A
- `/root/trading-bot-B` - Slot B
- `/root/trading-bot-current` - Symlink to active slot

### Standard Deployment Steps
```bash
# 1. Local: Commit and push
git add <files>
git commit -m "Descriptive message"
git push origin main

# 2. On Droplet: Pull and restart
cd /root/trading-bot-current
git pull origin main
sudo systemctl restart tradingbot
sleep 30
sudo systemctl status tradingbot
curl -I http://localhost:8050/
```

### Verification Commands
```bash
# Service status
sudo systemctl status tradingbot

# Dashboard access
curl -I http://localhost:8050/

# Recent logs
journalctl -u tradingbot --since "2 minutes ago" | tail -30

# Error check
journalctl -u tradingbot --since "5 minutes ago" | grep -E "ERROR|Traceback|SIGKILL"
```

---

## 🔧 Common Issues & Solutions

### Dashboard Issues
**Problem**: Dashboard not loading, blank tabs, callback errors
**Solutions**:
- Check callback syntax (separate Input args, not list)
- Verify authentication middleware allows Dash routes (`/_`, `/`)
- Check data loading functions handle missing files gracefully
- Verify imports work: `from src.pnl_dashboard_v2 import start_pnl_dashboard`

### Memory Issues (SIGKILL/OOM)
**Problem**: Worker killed, dashboard crashes
**Solutions**:
- Limit data loading (max 500-1000 records)
- Use `DR.get_closed_positions(hours=168)` instead of loading all
- Add timeouts to prevent hanging operations
- Check logs for what was loading when killed

### Import Errors
**Problem**: `ModuleNotFoundError` or `ImportError`
**Solutions**:
- Verify all imports are correct
- Check if module exists in codebase
- Use fallback imports with try/except
- Verify virtual environment is activated

### Data Not Showing
**Problem**: Dashboard loads but shows empty/zero data
**Solutions**:
- Check if data files exist: `ls -la /root/trading-bot-current/logs/positions_futures.json`
- Verify DataRegistry can read files
- Check error logs for data loading failures
- Verify path resolution is correct (use PathRegistry)

### Trading Stalls
**Problem**: Bot stops trading (emergency situation)
**Solutions**:
- Check service status: `sudo systemctl status tradingbot`
- Check logs for errors: `journalctl -u tradingbot -n 100`
- Verify positions file exists and is readable
- Check for zombie positions blocking capital
- Verify signal generation is working

---

## 📊 Data Architecture

### Position Data Schema
**File**: `logs/positions_futures.json`
```json
{
  "open_positions": [
    {
      "symbol": "BTCUSDT",
      "direction": "LONG",
      "entry_price": 45000.0,
      "size": 0.1,
      "leverage": 10,
      "margin_collateral": 450.0,
      "opened_at": "2025-12-19T10:00:00Z",
      "strategy": "Alpha",
      "bot_type": "alpha",
      "volatility_snapshot": {
        "atr_14": 123.45,
        "volume_24h": 1000000.0,
        "regime_at_entry": "Trending",
        "signal_components": {
          "liquidation": 0.75,
          "funding": 0.0001,
          "whale": 500000.0
        }
      }
    }
  ],
  "closed_positions": [
    {
      "symbol": "ETHUSDT",
      "direction": "LONG",
      "entry_price": 2500.0,
      "exit_price": 2550.0,
      "pnl": 50.0,
      "net_pnl": 45.0,
      "opened_at": "2025-12-19T08:00:00Z",
      "closed_at": "2025-12-19T09:00:00Z",
      "volatility_snapshot": {
        "atr_14": 50.25,
        "volume_24h": 500000.0,
        "regime_at_entry": "Volatile",
        "signal_components": {
          "liquidation": 0.50,
          "funding": 0.0002,
          "whale": 250000.0
        }
      }
    }
  ]
}
```

### Standardized Field Names
- `symbol`: Trading pair (e.g., "BTCUSDT")
- `direction`: "LONG" or "SHORT"
- `entry_price`, `exit_price`: Float values
- `size`: Contract size
- `leverage`: Integer (1-100)
- `margin_collateral`: USD margin used
- `pnl` or `net_pnl`: Realized P&L (after fees)
- `opened_at`, `closed_at`: ISO 8601 timestamps
- `strategy`: Strategy name
- `bot_type`: "alpha" or "beta"
- `volatility_snapshot`: Dict with ATR, volume, regime, signal_components (NEW - December 2025)

### Data Access Patterns
**ALWAYS USE:**
```python
from src.data_registry import DataRegistry as DR
from src.position_manager import load_futures_positions

# Get positions
positions = load_futures_positions()  # Returns full dict with open/closed
open_pos = DR.get_open_positions()
closed_pos = DR.get_closed_positions(hours=168)  # Last 7 days
```

**NEVER:**
- Read `positions_futures.json` directly with `open()` and `json.load()`
- Hardcode paths like `"logs/positions_futures.json"`
- Use relative paths without PathRegistry

---

## 🎨 Dashboard Architecture

### Dashboard Structure
- **Framework**: Flask (server) + Dash (UI)
- **Theme**: Dash Bootstrap Components (DARKLY)
- **Port**: 8050
- **Authentication**: Session-based password auth

### Key Components
1. **System Health Panel**: Shows signal engine, decision engine, trade execution, self-healing status
2. **Daily Summary Tab**: Wallet balance, trades, charts, open/closed positions
3. **Executive Summary Tab**: What worked, what didn't, missed opportunities, learning

### Callback Pattern
```python
@app.callback(
    Output("component-id", "property"),
    Input("input-id", "property"),
    Input("interval-id", "n_intervals"),
    prevent_initial_call=False,
)
def callback_function(input_value, n_intervals):
    # Always use try/except
    # Always use flush=True for print statements
    # Always handle missing data gracefully
    pass
```

### Common Dashboard Fixes
1. **Callback Syntax**: Use separate `Input()` args, not list `[Input(), Input()]`
2. **Authentication**: Allow Dash routes (`/_`, `/`, `OPTIONS`)
3. **Data Loading**: Limit to 500 records, use time-based filtering
4. **Error Handling**: Always return valid HTML components, never None

---

## 🔄 Phase Architecture

### Current Phases
- **Phase 2**: Offensive Architecture (Hurst-based regime gating, predictive sizing)
- **Phase 7.x**: Predictive Intelligence (self-tuning execution, adaptive parameters)
- **Phase 8.x**: Full Autonomy (self-healing watchdogs, edge compounding)
- **Phase 9.x**: Autonomy Controller (health scoring, capital scaling)
- **Phase 10.x**: Profit Engine (expectancy gates, attribution-weighted allocation)

### Phase Files Pattern
- `src/phase2_*.py` - Phase 2 components
- `src/phase7_*.py` - Phase 7 components
- `src/phase8_*.py` - Phase 8 components
- etc.

---

## 🛡️ Risk Management

### Position Limits
- **Max Concurrent**: 10 positions
- **Per Symbol**: 10% of capital
- **Total Futures Exposure**: 60% of capital
- **Per Sector**: 2 positions max (7 sectors: mega, l1, l2, defi, meme, exchange, payment)

### Exit Logic
- **Trailing Stops**: Dynamic stop-loss adjustment
- **Time Exits**: Maximum hold time enforcement
- **Profit Locks**: Lock in profits at thresholds
- **Emergency Exits**: Bypass hold time if drawdown >1.5% or position loss >2%

### Circuit Breakers
- **Session Loss Limit**: Daily loss threshold
- **Kill Switches**: Emergency stop mechanisms
- **Auto-Recovery**: Automatic restart after failures

---

## 📝 Important Patterns

### Error Handling Pattern
```python
try:
    # Operation
    result = some_function()
except Exception as e:
    print(f"⚠️  Error description: {e}", flush=True)
    import traceback
    traceback.print_exc()
    # Return safe default
    return default_value
```

### Data Loading Pattern
```python
try:
    from src.data_registry import DataRegistry as DR
    data = DR.get_closed_positions(hours=168)  # Limit by time
    if len(data) > 500:  # Limit by count
        data = data[-500:]
except Exception as e:
    print(f"⚠️  Error loading data: {e}", flush=True)
    data = []  # Safe default
```

### Path Resolution Pattern
```python
from src.infrastructure.path_registry import PathRegistry

# Always use PathRegistry for paths
file_path = PathRegistry.get_path("logs", "positions.json")
# Returns absolute path, handles slot-based deployments
```

### Logging Pattern
```python
# For Dash apps, always use flush=True
print(f"🔍 [COMPONENT] Message", flush=True)

# Add context to errors
print(f"❌ [COMPONENT] Error: {e}", flush=True)
import traceback
traceback.print_exc()
```

---

## 🧪 Testing & Validation

### Pre-Deployment Testing
```bash
# Test imports
python3 -c "from src.pnl_dashboard_v2 import start_pnl_dashboard; print('OK')"

# Test dashboard build
python3 -c "from src.pnl_dashboard_v2 import build_app; app = build_app(); print('OK' if app else 'FAIL')"
```

### Post-Deployment Verification
```bash
# Service health
sudo systemctl status tradingbot

# Dashboard access
curl -I http://localhost:8050/

# Error check
journalctl -u tradingbot --since "5 minutes ago" | grep -E "ERROR|Traceback"
```

---

## 📚 Key Documentation Files

- `DEPLOYMENT_AND_BEST_PRACTICES.md` - Complete deployment guide
- `DEPLOYMENT_CHECKLIST.md` - Quick deployment checklist
- `README.md` - Project overview and current status
- `DIGITALOCEAN_DEPLOYMENT.md` - Droplet-specific deployment
- `DASHBOARD_TROUBLESHOOTING.md` - Dashboard-specific issues

---

## 🔍 Quick Reference

### Common Commands
```bash
# Git workflow
git status
git add <file>
git commit -m "Message"
git push origin main

# Droplet deployment
cd /root/trading-bot-current
git pull origin main
sudo systemctl restart tradingbot

# Logs
journalctl -u tradingbot --since "10 minutes ago" | tail -50
journalctl -u tradingbot --since "10 minutes ago" | grep "DASHBOARD-V2"
```

### Critical Paths
- Positions: `logs/positions_futures.json` (via DataRegistry)
- Dashboard: `src/pnl_dashboard_v2.py`
- Main Entry: `src/run.py`
- Data Registry: `src/data_registry.py`
- Path Registry: `src/infrastructure/path_registry.py`

### Important Constants
- Dashboard Port: `8050`
- Dashboard Password: `Echelonlev2007!`
- Starting Capital: `$10,000`
- Max Positions: `10`
- Main Loop: `60 seconds`

---

## 🎓 Lessons Learned

### Critical Fixes Applied
1. **Dashboard Callback Syntax**: Fixed list syntax to separate Input args
2. **Authentication Middleware**: Allow Dash internal routes
3. **Wallet Balance**: Read directly from JSON for all positions
4. **Memory Limits**: Always limit data loading to 500-1000 records
5. **Error Handling**: Always return valid components, never None

### Common Mistakes to Avoid
1. **Don't read JSON files directly** - Always use DataRegistry
2. **Don't hardcode paths** - Always use PathRegistry
3. **Don't load all data** - Always limit by time and count
4. **Don't let errors crash dashboard** - Always return safe defaults
5. **Don't skip error handling** - Always use try/except

---

## 📊 Enhanced Logging & Analysis Workstreams (December 2025)

### Enhanced Trade Logging Module
**File**: `src/enhanced_trade_logging.py` (NEW - December 2025)
- **Purpose**: Capture comprehensive market data and signal components at trade entry
- **Key Functions**:
  - `is_golden_hour()` - Check if within 09:00-16:00 UTC trading window
  - `get_market_data_snapshot()` - Fetch ATR_14, volume_24h, regime_at_entry
  - `extract_signal_components()` - Extract liquidation/funding/whale flow scores
  - `create_volatility_snapshot()` - Complete snapshot with all metrics
  - `check_stable_regime_block()` - Block trades in Stable regime (35.2% win rate)
  - `check_golden_hours_block()` - Block trades outside golden hours

### Volatility Snapshot Data Structure
**Location**: Stored in `position["volatility_snapshot"]` and `trade["volatility_snapshot"]`
```json
{
  "atr_14": 123.45,
  "volume_24h": 1000000.0,
  "regime_at_entry": "Trending",
  "signal_components": {
    "liquidation": 0.75,
    "funding": 0.0001,
    "whale": 500000.0
  }
}
```

### Data File Locations
**Position Data**: `logs/positions_futures.json`
- Open positions: `positions["open_positions"][i]["volatility_snapshot"]`
- Closed positions: `positions["closed_positions"][i]["volatility_snapshot"]`

**Trade Records**: `logs/executed_trades.jsonl` (via `data_sync_module.py`)
- Each trade record includes `"volatility_snapshot"` field

**Enriched Decisions**: `logs/enriched_decisions.jsonl` (via `data_enrichment_layer.py`)
- Extracted to `signal_ctx["volatility_snapshot"]` for analysis

### Trading Restrictions (December 2025)
1. **Stable Regime Block**:
   - **Location**: `src/unified_recovery_learning_fix.py`, `src/full_integration_blofin_micro_live_and_paper.py`
   - **Function**: `pre_entry_check()` - checks before every entry
   - **Logic**: Hard blocks when `regime == "Stable"` (35.2% win rate)
   - **Impact**: Expected to boost win rate by removing ~44.5% of worst-performing trades

2. **Golden Hour Trading Window**:
   - **Location**: Same files as above
   - **Window**: 09:00-16:00 UTC (London Open to NY Close)
   - **Behavior**: Blocks NEW entries outside window, allows existing positions to close
   - **Implementation**: Fails open (doesn't break trading if check fails)

### Analysis Workstreams (December 2025)

#### 1. Signal Component Analysis
**File**: `analyze_signal_components.py`
- **Purpose**: Analyze trades with volatility and signal component breakdown
- **Input**: `logs/enriched_decisions.jsonl`, `logs/predictive_signals.jsonl`
- **Output**: `feature_store/signal_component_analysis.json`
- **Key Features**:
  - Tests volatility hypothesis (losses correlate with low/extreme volatility)
  - Tests signal component hypothesis (liquidation cascade vs funding vs whale flow)
  - Tests regime accuracy hypothesis
  - Exports detailed trade metrics for external review

**Usage**:
```bash
python3 analyze_signal_components.py
```

#### 2. Export Signal Analysis
**File**: `export_signal_analysis.py`
- **Purpose**: Export analysis results in CSV and JSON formats
- **Input**: `feature_store/signal_component_analysis.json`
- **Output**: 
  - `feature_store/signal_analysis_export.csv` (all trades with metrics)
  - `feature_store/signal_analysis_summary.json` (high-level summary)
- **Key Features**:
  - CSV export for spreadsheet analysis
  - JSON summary for quick review
  - Includes all volatility snapshot data

**Usage**:
```bash
python3 export_signal_analysis.py
```

#### 3. Display Export Data
**File**: `display_export_data.py`
- **Purpose**: Display exported data in terminal for copy/paste
- **Input**: `feature_store/signal_analysis_export.csv`, `feature_store/signal_analysis_summary.json`
- **Output**: Formatted terminal output
- **Key Features**:
  - Shows first 20 trades in readable format
  - Shows JSON summary in copy-pasteable format
  - Designed for easy data extraction from server

**Usage**:
```bash
python3 display_export_data.py
```

### Data Enrichment Pipeline
**File**: `src/data_enrichment_layer.py`
- **Purpose**: Enrich trade records with signal context and volatility snapshots
- **Process**:
  1. Loads trades from `logs/executed_trades.jsonl`
  2. Matches with signals from `logs/predictive_signals.jsonl`
  3. Extracts volatility snapshot from trade records
  4. Creates enriched records in `logs/enriched_decisions.jsonl`
- **Key Fields Extracted**:
  - `signal_ctx.volatility_snapshot` - Complete volatility data
  - `signal_ctx.signal_components` - Individual signal scores
  - `signal_ctx.volatility` - Volatility metric
  - `signal_ctx.volume` - Volume metric

### Best Practices for Enhanced Logging

1. **Always Check Volatility Snapshot**:
   - When analyzing trades, check `trade.get("volatility_snapshot", {})`
   - If empty, trade was opened before December 2025 implementation
   - New trades (after deployment) will have complete data

2. **Signal Component Extraction**:
   - Components stored in `volatility_snapshot["signal_components"]`
   - Format: `{"liquidation": float, "funding": float, "whale": float}`
   - If missing, check `signal_ctx.signal_components` in enriched records

3. **Regime Data**:
   - Always use `regime_at_entry` from volatility snapshot (captured at entry time)
   - Don't use current regime for historical analysis
   - Regime values: "Stable", "Trending", "Volatile", "Ranging", "unknown"

4. **Analysis Workflow**:
   ```bash
   # Step 1: Run analysis
   python3 analyze_signal_components.py
   
   # Step 2: Export results
   python3 export_signal_analysis.py
   
   # Step 3: Display for review
   python3 display_export_data.py
   ```

5. **Data Quality Checks**:
   - Verify `atr_14 > 0` for new trades (indicates successful capture)
   - Verify `signal_components` not empty for new trades
   - Check `regime_at_entry` matches expected values

### Files Modified for Enhanced Logging
1. `src/enhanced_trade_logging.py` - NEW module (December 2025)
2. `src/position_manager.py` - Captures volatility snapshot at entry
3. `src/futures_portfolio_tracker.py` - Stores volatility snapshot in trade records
4. `src/unified_recovery_learning_fix.py` - Added golden hour + stable regime checks
5. `src/full_integration_blofin_micro_live_and_paper.py` - Added golden hour + stable regime checks
6. `src/bot_cycle.py` - Enhanced signal_context to include signals
7. `src/data_enrichment_layer.py` - Extracts volatility_snapshot for analysis

---

## 🔄 Update Log

**2025-12-22**: Enhanced Logging & Trading Restrictions Implementation
- **NEW**: `src/enhanced_trade_logging.py` module for comprehensive trade logging
- **NEW**: Volatility snapshot capture (ATR, volume, regime, signal components) at entry
- **NEW**: Stable regime block (hard blocks trades in Stable regime - 35.2% win rate)
- **NEW**: Golden hour trading window (09:00-16:00 UTC, blocks new entries outside window)
- **NEW**: Analysis workstreams (`analyze_signal_components.py`, `export_signal_analysis.py`, `display_export_data.py`)
- **ENHANCED**: `data_enrichment_layer.py` to extract volatility snapshots
- **ENHANCED**: Trade records now include `volatility_snapshot` field
- **Data Locations**: Volatility snapshots stored in positions and trades, accessible via enriched_decisions.jsonl
- **Expected Impact**: Immediate win rate boost from stable regime block, complete data for analysis after 3-5 days

**2025-12-22**: Active Directory Confirmation
- **CONFIRMED**: Bot's active directory is `/root/trading-bot-B` (not `/root/trading-bot-current`)
- PathRegistry PROJECT_ROOT resolves to `/root/trading-bot-B` based on `path_registry.py` location
- Signal tracker uses `/root/trading-bot-B/feature_store/pending_signals.json`
- Multiple directories exist: `trading-bot-A` (old, 694 signals), `trading-bot-B` (active), `trading-bot-current` (user SSH location)
- Use `check_all_pending_signals.py` to verify which directory has signals

**2025-12-19**: Initial memory bank created
- Captured system architecture
- Documented deployment process
- Added common issues and solutions
- Included user preferences and constraints

---

## Fee Tracking Status (December 2024)

### Fee Data Collection
✅ **Fees ARE being tracked and recorded:**
- Trading fees: Recorded in all trades ($0.05-$0.96 per trade, avg $0.25)
- Funding fees: Recorded when applicable (typically $0.00 for quick closes)
- Total fees across all trades: ~$545.93
- Fees are stored in `trading_fees` and `funding_fees` fields in trade records
- Fees are properly extracted in `data_enrichment_layer.py` for learning engine

### Fee Usage in Calculations
✅ **Fees ARE being used in all critical calculations:**
- **Net P&L**: All `net_pnl` values already include fees deducted (gross P&L - fees)
- **Learning Engine**: Fees are included in enriched decision records (`data_enrichment_layer.py` lines 142-144)
- **Portfolio Tracking**: Fees are accumulated in portfolio totals (`futures_portfolio_tracker.py`)
- **Counterfactual Learning**: Fees are used in hypothetical P&L calculations (`decision_attribution.py`)
- **Signal Evaluation**: Fees are part of outcome data used for signal weight learning

### Dashboard Display Issue
⚠️ **Known Issue (December 2024):**
- Fees column in dashboard closed trades table shows $0.00 (display issue only)
- Fee extraction logic in `pnl_dashboard.py` is correct
- Summary card "Total Fees" calculation works correctly
- **User Decision**: Not troubleshooting dashboard display further as long as fees are used in calculations
- **Root Cause**: Likely browser cache or Dash table rendering issue, but not critical since fees are used in all calculations

### User Preference
**User explicitly stated (December 2024):**
- "As long as they are being calculated somewhere and part of the overall signals calculation, then I don't want to proceed with troubleshooting."
- Do NOT attempt further dashboard fee display fixes unless explicitly requested
- Focus on ensuring fees are used in learning and profitability calculations (which they are)

---

**Note**: This memory bank should be updated whenever:
- New components are added
- Architecture changes are made
- Common issues are discovered and fixed
- Deployment process changes
- User preferences are updated
