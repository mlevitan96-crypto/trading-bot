# Memory Bank - Trading Bot Knowledge Base
**Last Updated:** 2025-12-19  
**Purpose:** Comprehensive knowledge base for AI assistant to reference in all future conversations

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

## 🚨 CRITICAL: Disconnect Between Code and Reality
**This has happened multiple times and is extremely frustrating for the user:**
- Code looks correct but doesn't work in practice
- Assumptions about dates/years without verification
- Not testing with actual data before claiming fixes
- User reports issues but code "looks right" so we assume it's working

**REQUIRED PROCESS:**
1. Read actual data files to verify structure and dates
2. Test calculations with real data before committing
3. Add comprehensive logging to see what's actually happening
4. Verify fixes work on actual deployment before claiming success
5. If user says it's broken, it's broken - investigate actual data, not just code

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
├── config/                 # Configuration files (asset_universe.json, etc.)
├── configs/               # Strategy configs (38 JSON files)
├── logs/                   # Runtime logs and state
│   ├── positions_futures.json  # AUTHORITATIVE position data
│   ├── signals.jsonl           # All signals (executed + blocked)
│   └── enriched_decisions.jsonl
├── data/                   # SQLite database (trading_system.db)
├── feature_store/          # Signal weights, learning data
├── state/                  # System state snapshots
└── reports/                # Daily reports and analysis
```

### Critical Files (Single Source of Truth)
- **Positions Data**: `logs/positions_futures.json` (AUTHORITATIVE - never read from elsewhere)
- **Data Registry**: `src/data_registry.py` (all path resolution)
- **Path Registry**: `src/infrastructure/path_registry.py` (slot-based deployments)
- **Main Entry**: `src/run.py` (orchestrates everything)
- **Dashboard**: `src/pnl_dashboard_v2.py` (main dashboard, port 8050)

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
      "bot_type": "alpha"
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
      "closed_at": "2025-12-19T09:00:00Z"
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

## 🔄 Update Log

**2025-12-19**: Initial memory bank created
- Captured system architecture
- Documented deployment process
- Added common issues and solutions
- Included user preferences and constraints

---

**Note**: This memory bank should be updated whenever:
- New components are added
- Architecture changes are made
- Common issues are discovered and fixed
- Deployment process changes
- User preferences are updated
