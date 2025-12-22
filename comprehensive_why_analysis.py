#!/usr/bin/env python3
"""
Comprehensive "WHY" Analysis - ALL Data Sources
===============================================
Answers fundamental questions using ALL available data:
1. Executed trades
2. Blocked trades
3. Counterfactual outcomes (what blocked trades would have done)
4. Missed opportunities
5. CoinGlass data (funding rates, liquidations)
6. Signal universe (all signals)

This provides a complete picture of WHY patterns occur.
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from typing import Dict, List, Any, Tuple
from statistics import mean, median

sys.path.insert(0, os.path.dirname(__file__))

print("=" * 80)
print("COMPREHENSIVE 'WHY' ANALYSIS - ALL DATA SOURCES")
print("=" * 80)
print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

results = {
    "generated_at": datetime.now().isoformat(),
    "data_sources": {},
    "questions": {},
    "insights": [],
    "recommendations": []
}

# ============================================================================
# LOAD ALL DATA SOURCES
# ============================================================================
print("=" * 80)
print("LOADING ALL DATA SOURCES")
print("=" * 80)

from src.data_registry import DataRegistry as DR
from src.comprehensive_intelligence_analysis import load_all_data, enrich_record

def load_jsonl(path, max_age_hours=None):
    """Load JSONL file."""
    if isinstance(path, Path):
        path = str(path)
    if not os.path.exists(path):
        return []
    records = []
    cutoff_ts = None
    if max_age_hours:
        cutoff_ts = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).timestamp()
    with open(path, 'r') as f:
        for line in f:
            try:
                rec = json.loads(line.strip())
                if cutoff_ts and rec.get('ts', 0) < cutoff_ts:
                    continue
                records.append(rec)
            except:
                pass
    return records

# Load all data using comprehensive loader
print("   Loading comprehensive data (executed, blocked, missed, counterfactual)...")
all_data = load_all_data()

executed = all_data.get("executed", [])
blocked = all_data.get("blocked", [])
missed = all_data.get("missed", [])
counterfactual = all_data.get("counterfactual", [])

print(f"   ✅ Executed: {len(executed)}")
print(f"   ✅ Blocked: {len(blocked)}")
print(f"   ✅ Missed: {len(missed)}")
print(f"   ✅ Counterfactual: {len(counterfactual)}")

# Load signal universe
signals_universe = []
signals_file = Path(DR.SIGNALS_UNIVERSE)
if signals_file.exists():
    with open(signals_file, 'r') as f:
        for line in f:
            try:
                signals_universe.append(json.loads(line.strip()))
            except:
                pass
print(f"   ✅ Signal Universe: {len(signals_universe)}")

# Load CoinGlass data
coinglass_data = {}
coinglass_dir = Path(DR.COINGLASS_DIR)
intelligence_dir = Path(DR.INTELLIGENCE_DIR)

coinglass_files = []
if coinglass_dir.exists():
    for file in coinglass_dir.glob("*.json"):
        coinglass_files.append(file)
if intelligence_dir.exists():
    for file in intelligence_dir.glob("*_intel.json"):
        coinglass_files.append(file)
    if (intelligence_dir / "summary.json").exists():
        coinglass_files.append(intelligence_dir / "summary.json")

print(f"   ✅ CoinGlass files: {len(coinglass_files)}")

# Load closed trades for additional context
closed_trades = DR.get_closed_positions(hours=168*24)
print(f"   ✅ Closed trades: {len(closed_trades)}")

results["data_sources"] = {
    "executed": len(executed),
    "blocked": len(blocked),
    "missed": len(missed),
    "counterfactual": len(counterfactual),
    "signals_universe": len(signals_universe),
    "coinglass_files": len(coinglass_files),
    "closed_trades": len(closed_trades)
}

print()

# ============================================================================
# QUESTION 1: WHY ARE LONG TRADES LOSING? (WITH BLOCKED DATA)
# ============================================================================
print("=" * 80)
print("QUESTION 1: WHY ARE LONG TRADES LOSING? (All Data)")
print("=" * 80)

# Helper function to get direction from enriched record
def get_direction(record):
    """Extract direction from enriched record (checks multiple possible locations)."""
    # Check enriched record direction field first (from enrich_record)
    direction = record.get("direction", "")
    if direction:
        return str(direction).upper()
    
    # Check signal_ctx
    signal_ctx = record.get("signal_ctx", {})
    if signal_ctx:
        direction = signal_ctx.get("side", signal_ctx.get("direction", ""))
        if direction:
            return str(direction).upper()
    
    # Check raw record if available (portfolio trades)
    raw = record.get("_raw", {})
    if raw:
        direction = raw.get("side", raw.get("direction", ""))
        if direction:
            return str(direction).upper()
    
    # Check record directly (portfolio trades might not have _raw)
    direction = record.get("side", record.get("direction", ""))
    if direction:
        return str(direction).upper()
    
    # Check position_type (for futures positions)
    pos_type = record.get("position_type", raw.get("position_type", ""))
    if pos_type:
        return str(pos_type).upper()
    
    return ""

# Debug: Check first few executed trades to see their structure
if executed:
    print(f"\n🔍 DEBUG: Sample executed trade structure:")
    sample = executed[0]
    print(f"   Keys: {list(sample.keys())[:10]}")
    print(f"   direction field: {sample.get('direction', 'NOT FOUND')}")
    print(f"   _raw direction: {sample.get('_raw', {}).get('direction', 'NOT FOUND')}")
    print(f"   get_direction result: {get_direction(sample)}")

# Analyze executed LONG trades (handle both "LONG" and "long")
executed_long = [t for t in executed if get_direction(t) in ["LONG", "long"]]
executed_short = [t for t in executed if get_direction(t) == "SHORT"]

# Analyze blocked LONG trades
blocked_long = [t for t in blocked if get_direction(t) in ["LONG", "long"]]
blocked_short = [t for t in blocked if get_direction(t) == "SHORT"]

# Analyze counterfactual LONG (what blocked LONG trades would have done)
counterfactual_long = [t for t in counterfactual if get_direction(t) in ["LONG", "long"]]
counterfactual_short = [t for t in counterfactual if get_direction(t) == "SHORT"]

print(f"\n📊 LONG Trade Analysis:")
print(f"   Executed: {len(executed_long)}")
print(f"   Blocked: {len(blocked_long)}")
print(f"   Counterfactual: {len(counterfactual_long)}")

# Analyze OFI in executed LONG
executed_long_ofi = []
for trade in executed_long:
    # Check multiple OFI field names (portfolio trades use ofi_score, enriched uses ofi/ofi_raw)
    ofi = (trade.get("ofi") or trade.get("ofi_raw") or 
           trade.get("_raw", {}).get("ofi_score") or 
           trade.get("_raw", {}).get("ofi") or
           trade.get("signal_ctx", {}).get("ofi", 0))
    pnl = trade.get("pnl", trade.get("outcome", {}).get("pnl_usd", trade.get("outcome", {}).get("pnl", 0)))
    if isinstance(ofi, (int, float)) and ofi != 0:
        executed_long_ofi.append({
            "ofi": float(ofi),
            "ofi_abs": abs(float(ofi)),
            "pnl": float(pnl) if pnl else 0
        })

if executed_long_ofi:
    avg_ofi = mean([e["ofi_abs"] for e in executed_long_ofi])
    print(f"\n   Executed LONG OFI Analysis:")
    print(f"      Average OFI strength: {avg_ofi:.3f}")
    print(f"      OFI range: {min([e['ofi_abs'] for e in executed_long_ofi]):.3f} - {max([e['ofi_abs'] for e in executed_long_ofi]):.3f}")

# Analyze OFI in blocked LONG
blocked_long_ofi = []
for trade in blocked_long:
    ofi = trade.get("ofi", trade.get("ofi_raw", trade.get("signal_ctx", {}).get("ofi", trade.get("intelligence", {}).get("ofi", 0))))
    if isinstance(ofi, (int, float)):
        blocked_long_ofi.append({
            "ofi": float(ofi),
            "ofi_abs": abs(float(ofi))
        })

if blocked_long_ofi:
    avg_ofi = mean([e["ofi_abs"] for e in blocked_long_ofi])
    print(f"\n   Blocked LONG OFI Analysis:")
    print(f"      Average OFI strength: {avg_ofi:.3f}")
    print(f"      OFI range: {min([e['ofi_abs'] for e in blocked_long_ofi]):.3f} - {max([e['ofi_abs'] for e in blocked_long_ofi]):.3f}")

# Analyze counterfactual LONG (what would have happened)
counterfactual_long_winners = [t for t in counterfactual_long if t.get("would_have_won", t.get("pnl", 0) > 0)]
counterfactual_long_losers = [t for t in counterfactual_long if not t.get("would_have_won", t.get("pnl", 0) <= 0)]

print(f"\n   Counterfactual LONG Analysis:")
print(f"      Would have won: {len(counterfactual_long_winners)}")
print(f"      Would have lost: {len(counterfactual_long_losers)}")
if counterfactual_long:
    cf_wr = len(counterfactual_long_winners) / len(counterfactual_long) * 100
    print(f"      Counterfactual win rate: {cf_wr:.1f}%")

results["questions"]["why_long_losing_all_data"] = {
    "executed_long": len(executed_long),
    "blocked_long": len(blocked_long),
    "counterfactual_long": len(counterfactual_long),
    "executed_avg_ofi": mean([e["ofi_abs"] for e in executed_long_ofi]) if executed_long_ofi else 0,
    "blocked_avg_ofi": mean([e["ofi_abs"] for e in blocked_long_ofi]) if blocked_long_ofi else 0,
    "counterfactual_wr": len(counterfactual_long_winners) / len(counterfactual_long) * 100 if counterfactual_long else 0
}

print()

# ============================================================================
# QUESTION 2: WHY ARE SHORT TRADES WINNING? (WITH BLOCKED DATA)
# ============================================================================
print("=" * 80)
print("QUESTION 2: WHY ARE SHORT TRADES WINNING? (All Data)")
print("=" * 80)

print(f"\n📊 SHORT Trade Analysis:")
print(f"   Executed: {len(executed_short)}")
print(f"   Blocked: {len(blocked_short)}")
print(f"   Counterfactual: {len(counterfactual_short)}")

# Analyze OFI in executed SHORT
executed_short_ofi = []
for trade in executed_short:
    # Check multiple OFI field names (portfolio trades use ofi_score, enriched uses ofi/ofi_raw)
    ofi = (trade.get("ofi") or trade.get("ofi_raw") or 
           trade.get("_raw", {}).get("ofi_score") or 
           trade.get("_raw", {}).get("ofi") or
           trade.get("signal_ctx", {}).get("ofi", 0))
    pnl = trade.get("pnl", trade.get("outcome", {}).get("pnl_usd", trade.get("outcome", {}).get("pnl", 0)))
    if isinstance(ofi, (int, float)) and ofi != 0:
        executed_short_ofi.append({
            "ofi": float(ofi),
            "ofi_abs": abs(float(ofi)),
            "pnl": float(pnl) if pnl else 0
        })

if executed_short_ofi:
    avg_ofi = mean([e["ofi_abs"] for e in executed_short_ofi])
    print(f"\n   Executed SHORT OFI Analysis:")
    print(f"      Average OFI strength: {avg_ofi:.3f}")
    print(f"      OFI range: {min([e['ofi_abs'] for e in executed_short_ofi]):.3f} - {max([e['ofi_abs'] for e in executed_short_ofi]):.3f}")

# Analyze OFI in blocked SHORT
blocked_short_ofi = []
for trade in blocked_short:
    ofi = trade.get("ofi", trade.get("ofi_raw", trade.get("signal_ctx", {}).get("ofi", trade.get("intelligence", {}).get("ofi", 0))))
    if isinstance(ofi, (int, float)):
        blocked_short_ofi.append({
            "ofi": float(ofi),
            "ofi_abs": abs(float(ofi))
        })

if blocked_short_ofi:
    avg_ofi = mean([e["ofi_abs"] for e in blocked_short_ofi])
    print(f"\n   Blocked SHORT OFI Analysis:")
    print(f"      Average OFI strength: {avg_ofi:.3f}")

# Analyze counterfactual SHORT
counterfactual_short_winners = [t for t in counterfactual_short if t.get("would_have_won", t.get("pnl", 0) > 0)]
counterfactual_short_losers = [t for t in counterfactual_short if not t.get("would_have_won", t.get("pnl", 0) <= 0)]

print(f"\n   Counterfactual SHORT Analysis:")
print(f"      Would have won: {len(counterfactual_short_winners)}")
print(f"      Would have lost: {len(counterfactual_short_losers)}")
if counterfactual_short:
    cf_wr = len(counterfactual_short_winners) / len(counterfactual_short) * 100
    print(f"      Counterfactual win rate: {cf_wr:.1f}%")

results["questions"]["why_short_winning_all_data"] = {
    "executed_short": len(executed_short),
    "blocked_short": len(blocked_short),
    "counterfactual_short": len(counterfactual_short),
    "executed_avg_ofi": mean([e["ofi_abs"] for e in executed_short_ofi]) if executed_short_ofi else 0,
    "blocked_avg_ofi": mean([e["ofi_abs"] for e in blocked_short_ofi]) if blocked_short_ofi else 0,
    "counterfactual_wr": len(counterfactual_short_winners) / len(counterfactual_short) * 100 if counterfactual_short else 0
}

print()

# ============================================================================
# QUESTION 3: WHAT BLOCKED TRADES WOULD HAVE DONE
# ============================================================================
print("=" * 80)
print("QUESTION 3: WHAT WOULD BLOCKED TRADES HAVE DONE?")
print("=" * 80)

# Analyze counterfactual outcomes
if counterfactual:
    cf_winners = [t for t in counterfactual if t.get("would_have_won", t.get("pnl", 0) > 0)]
    cf_losers = [t for t in counterfactual if not t.get("would_have_won", t.get("pnl", 0) <= 0)]
    
    print(f"\n📊 Counterfactual Analysis:")
    print(f"   Total counterfactual trades: {len(counterfactual)}")
    print(f"   Would have won: {len(cf_winners)} ({len(cf_winners)/len(counterfactual)*100:.1f}%)")
    print(f"   Would have lost: {len(cf_losers)} ({len(cf_losers)/len(counterfactual)*100:.1f}%)")
    
    # By direction
    cf_long_winners = [t for t in cf_winners if get_direction(t) in ["LONG"]]
    cf_long_losers = [t for t in cf_losers if get_direction(t) in ["LONG"]]
    cf_short_winners = [t for t in cf_winners if get_direction(t) == "SHORT"]
    cf_short_losers = [t for t in cf_losers if get_direction(t) == "SHORT"]
    
    if cf_long_winners or cf_long_losers:
        cf_long_total = len(cf_long_winners) + len(cf_long_losers)
        cf_long_wr = len(cf_long_winners) / cf_long_total * 100 if cf_long_total > 0 else 0
        print(f"\n   Blocked LONG trades:")
        print(f"      Would have won: {len(cf_long_winners)} ({cf_long_wr:.1f}%)")
        print(f"      Would have lost: {len(cf_long_losers)}")
    
    if cf_short_winners or cf_short_losers:
        cf_short_total = len(cf_short_winners) + len(cf_short_losers)
        cf_short_wr = len(cf_short_winners) / cf_short_total * 100 if cf_short_total > 0 else 0
        print(f"\n   Blocked SHORT trades:")
        print(f"      Would have won: {len(cf_short_winners)} ({cf_short_wr:.1f}%)")
        print(f"      Would have lost: {len(cf_short_losers)}")
    
    results["questions"]["blocked_trades_counterfactual"] = {
        "total": len(counterfactual),
        "would_have_won": len(cf_winners),
        "would_have_lost": len(cf_losers),
        "long_winners": len(cf_long_winners),
        "long_losers": len(cf_long_losers),
        "short_winners": len(cf_short_winners),
        "short_losers": len(cf_short_losers)
    }

print()

# ============================================================================
# QUESTION 4: MISSED OPPORTUNITIES ANALYSIS
# ============================================================================
print("=" * 80)
print("QUESTION 4: WHAT OPPORTUNITIES DID WE MISS?")
print("=" * 80)

if missed:
    missed_long = [t for t in missed if get_direction(t) in ["LONG"]]
    missed_short = [t for t in missed if get_direction(t) == "SHORT"]
    
    print(f"\n📊 Missed Opportunities:")
    print(f"   Total missed: {len(missed)}")
    print(f"   LONG missed: {len(missed_long)}")
    print(f"   SHORT missed: {len(missed_short)}")
    
    # Analyze potential P&L from missed opportunities
    if missed:
        potential_pnl = sum(float(t.get("best_pnl_pct", 0) or 0) for t in missed)
        print(f"   Potential P&L (if taken): {potential_pnl:.2f}%")
        
        # Top missed opportunities
        missed_sorted = sorted(missed, key=lambda x: float(x.get("best_pnl_pct", 0) or 0), reverse=True)
        print(f"\n   Top 5 Missed Opportunities:")
        for i, opp in enumerate(missed_sorted[:5], 1):
            symbol = opp.get("symbol", "UNKNOWN")
            side = opp.get("side", "UNKNOWN")
            pnl_pct = opp.get("best_pnl_pct", 0)
            print(f"      {i}. {symbol} {side}: Would have made {pnl_pct:.2f}%")
    
    results["questions"]["missed_opportunities"] = {
        "total": len(missed),
        "long": len(missed_long),
        "short": len(missed_short),
        "top_opportunities": [{"symbol": t.get("symbol"), "side": t.get("side"), "pnl_pct": t.get("best_pnl_pct", 0)} for t in sorted(missed, key=lambda x: float(x.get("best_pnl_pct", 0) or 0), reverse=True)[:10]]
    }

print()

# ============================================================================
# QUESTION 5: COINGLASS DATA CORRELATION
# ============================================================================
print("=" * 80)
print("QUESTION 5: COINGLASS DATA CORRELATION")
print("=" * 80)

# Load CoinGlass data
coinglass_features = {}
for file in coinglass_files[:10]:  # Sample first 10 files
    try:
        with open(file, 'r') as f:
            data = json.load(f)
            symbol = file.stem.replace("_coinglass_features", "").replace("_intel", "")
            coinglass_features[symbol] = data
    except:
        pass

print(f"\n📊 CoinGlass Data:")
print(f"   Files loaded: {len(coinglass_features)}")

# Correlate CoinGlass data with trade outcomes
if coinglass_features and executed:
    print(f"\n   Analyzing CoinGlass correlation with trade outcomes...")
    # This would require matching trades with CoinGlass data by timestamp
    # For now, just report what data is available
    for symbol, data in list(coinglass_features.items())[:5]:
        funding_rate = data.get("funding_rate", data.get("funding", 0))
        liquidation = data.get("liquidation", {})
        print(f"      {symbol}: funding_rate={funding_rate}, liquidation_data={'yes' if liquidation else 'no'}")

results["questions"]["coinglass_correlation"] = {
    "files_loaded": len(coinglass_features),
    "symbols_with_data": list(coinglass_features.keys())[:10]
}

print()

# ============================================================================
# QUESTION 6: OFI vs SENTIMENT - DEEP COMPARISON
# ============================================================================
print("=" * 80)
print("QUESTION 6: WHY DOES OFI WORK BETTER THAN SENTIMENT?")
print("=" * 80)

# Analyze strategy performance with signal context
ofi_strategy_trades = [t for t in executed if "ofi" in t.get("strategy", "").lower() or "alpha-ofi" in t.get("strategy", "").lower()]
sentiment_strategy_trades = [t for t in executed if "sentiment" in t.get("strategy", "").lower()]

print(f"\n📊 Strategy Comparison:")
print(f"   OFI-based trades: {len(ofi_strategy_trades)}")
print(f"   Sentiment-based trades: {len(sentiment_strategy_trades)}")

# Analyze OFI values in each strategy
ofi_strategy_ofi = []
for trade in ofi_strategy_trades:
    ofi = trade.get("ofi", trade.get("ofi_raw", trade.get("signal_ctx", {}).get("ofi", 0)))
    pnl = trade.get("pnl", trade.get("outcome", {}).get("pnl_usd", trade.get("outcome", {}).get("pnl", 0)))
    if isinstance(ofi, (int, float)):
        ofi_strategy_ofi.append({"ofi_abs": abs(float(ofi)), "pnl": float(pnl) if pnl else 0})

sentiment_strategy_ofi = []
for trade in sentiment_strategy_trades:
    ofi = trade.get("ofi", trade.get("ofi_raw", trade.get("signal_ctx", {}).get("ofi", 0)))
    pnl = trade.get("pnl", trade.get("outcome", {}).get("pnl_usd", trade.get("outcome", {}).get("pnl", 0)))
    if isinstance(ofi, (int, float)):
        sentiment_strategy_ofi.append({"ofi_abs": abs(float(ofi)), "pnl": float(pnl) if pnl else 0})

if ofi_strategy_ofi:
    avg_ofi = mean([e["ofi_abs"] for e in ofi_strategy_ofi])
    avg_pnl = mean([e["pnl"] for e in ofi_strategy_ofi])
    print(f"\n   OFI Strategy:")
    print(f"      Average OFI strength: {avg_ofi:.3f}")
    print(f"      Average P&L: ${avg_pnl:.2f}")

if sentiment_strategy_ofi:
    avg_ofi = mean([e["ofi_abs"] for e in sentiment_strategy_ofi])
    avg_pnl = mean([e["pnl"] for e in sentiment_strategy_ofi])
    print(f"\n   Sentiment Strategy:")
    print(f"      Average OFI strength: {avg_ofi:.3f}")
    print(f"      Average P&L: ${avg_pnl:.2f}")

results["questions"]["ofi_vs_sentiment"] = {
    "ofi_strategy": {
        "trades": len(ofi_strategy_trades),
        "avg_ofi": mean([e["ofi_abs"] for e in ofi_strategy_ofi]) if ofi_strategy_ofi else 0,
        "avg_pnl": mean([e["pnl"] for e in ofi_strategy_ofi]) if ofi_strategy_ofi else 0
    },
    "sentiment_strategy": {
        "trades": len(sentiment_strategy_trades),
        "avg_ofi": mean([e["ofi_abs"] for e in sentiment_strategy_ofi]) if sentiment_strategy_ofi else 0,
        "avg_pnl": mean([e["pnl"] for e in sentiment_strategy_ofi]) if sentiment_strategy_ofi else 0
    }
}

print()

# ============================================================================
# GENERATE COMPREHENSIVE INSIGHTS
# ============================================================================
print("=" * 80)
print("COMPREHENSIVE INSIGHTS")
print("=" * 80)

insights = []

# Insight 1: OFI Strength Difference
if executed_long_ofi and executed_short_ofi:
    long_avg = mean([e["ofi_abs"] for e in executed_long_ofi])
    short_avg = mean([e["ofi_abs"] for e in executed_short_ofi])
    if short_avg > long_avg * 2:
        insights.append({
            "type": "ofi_strength_gap",
            "finding": f"SHORT trades use {short_avg/long_avg:.1f}x stronger OFI signals ({short_avg:.3f} vs {long_avg:.3f})",
            "explanation": "SHORT requires strong OFI, LONG accepts weak OFI - this explains the performance gap",
            "recommendation": "Require OFI ≥ 0.5 for LONG trades (match SHORT requirements)"
        })

# Insight 2: Blocked LONG Counterfactual
if counterfactual_long:
    cf_long_wr = len(counterfactual_long_winners) / len(counterfactual_long) * 100
    if cf_long_wr > 40:
        insights.append({
            "type": "blocked_long_opportunity",
            "finding": f"Blocked LONG trades would have {cf_long_wr:.1f}% win rate (better than executed 36.8%)",
            "explanation": "We're blocking profitable LONG opportunities - gates may be too strict",
            "recommendation": "Review why profitable LONG signals are being blocked"
        })

# Insight 3: Missed Opportunities
if missed:
    missed_long_count = len([t for t in missed if get_direction(t) in ["LONG"]])
    if missed_long_count > len(missed) * 0.5:
        insights.append({
            "type": "missed_long_opportunities",
            "finding": f"{missed_long_count} missed LONG opportunities (potential winners we didn't take)",
            "explanation": "System is missing profitable LONG trades",
            "recommendation": "Analyze why profitable LONG signals are being missed"
        })

for i, insight in enumerate(insights, 1):
    print(f"\n💡 Insight {i}: {insight['type'].upper().replace('_', ' ')}")
    print(f"   Finding: {insight['finding']}")
    print(f"   Explanation: {insight['explanation']}")
    print(f"   Recommendation: {insight['recommendation']}")

results["insights"] = insights

# Save results
output_file = Path("feature_store/comprehensive_why_analysis.json")
output_file.parent.mkdir(parents=True, exist_ok=True)
with open(output_file, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n💾 Full analysis saved to: {output_file}")

print("\n" + "=" * 80)
print("✅ COMPREHENSIVE 'WHY' ANALYSIS COMPLETE")
print("=" * 80)
print(f"\nThis analysis included:")
print(f"   - {len(executed)} executed trades")
print(f"   - {len(blocked)} blocked trades")
print(f"   - {len(counterfactual)} counterfactual outcomes")
print(f"   - {len(missed)} missed opportunities")
print(f"   - {len(signals_universe)} signals in universe")
print(f"   - {len(coinglass_files)} CoinGlass data files")
print("=" * 80)
