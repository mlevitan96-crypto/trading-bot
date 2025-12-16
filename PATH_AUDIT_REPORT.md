# Path Architecture Audit Report

## Executive Summary

The trading bot uses a slot-based deployment (trading-bot-A, trading-bot-B, trading-bot-current symlink), but path resolution is inconsistent across the codebase. This causes the dashboard to read stale or incorrect data because components are reading/writing from different locations.

## Critical Issues Identified

### 1. **Multiple Path Resolution Mechanisms**
- `PathRegistry` class with absolute path resolution
- `resolve_path()` function wrapper
- `DataRegistry` with relative paths (some use resolve_path, some don't)
- Direct hardcoded `"logs/..."` strings throughout codebase

### 2. **Key File Paths - Current State**

#### Positions & Trades (CRITICAL)
- **Canonical Source**: `logs/positions_futures.json`
  - `position_manager.py`: Uses `resolve_path("logs/positions_futures.json")` ✅
  - `pnl_dashboard.py`: Uses `resolve_path("logs/positions_futures.json")` ✅
  - `data_registry.py`: Uses `"logs/positions_futures.json"` (relative) ⚠️
  - `pnl_dashboard_loader.py`: Uses `DR.PORTFOLIO_MASTER` which points to same file ✅
  - `futures_portfolio_tracker.py`: Uses `PathRegistry.PORTFOLIO_LOG` (different file!) ❌

#### Portfolio Files
- `logs/portfolio_futures.json` - Used by `futures_portfolio_tracker.py`
- `logs/positions_futures.json` - Used by position manager and dashboard
- **ISSUE**: These are TWO DIFFERENT FILES! Dashboard reads from positions_futures.json, but portfolio tracker writes to portfolio_futures.json

#### Dashboard Data Sources
- `pnl_dashboard.py`:
  - `FUTURES_POS_LOG = resolve_path("logs/positions_futures.json")` ✅
  - `OPEN_POS_LOG = resolve_path("logs/positions.json")` ⚠️ (legacy spot file)
  - `WALLET_SNAPSHOTS_FILE = resolve_path("logs/wallet_snapshots.jsonl")` ✅

- `pnl_dashboard_loader.py`:
  - Uses `DR.PORTFOLIO_MASTER` which is `"logs/positions_futures.json"` ✅
  - But also tries SQLite first, then falls back to JSONL

### 3. **Path Resolution Issues**

#### Files Using `resolve_path()` ✅
- `src/position_manager.py` (after recent fix)
- `src/pnl_dashboard.py`
- `src/data_registry.py` (in helper methods)

#### Files Using Hardcoded Relative Paths ❌
- `src/run.py` - Many hardcoded `"logs/..."` paths
- `src/futures_portfolio_tracker.py` - Uses `PathRegistry` constants but different file
- Many phase files and other modules

#### Files Using `PathRegistry` Constants ⚠️
- `src/futures_portfolio_tracker.py` - Uses `PathRegistry.PORTFOLIO_LOG` (portfolio_futures.json)
- `src/infrastructure/path_registry.py` - Defines constants

### 4. **Root Cause Analysis**

**PRIMARY ISSUE**: The dashboard reads from `logs/positions_futures.json`, but:
1. The bot writes positions to `logs/positions_futures.json` ✅
2. BUT `futures_portfolio_tracker.py` writes to `logs/portfolio_futures.json` ❌
3. Dashboard loader tries SQLite first, which might be empty or stale
4. Some components use relative paths that resolve differently in A/B slots

**SECONDARY ISSUE**: Path resolution depends on `PROJECT_ROOT` detection:
- `PathRegistry` uses `__file__` to find project root
- Falls back to `os.getcwd()` if `.replit` doesn't exist
- In systemd, `WorkingDirectory=/root/trading-bot-current` should work, but if CWD changes, paths break

## Proposed Solution

### Unified Path Architecture

1. **Single Source of Truth**: `PathRegistry` class
2. **All paths relative to project root**: Use `resolve_path()` or `PathRegistry.get_path()`
3. **No hardcoded paths**: All file operations go through registry
4. **Consistent file usage**:
   - `logs/positions_futures.json` - Single file for ALL position/trade data
   - Remove `logs/portfolio_futures.json` or merge into positions_futures.json

### Implementation Plan

1. Update `PathRegistry` to be the authoritative source
2. Update `DataRegistry` to always use `resolve_path()` for all paths
3. Update `position_manager.py` to use `PathRegistry` constants
4. Update `pnl_dashboard.py` to use `PathRegistry` constants
5. Update `pnl_dashboard_loader.py` to use `PathRegistry` constants
6. Update `futures_portfolio_tracker.py` to use same file as dashboard
7. Update `run.py` to use `PathRegistry` for all log paths
8. Add validation to ensure all paths resolve correctly

## Files Requiring Updates

### Critical (Must Fix)
1. `src/position_manager.py` - Already uses resolve_path, but should use PathRegistry constant
2. `src/pnl_dashboard.py` - Uses resolve_path, should use PathRegistry constant
3. `src/pnl_dashboard_loader.py` - Uses DR.PORTFOLIO_MASTER, should verify it resolves correctly
4. `src/futures_portfolio_tracker.py` - Uses different file! Must fix
5. `src/data_registry.py` - Helper methods use resolve_path, but constants are relative

### Important (Should Fix)
6. `src/run.py` - Many hardcoded paths
7. Other modules with hardcoded `"logs/..."` paths

## Testing Plan

1. Verify `resolve_path()` works correctly in slot-based deployment
2. Test that bot writes and dashboard reads from same file
3. Verify systemd service uses correct working directory
4. Test path resolution when CWD != project root
5. Verify all components see same data



