# AI Assistant Context File

## 🚨 MANDATORY: Read Before Making Changes

This file ensures AI assistants have critical context. **You are reading this because you should also read `MEMORY_BANK.md`.**

## Quick Start for AI Assistants

1. **Read `MEMORY_BANK.md`** - Start with the "READ THIS FIRST" section
2. **Review `CONTEXT.md`** - Project structure and quick reference
3. **Check conversation history** - Look for recent context
4. **Follow REQUIRED PROCESS** - Documented in MEMORY_BANK.md

## Why This Matters

The user has experienced extreme frustration due to:
- Code that "looks correct" but doesn't work
- Assumptions without verification
- Not testing with actual data
- Disconnect between what's said and what's seen

**The user explicitly stated: "This can't keep happening."**

## Critical Files

- **`MEMORY_BANK.md`** - Comprehensive knowledge base (READ FIRST)
- **`CONTEXT.md`** - Quick reference guide
- **`src/pnl_dashboard_v2.py`** - Dashboard (see MEMORY_BANK.md for past issues)
- **`src/data_registry.py`** - Data paths (canonical source)
- **`logs/positions_futures.json`** - Authoritative trade data

## December 2024 Incident (See MEMORY_BANK.md)

Multiple dashboard fixes failed because:
1. Wrong year assumption (2025 vs 2024) - filtered out ALL data
2. Date parsing issues - timezone-aware strings not handled
3. P&L field mismatches - summary showed zeros
4. No testing with real data before claiming fixes

**Result**: User frustration, wasted time, broken dashboard

## Required Process (From MEMORY_BANK.md)

1. Read actual data files to verify structure and dates
2. Test calculations with real data before committing
3. Add comprehensive logging to see what's actually happening
4. Verify fixes work on actual deployment before claiming success
5. If user says it's broken, it's broken - investigate actual data, not just code

## Key Principles

- **BELIEVE THE USER** - If they report an issue, investigate actual data
- **Test with real data** - Don't assume code is correct
- **Add logging** - See what's actually happening
- **Verify before claiming** - Check logs and real results
- **No assumptions** - Verify dates, formats, field names

---

**Remember: The goal is to fix things correctly the first time, not to create more frustration.**
