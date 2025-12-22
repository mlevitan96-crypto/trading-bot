#!/usr/bin/env python3
"""
Deep "WHY" Analysis
==================
Answers the fundamental questions:
1. WHY are LONG trades losing?
2. WHY are SHORT trades winning?
3. WHY does OFI work better than Sentiment?
4. What patterns in the data can we leverage?
5. How can we improve OFI predictions?

This script analyzes:
- OFI values and direction at entry vs outcomes
- Market conditions (regime, volatility) during trades
- Signal alignment (OFI direction vs trade direction)
- Price action correlation
- Market direction bias
- Strategy component effectiveness
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from typing import Dict, List, Any, Tuple
from statistics import mean, median

sys.path.insert(0, os.path.dirname(__file__))

print("=" * 80)
print("DEEP 'WHY' ANALYSIS")
print("=" * 80)
print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

results = {
    "generated_at": datetime.now().isoformat(),
    "questions": {},
    "insights": [],
    "recommendations": []
}

# ============================================================================
# LOAD ALL TRADE DATA WITH SIGNAL CONTEXT
# ============================================================================
print("=" * 80)
print("LOADING TRADE DATA WITH SIGNAL CONTEXT")
print("=" * 80)

from src.data_registry import DataRegistry as DR

closed_trades = DR.get_closed_positions(hours=168*24)  # Last 7 days, but get more if available
print(f"📊 Loaded {len(closed_trades)} closed trades")

# Also try to load enriched decisions for signal context
enriched_decisions = []
enriched_file = Path("logs/enriched_decisions.jsonl")
if enriched_file.exists():
    with open(enriched_file, 'r') as f:
        for line in f:
            try:
                enriched_decisions.append(json.loads(line.strip()))
            except:
                pass
    print(f"📊 Loaded {len(enriched_decisions)} enriched decisions")

# Create lookup: trade_id -> enriched context
enriched_lookup = {}
for ed in enriched_decisions:
    symbol = ed.get("symbol", "")
    ts = ed.get("ts") or ed.get("entry_ts")
    if symbol and ts:
        key = f"{symbol}_{ts}"
        enriched_lookup[key] = ed

print()

# ============================================================================
# QUESTION 1: WHY ARE LONG TRADES LOSING?
# ============================================================================
print("=" * 80)
print("QUESTION 1: WHY ARE LONG TRADES LOSING?")
print("=" * 80)

long_trades = []
short_trades = []

for trade in closed_trades:
    direction = trade.get("direction", "").upper()
    if direction in ["LONG", "long"]:
        long_trades.append(trade)
    elif direction == "SHORT":
        short_trades.append(trade)

print(f"\n📊 Trade Distribution:")
print(f"   LONG/long trades: {len(long_trades)}")
print(f"   SHORT trades: {len(short_trades)}")

# Analyze LONG trades
long_pnl = sum(t.get("net_pnl", t.get("realized_pnl", t.get("pnl", 0))) or 0 for t in long_trades)
long_wins = [t for t in long_trades if (t.get("net_pnl", t.get("realized_pnl", t.get("pnl", 0))) or 0) > 0]
long_losses = [t for t in long_trades if (t.get("net_pnl", t.get("realized_pnl", t.get("pnl", 0))) or 0) < 0]

print(f"\n📉 LONG Trade Performance:")
print(f"   Total P&L: ${long_pnl:.2f}")
print(f"   Wins: {len(long_wins)} ({len(long_wins)/len(long_trades)*100:.1f}%)")
print(f"   Losses: {len(long_losses)} ({len(long_losses)/len(long_trades)*100:.1f}%)")

# Analyze price direction for LONG trades
long_price_analysis = {
    "price_went_up": 0,
    "price_went_down": 0,
    "price_stayed_same": 0,
    "avg_price_change_pct": []
}

for trade in long_trades:
    entry_price = float(trade.get("entry_price", 0) or 0)
    exit_price = float(trade.get("exit_price", 0) or 0)
    if entry_price > 0 and exit_price > 0:
        price_change_pct = ((exit_price - entry_price) / entry_price) * 100
        long_price_analysis["avg_price_change_pct"].append(price_change_pct)
        if price_change_pct > 0.1:
            long_price_analysis["price_went_up"] += 1
        elif price_change_pct < -0.1:
            long_price_analysis["price_went_down"] += 1
        else:
            long_price_analysis["price_stayed_same"] += 1

if long_price_analysis["avg_price_change_pct"]:
    avg_price_change = mean(long_price_analysis["avg_price_change_pct"])
    print(f"\n   💡 Price Action Analysis:")
    print(f"      Average price change: {avg_price_change:+.2f}%")
    print(f"      Price went UP: {long_price_analysis['price_went_up']} ({long_price_analysis['price_went_up']/len(long_trades)*100:.1f}%)")
    print(f"      Price went DOWN: {long_price_analysis['price_went_down']} ({long_price_analysis['price_went_down']/len(long_trades)*100:.1f}%)")
    print(f"      Price stayed same: {long_price_analysis['price_stayed_same']} ({long_price_analysis['price_stayed_same']/len(long_trades)*100:.1f}%)")

# Analyze OFI at entry for LONG trades
long_ofi_analysis = {
    "ofi_positive": {"count": 0, "wins": 0, "pnl": 0},
    "ofi_negative": {"count": 0, "wins": 0, "pnl": 0},
    "ofi_weak": {"count": 0, "wins": 0, "pnl": 0},
    "ofi_strong": {"count": 0, "wins": 0, "pnl": 0},
    "ofi_aligned": {"count": 0, "wins": 0, "pnl": 0},
    "ofi_misaligned": {"count": 0, "wins": 0, "pnl": 0}
}

for trade in long_trades:
    # Try to get OFI from multiple sources
    ofi = trade.get("ofi_score") or trade.get("ofi") or 0
    if isinstance(ofi, (int, float)):
        ofi_value = float(ofi)
        pnl = float(trade.get("net_pnl") or trade.get("realized_pnl") or trade.get("pnl") or 0)
        is_win = pnl > 0
        
        # OFI direction analysis
        if ofi_value > 0.01:
            long_ofi_analysis["ofi_positive"]["count"] += 1
            if is_win:
                long_ofi_analysis["ofi_positive"]["wins"] += 1
            long_ofi_analysis["ofi_positive"]["pnl"] += pnl
        elif ofi_value < -0.01:
            long_ofi_analysis["ofi_negative"]["count"] += 1
            if is_win:
                long_ofi_analysis["ofi_negative"]["wins"] += 1
            long_ofi_analysis["ofi_negative"]["pnl"] += pnl
        
        # OFI strength analysis
        ofi_abs = abs(ofi_value)
        if ofi_abs < 0.3:
            long_ofi_analysis["ofi_weak"]["count"] += 1
            if is_win:
                long_ofi_analysis["ofi_weak"]["wins"] += 1
            long_ofi_analysis["ofi_weak"]["pnl"] += pnl
        elif ofi_abs >= 0.5:
            long_ofi_analysis["ofi_strong"]["count"] += 1
            if is_win:
                long_ofi_analysis["ofi_strong"]["wins"] += 1
            long_ofi_analysis["ofi_strong"]["pnl"] += pnl
        
        # OFI alignment (OFI positive should align with LONG)
        if ofi_value > 0.01:  # OFI positive = buying pressure = should be LONG
            long_ofi_analysis["ofi_aligned"]["count"] += 1
            if is_win:
                long_ofi_analysis["ofi_aligned"]["wins"] += 1
            long_ofi_analysis["ofi_aligned"]["pnl"] += pnl
        elif ofi_value < -0.01:  # OFI negative = selling pressure = misaligned with LONG
            long_ofi_analysis["ofi_misaligned"]["count"] += 1
            if is_win:
                long_ofi_analysis["ofi_misaligned"]["wins"] += 1
            long_ofi_analysis["ofi_misaligned"]["pnl"] += pnl

print(f"\n   📊 OFI Analysis for LONG Trades:")
if long_ofi_analysis["ofi_positive"]["count"] > 0:
    wr = long_ofi_analysis["ofi_positive"]["wins"] / long_ofi_analysis["ofi_positive"]["count"] * 100
    print(f"      OFI Positive (aligned): {long_ofi_analysis['ofi_positive']['count']} trades, WR={wr:.1f}%, P&L=${long_ofi_analysis['ofi_positive']['pnl']:.2f}")
if long_ofi_analysis["ofi_negative"]["count"] > 0:
    wr = long_ofi_analysis["ofi_negative"]["wins"] / long_ofi_analysis["ofi_negative"]["count"] * 100
    print(f"      OFI Negative (misaligned): {long_ofi_analysis['ofi_negative']['count']} trades, WR={wr:.1f}%, P&L=${long_ofi_analysis['ofi_negative']['pnl']:.2f}")
if long_ofi_analysis["ofi_weak"]["count"] > 0:
    wr = long_ofi_analysis["ofi_weak"]["wins"] / long_ofi_analysis["ofi_weak"]["count"] * 100
    print(f"      Weak OFI (<0.3): {long_ofi_analysis['ofi_weak']['count']} trades, WR={wr:.1f}%, P&L=${long_ofi_analysis['ofi_weak']['pnl']:.2f}")
if long_ofi_analysis["ofi_strong"]["count"] > 0:
    wr = long_ofi_analysis["ofi_strong"]["wins"] / long_ofi_analysis["ofi_strong"]["count"] * 100
    print(f"      Strong OFI (≥0.5): {long_ofi_analysis['ofi_strong']['count']} trades, WR={wr:.1f}%, P&L=${long_ofi_analysis['ofi_strong']['pnl']:.2f}")

results["questions"]["why_long_losing"] = {
    "total_trades": len(long_trades),
    "total_pnl": long_pnl,
    "win_rate": len(long_wins)/len(long_trades)*100 if long_trades else 0,
    "price_analysis": long_price_analysis,
    "ofi_analysis": long_ofi_analysis
}

print()

# ============================================================================
# QUESTION 2: WHY ARE SHORT TRADES WINNING?
# ============================================================================
print("=" * 80)
print("QUESTION 2: WHY ARE SHORT TRADES WINNING?")
print("=" * 80)

short_pnl = sum(t.get("net_pnl", t.get("realized_pnl", t.get("pnl", 0))) or 0 for t in short_trades)
short_wins = [t for t in short_trades if (t.get("net_pnl", t.get("realized_pnl", t.get("pnl", 0))) or 0) > 0]
short_losses = [t for t in short_trades if (t.get("net_pnl", t.get("realized_pnl", t.get("pnl", 0))) or 0) < 0]

print(f"\n📈 SHORT Trade Performance:")
print(f"   Total P&L: ${short_pnl:.2f}")
print(f"   Wins: {len(short_wins)} ({len(short_wins)/len(short_trades)*100:.1f}%)")
print(f"   Losses: {len(short_losses)} ({len(short_losses)/len(short_trades)*100:.1f}%)")

# Analyze price direction for SHORT trades
short_price_analysis = {
    "price_went_up": 0,
    "price_went_down": 0,
    "price_stayed_same": 0,
    "avg_price_change_pct": []
}

for trade in short_trades:
    entry_price = float(trade.get("entry_price", 0) or 0)
    exit_price = float(trade.get("exit_price", 0) or 0)
    if entry_price > 0 and exit_price > 0:
        price_change_pct = ((exit_price - entry_price) / entry_price) * 100
        short_price_analysis["avg_price_change_pct"].append(price_change_pct)
        if price_change_pct > 0.1:
            short_price_analysis["price_went_up"] += 1
        elif price_change_pct < -0.1:
            short_price_analysis["price_went_down"] += 1
        else:
            short_price_analysis["price_stayed_same"] += 1

if short_price_analysis["avg_price_change_pct"]:
    avg_price_change = mean(short_price_analysis["avg_price_change_pct"])
    print(f"\n   💡 Price Action Analysis:")
    print(f"      Average price change: {avg_price_change:+.2f}%")
    print(f"      Price went UP: {short_price_analysis['price_went_up']} ({short_price_analysis['price_went_up']/len(short_trades)*100:.1f}%)")
    print(f"      Price went DOWN: {short_price_analysis['price_went_down']} ({short_price_analysis['price_went_down']/len(short_trades)*100:.1f}%)")

# Analyze OFI at entry for SHORT trades
short_ofi_analysis = {
    "ofi_positive": {"count": 0, "wins": 0, "pnl": 0},
    "ofi_negative": {"count": 0, "wins": 0, "pnl": 0},
    "ofi_weak": {"count": 0, "wins": 0, "pnl": 0},
    "ofi_strong": {"count": 0, "wins": 0, "pnl": 0},
    "ofi_aligned": {"count": 0, "wins": 0, "pnl": 0},
    "ofi_misaligned": {"count": 0, "wins": 0, "pnl": 0}
}

for trade in short_trades:
    ofi = trade.get("ofi_score") or trade.get("ofi") or 0
    if isinstance(ofi, (int, float)):
        ofi_value = float(ofi)
        pnl = float(trade.get("net_pnl") or trade.get("realized_pnl") or trade.get("pnl") or 0)
        is_win = pnl > 0
        
        if ofi_value > 0.01:
            short_ofi_analysis["ofi_positive"]["count"] += 1
            if is_win:
                short_ofi_analysis["ofi_positive"]["wins"] += 1
            short_ofi_analysis["ofi_positive"]["pnl"] += pnl
        elif ofi_value < -0.01:
            short_ofi_analysis["ofi_negative"]["count"] += 1
            if is_win:
                short_ofi_analysis["ofi_negative"]["wins"] += 1
            short_ofi_analysis["ofi_negative"]["pnl"] += pnl
        
        ofi_abs = abs(ofi_value)
        if ofi_abs < 0.3:
            short_ofi_analysis["ofi_weak"]["count"] += 1
            if is_win:
                short_ofi_analysis["ofi_weak"]["wins"] += 1
            short_ofi_analysis["ofi_weak"]["pnl"] += pnl
        elif ofi_abs >= 0.5:
            short_ofi_analysis["ofi_strong"]["count"] += 1
            if is_win:
                short_ofi_analysis["ofi_strong"]["wins"] += 1
            short_ofi_analysis["ofi_strong"]["pnl"] += pnl
        
        # OFI alignment (OFI negative = selling pressure = should be SHORT)
        if ofi_value < -0.01:  # OFI negative = selling pressure = aligned with SHORT
            short_ofi_analysis["ofi_aligned"]["count"] += 1
            if is_win:
                short_ofi_analysis["ofi_aligned"]["wins"] += 1
            short_ofi_analysis["ofi_aligned"]["pnl"] += pnl
        elif ofi_value > 0.01:  # OFI positive = buying pressure = misaligned with SHORT
            short_ofi_analysis["ofi_misaligned"]["count"] += 1
            if is_win:
                short_ofi_analysis["ofi_misaligned"]["wins"] += 1
            short_ofi_analysis["ofi_misaligned"]["pnl"] += pnl

print(f"\n   📊 OFI Analysis for SHORT Trades:")
if short_ofi_analysis["ofi_positive"]["count"] > 0:
    wr = short_ofi_analysis["ofi_positive"]["wins"] / short_ofi_analysis["ofi_positive"]["count"] * 100
    print(f"      OFI Positive (misaligned): {short_ofi_analysis['ofi_positive']['count']} trades, WR={wr:.1f}%, P&L=${short_ofi_analysis['ofi_positive']['pnl']:.2f}")
if short_ofi_analysis["ofi_negative"]["count"] > 0:
    wr = short_ofi_analysis["ofi_negative"]["wins"] / short_ofi_analysis["ofi_negative"]["count"] * 100
    print(f"      OFI Negative (aligned): {short_ofi_analysis['ofi_negative']['count']} trades, WR={wr:.1f}%, P&L=${short_ofi_analysis['ofi_negative']['pnl']:.2f}")
if short_ofi_analysis["ofi_weak"]["count"] > 0:
    wr = short_ofi_analysis["ofi_weak"]["wins"] / short_ofi_analysis["ofi_weak"]["count"] * 100
    print(f"      Weak OFI (<0.3): {short_ofi_analysis['ofi_weak']['count']} trades, WR={wr:.1f}%, P&L=${short_ofi_analysis['ofi_weak']['pnl']:.2f}")
if short_ofi_analysis["ofi_strong"]["count"] > 0:
    wr = short_ofi_analysis["ofi_strong"]["wins"] / short_ofi_analysis["ofi_strong"]["count"] * 100
    print(f"      Strong OFI (≥0.5): {short_ofi_analysis['ofi_strong']['count']} trades, WR={wr:.1f}%, P&L=${short_ofi_analysis['ofi_strong']['pnl']:.2f}")

results["questions"]["why_short_winning"] = {
    "total_trades": len(short_trades),
    "total_pnl": short_pnl,
    "win_rate": len(short_wins)/len(short_trades)*100 if short_trades else 0,
    "price_analysis": short_price_analysis,
    "ofi_analysis": short_ofi_analysis
}

print()

# ============================================================================
# QUESTION 3: WHY DOES OFI WORK BETTER THAN SENTIMENT?
# ============================================================================
print("=" * 80)
print("QUESTION 3: WHY DOES OFI WORK BETTER THAN SENTIMENT?")
print("=" * 80)

# Analyze by strategy
strategy_analysis = defaultdict(lambda: {"trades": [], "pnl": 0, "wins": 0, "losses": 0})

for trade in closed_trades:
    strategy = trade.get("strategy", "unknown")
    pnl = float(trade.get("net_pnl") or trade.get("realized_pnl") or trade.get("pnl") or 0)
    strategy_analysis[strategy]["trades"].append(trade)
    strategy_analysis[strategy]["pnl"] += pnl
    if pnl > 0:
        strategy_analysis[strategy]["wins"] += 1
    else:
        strategy_analysis[strategy]["losses"] += 1

print(f"\n📊 Strategy Performance Comparison:")

# Find OFI-based strategy
ofi_strategy = None
sentiment_strategy = None

for strategy, data in strategy_analysis.items():
    if "ofi" in strategy.lower() or "alpha-ofi" in strategy.lower():
        ofi_strategy = (strategy, data)
    if "sentiment" in strategy.lower():
        sentiment_strategy = (strategy, data)

if ofi_strategy:
    name, data = ofi_strategy
    total = len(data["trades"])
    wr = data["wins"] / total * 100 if total > 0 else 0
    ev = data["pnl"] / total if total > 0 else 0
    print(f"\n   ✅ {name}:")
    print(f"      Trades: {total}")
    print(f"      P&L: ${data['pnl']:.2f}")
    print(f"      Win Rate: {wr:.1f}%")
    print(f"      Expectancy: ${ev:.2f} per trade")
    
    # Analyze OFI values in OFI strategy trades
    ofi_values = []
    for trade in data["trades"][:50]:  # Sample first 50
        ofi = trade.get("ofi_score") or trade.get("ofi") or 0
        if isinstance(ofi, (int, float)) and ofi != 0:
            ofi_values.append(abs(float(ofi)))
    
    if ofi_values:
        print(f"      OFI Values: avg={mean(ofi_values):.3f}, median={median(ofi_values):.3f}")

if sentiment_strategy:
    name, data = sentiment_strategy
    total = len(data["trades"])
    wr = data["wins"] / total * 100 if total > 0 else 0
    ev = data["pnl"] / total if total > 0 else 0
    print(f"\n   ❌ {name}:")
    print(f"      Trades: {total}")
    print(f"      P&L: ${data['pnl']:.2f}")
    print(f"      Win Rate: {wr:.1f}%")
    print(f"      Expectancy: ${ev:.2f} per trade")

print()

# ============================================================================
# QUESTION 4: WHAT PATTERNS CAN WE LEVERAGE?
# ============================================================================
print("=" * 80)
print("QUESTION 4: WHAT PATTERNS IN THE DATA CAN WE LEVERAGE?")
print("=" * 80)

# Analyze OFI ranges by direction
ofi_range_analysis = defaultdict(lambda: {
    "LONG": {"trades": 0, "wins": 0, "pnl": 0},
    "SHORT": {"trades": 0, "wins": 0, "pnl": 0}
})

for trade in closed_trades:
    direction = trade.get("direction", "").upper()
    if direction not in ["LONG", "SHORT", "long"]:
        continue
    
    ofi = trade.get("ofi_score") or trade.get("ofi") or 0
    if isinstance(ofi, (int, float)):
        ofi_abs = abs(float(ofi))
        pnl = float(trade.get("net_pnl") or trade.get("realized_pnl") or trade.get("pnl") or 0)
        
        # Categorize OFI
        if ofi_abs < 0.3:
            bucket = "weak (<0.3)"
        elif ofi_abs < 0.5:
            bucket = "moderate (0.3-0.5)"
        elif ofi_abs < 0.7:
            bucket = "strong (0.5-0.7)"
        elif ofi_abs < 0.9:
            bucket = "very_strong (0.7-0.9)"
        else:
            bucket = "extreme (≥0.9)"
        
        dir_key = "LONG" if direction in ["LONG", "long"] else "SHORT"
        ofi_range_analysis[bucket][dir_key]["trades"] += 1
        if pnl > 0:
            ofi_range_analysis[bucket][dir_key]["wins"] += 1
        ofi_range_analysis[bucket][dir_key]["pnl"] += pnl

print(f"\n📊 OFI Range Performance by Direction:")
print(f"{'OFI Range':<20} {'LONG WR%':>10} {'LONG P&L':>12} {'SHORT WR%':>11} {'SHORT P&L':>12}")
print("-" * 80)

for bucket in ["weak (<0.3)", "moderate (0.3-0.5)", "strong (0.5-0.7)", "very_strong (0.7-0.9)", "extreme (≥0.9)"]:
    if bucket in ofi_range_analysis:
        long_data = ofi_range_analysis[bucket]["LONG"]
        short_data = ofi_range_analysis[bucket]["SHORT"]
        
        long_wr = long_data["wins"] / long_data["trades"] * 100 if long_data["trades"] > 0 else 0
        short_wr = short_data["wins"] / short_data["trades"] * 100 if short_data["trades"] > 0 else 0
        
        print(f"{bucket:<20} {long_wr:>9.1f}% ${long_data['pnl']:>10.2f} {short_wr:>10.1f}% ${short_data['pnl']:>11.2f}")

results["questions"]["leverage_patterns"] = {
    "ofi_range_analysis": dict(ofi_range_analysis)
}

print()

# ============================================================================
# QUESTION 5: HOW TO IMPROVE OFI PREDICTIONS?
# ============================================================================
print("=" * 80)
print("QUESTION 5: HOW CAN WE IMPROVE OFI PREDICTIONS?")
print("=" * 80)

# Analyze what makes OFI signals successful
successful_ofi_patterns = []
failed_ofi_patterns = []

for trade in closed_trades:
    ofi = trade.get("ofi_score") or trade.get("ofi") or 0
    direction = trade.get("direction", "").upper()
    pnl = float(trade.get("net_pnl") or trade.get("realized_pnl") or trade.get("pnl") or 0)
    entry_price = float(trade.get("entry_price", 0) or 0)
    exit_price = float(trade.get("exit_price", 0) or 0)
    
    if isinstance(ofi, (int, float)) and ofi != 0 and entry_price > 0 and exit_price > 0:
        ofi_value = float(ofi)
        ofi_abs = abs(ofi_value)
        price_change_pct = ((exit_price - entry_price) / entry_price) * 100
        
        # Check alignment
        is_aligned = (ofi_value > 0.01 and direction in ["LONG", "long"]) or (ofi_value < -0.01 and direction == "SHORT")
        
        pattern = {
            "direction": direction,
            "ofi_value": ofi_value,
            "ofi_abs": ofi_abs,
            "is_aligned": is_aligned,
            "price_change_pct": price_change_pct,
            "pnl": pnl,
            "is_win": pnl > 0
        }
        
        if pnl > 0:
            successful_ofi_patterns.append(pattern)
        else:
            failed_ofi_patterns.append(pattern)

print(f"\n📊 Successful OFI Patterns: {len(successful_ofi_patterns)}")
if successful_ofi_patterns:
    avg_ofi = mean([p["ofi_abs"] for p in successful_ofi_patterns])
    aligned_pct = sum(1 for p in successful_ofi_patterns if p["is_aligned"]) / len(successful_ofi_patterns) * 100
    print(f"   Average OFI strength: {avg_ofi:.3f}")
    print(f"   Alignment rate: {aligned_pct:.1f}%")
    
    # By direction
    long_success = [p for p in successful_ofi_patterns if p["direction"] in ["LONG", "long"]]
    short_success = [p for p in successful_ofi_patterns if p["direction"] == "SHORT"]
    if long_success:
        print(f"   LONG successful: avg OFI={mean([p['ofi_abs'] for p in long_success]):.3f}")
    if short_success:
        print(f"   SHORT successful: avg OFI={mean([p['ofi_abs'] for p in short_success]):.3f}")

print(f"\n📊 Failed OFI Patterns: {len(failed_ofi_patterns)}")
if failed_ofi_patterns:
    avg_ofi = mean([p["ofi_abs"] for p in failed_ofi_patterns])
    aligned_pct = sum(1 for p in failed_ofi_patterns if p["is_aligned"]) / len(failed_ofi_patterns) * 100
    print(f"   Average OFI strength: {avg_ofi:.3f}")
    print(f"   Alignment rate: {aligned_pct:.1f}%")
    
    # By direction
    long_failed = [p for p in failed_ofi_patterns if p["direction"] in ["LONG", "long"]]
    short_failed = [p for p in failed_ofi_patterns if p["direction"] == "SHORT"]
    if long_failed:
        print(f"   LONG failed: avg OFI={mean([p['ofi_abs'] for p in long_failed]):.3f}")
    if short_failed:
        print(f"   SHORT failed: avg OFI={mean([p['ofi_abs'] for p in short_failed]):.3f}")

results["questions"]["improve_ofi"] = {
    "successful_patterns": len(successful_ofi_patterns),
    "failed_patterns": len(failed_ofi_patterns),
    "success_avg_ofi": mean([p["ofi_abs"] for p in successful_ofi_patterns]) if successful_ofi_patterns else 0,
    "failed_avg_ofi": mean([p["ofi_abs"] for p in failed_ofi_patterns]) if failed_ofi_patterns else 0
}

print()

# ============================================================================
# GENERATE INSIGHTS AND RECOMMENDATIONS
# ============================================================================
print("=" * 80)
print("KEY INSIGHTS & RECOMMENDATIONS")
print("=" * 80)

insights = []

# Insight 1: Market Direction Bias
if long_price_analysis.get("avg_price_change_pct"):
    avg_long_price_change = mean(long_price_analysis["avg_price_change_pct"])
    if avg_long_price_change < -0.1:
        insights.append({
            "type": "market_direction",
            "finding": f"Market has been trending DOWN during LONG trades (avg {avg_long_price_change:.2f}%)",
            "explanation": "This explains why LONG trades are losing - we're buying into a downtrend",
            "recommendation": "Consider market trend before entering LONG positions, or wait for trend reversal signals"
        })

# Insight 2: OFI Alignment Matters
if long_ofi_analysis["ofi_aligned"]["count"] > 0 and long_ofi_analysis["ofi_misaligned"]["count"] > 0:
    aligned_wr = long_ofi_analysis["ofi_aligned"]["wins"] / long_ofi_analysis["ofi_aligned"]["count"] * 100
    misaligned_wr = long_ofi_analysis["ofi_misaligned"]["wins"] / long_ofi_analysis["ofi_misaligned"]["count"] * 100
    if aligned_wr > misaligned_wr + 5:
        insights.append({
            "type": "ofi_alignment",
            "finding": f"OFI alignment matters: Aligned LONG trades have {aligned_wr:.1f}% WR vs {misaligned_wr:.1f}% for misaligned",
            "explanation": "When OFI is positive (buying pressure), LONG trades work better",
            "recommendation": "Require OFI > 0.01 for LONG trades, OFI < -0.01 for SHORT trades"
        })

# Insight 3: Weak OFI Works for SHORT
if short_ofi_analysis["ofi_weak"]["count"] > 0:
    weak_wr = short_ofi_analysis["ofi_weak"]["wins"] / short_ofi_analysis["ofi_weak"]["count"] * 100
    if weak_wr > 50:
        insights.append({
            "type": "weak_ofi_short",
            "finding": f"Weak OFI (<0.3) works well for SHORT trades: {weak_wr:.1f}% WR",
            "explanation": "Even weak selling pressure (negative OFI) predicts price drops well",
            "recommendation": "For SHORT trades, can accept lower OFI thresholds (even <0.3)"
        })

# Insight 4: Strong OFI Doesn't Help LONG
if long_ofi_analysis["ofi_strong"]["count"] > 0:
    strong_wr = long_ofi_analysis["ofi_strong"]["wins"] / long_ofi_analysis["ofi_strong"]["count"] * 100
    if strong_wr < 40:
        insights.append({
            "type": "strong_ofi_long",
            "finding": f"Even strong OFI (≥0.5) doesn't help LONG trades: {strong_wr:.1f}% WR",
            "explanation": "Strong buying pressure doesn't guarantee price goes up (market may be in downtrend)",
            "recommendation": "For LONG trades, need additional confirmation beyond just OFI strength"
        })

for i, insight in enumerate(insights, 1):
    print(f"\n💡 Insight {i}: {insight['type'].upper().replace('_', ' ')}")
    print(f"   Finding: {insight['finding']}")
    print(f"   Explanation: {insight['explanation']}")
    print(f"   Recommendation: {insight['recommendation']}")

results["insights"] = insights

# Save results
output_file = Path("feature_store/deep_why_analysis.json")
output_file.parent.mkdir(parents=True, exist_ok=True)
with open(output_file, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n💾 Full analysis saved to: {output_file}")

print("\n" + "=" * 80)
print("✅ DEEP 'WHY' ANALYSIS COMPLETE")
print("=" * 80)
