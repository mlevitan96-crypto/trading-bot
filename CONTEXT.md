# Project Context - READ FIRST

## 🚨 CRITICAL: AI Assistant Instructions

**Before making ANY changes to this codebase, you MUST:**

1. **Read `MEMORY_BANK.md`** - This contains critical project knowledge, past failures, and mandatory processes
2. **Review recent conversation history** - Check for context about current work
3. **Follow the REQUIRED PROCESS** documented in MEMORY_BANK.md for any date/data/dashboard changes

## Why This Exists

This project has experienced critical failures due to:
- Assumptions without verification
- Not testing with actual data
- Disconnect between code and reality

**The user has explicitly stated these scenarios "can't keep happening"** - they caused extreme frustration.

## Quick Reference

- **Main Knowledge Base**: `MEMORY_BANK.md` - Comprehensive project documentation
- **Entry Point**: `src/run.py` - Main application entry
- **Dashboard**: `src/pnl_dashboard_v2.py` - P&L dashboard (has had critical issues - see MEMORY_BANK.md)
- **Data Registry**: `src/data_registry.py` - Canonical data paths

## Critical Sections in MEMORY_BANK.md

1. **"READ THIS FIRST"** - Mandatory reading before any changes
2. **"CRITICAL: Disconnect Between Code and Reality"** - December 2024 incident documentation
3. **"REQUIRED PROCESS"** - Mandatory steps for date/data changes
4. **Wallet Reset Information** - Critical for dashboard calculations

## When to Reference MEMORY_BANK.md

- **ALWAYS** before making dashboard changes
- **ALWAYS** before making date-related changes
- **ALWAYS** before making data filtering changes
- **ALWAYS** when user reports issues that "should be working"
- **ALWAYS** when code looks correct but doesn't work

## Project Structure

```
trading-bot/
├── MEMORY_BANK.md          # ⚠️ READ THIS FIRST - Critical knowledge base
├── CONTEXT.md             # This file - Quick reference
├── README.md             # Project overview
├── src/
│   ├── run.py            # Main entry point
│   ├── pnl_dashboard_v2.py  # Dashboard (see MEMORY_BANK.md for issues)
│   ├── data_registry.py  # Canonical data paths
│   └── ...
├── logs/
│   └── positions_futures.json  # Authoritative trade data
└── scripts/
    └── delete_bad_trades.py  # Utility for cleaning bad trades
```

---

**Remember: If the user says something is broken, BELIEVE THEM. Check actual data, not just code.**
