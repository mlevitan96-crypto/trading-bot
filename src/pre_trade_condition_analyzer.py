#!/usr/bin/env python3
"""
Pre-Trade Condition Analyzer
Analyzes what market conditions PRECEDE profitable vs losing trades.

This is the learning component that answers:
"What intelligence signals appeared BEFORE our winning trades vs losing trades?"

Output feeds back into:
1. Trend Inception Detector - improves leading indicator weights
2. Intelligence Gate - adjusts confidence thresholds
3. Entry Flow - informs when to boost/suppress signals
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from pathlib import Path
from collections import defaultdict

ANALYSIS_OUTPUT = "feature_store/pre_trade_conditions.json"
LEARNING_RULES_OUTPUT = "feature_store/leading_indicator_rules.json"


def _now() -> datetime:
    return datetime.utcnow()


def load_trades() -> List[Dict]:
    """Load recent trades for analysis."""
    trades = []
    
    try:
        from src.data_registry import DataRegistry
        DR = DataRegistry()
        trades = DR.get_trades()
    except:
        positions_file = "logs/positions_futures.json"
        if os.path.exists(positions_file):
            try:
                with open(positions_file) as f:
                    data = json.load(f)
                trades = data.get("closed_positions", [])
            except:
                pass
    
    return trades


def load_intelligence_history() -> List[Dict]:
    """Load intelligence gate log for pre-trade conditions."""
    entries = []
    log_file = "logs/intelligence_gate.log"
    
    if os.path.exists(log_file):
        try:
            with open(log_file) as f:
                for line in f:
                    if line.strip():
                        entries.append({"raw": line.strip()})
        except:
            pass
    
    return entries


def load_coinglass_history() -> List[Dict]:
    """Load CoinGlass intelligence snapshots."""
    entries = []
    log_file = "logs/coinglass_intelligence.jsonl"
    
    if os.path.exists(log_file):
        try:
            with open(log_file) as f:
                for line in f:
                    if line.strip():
                        try:
                            entries.append(json.loads(line))
                        except:
                            pass
        except:
            pass
    
    return entries


def analyze_winning_vs_losing_conditions() -> Dict[str, Any]:
    """
    Core analysis: What conditions preceded winning trades vs losing trades?
    
    Returns breakdown of:
    - OFI levels before wins vs losses
    - Ensemble scores before wins vs losses
    - Funding rate conditions before wins vs losses
    - Session/time patterns
    - Direction preferences by symbol
    """
    trades = load_trades()
    
    if len(trades) < 20:
        return {"status": "insufficient_data", "trade_count": len(trades)}
    
    wins = [t for t in trades if float(t.get("realized_pnl", t.get("net_pnl", 0))) > 0]
    losses = [t for t in trades if float(t.get("realized_pnl", t.get("net_pnl", 0))) < 0]
    
    analysis = {
        "timestamp": _now().isoformat(),
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(trades) * 100 if trades else 0,
        "by_symbol": {},
        "by_direction": {"LONG": {"wins": 0, "losses": 0}, "SHORT": {"wins": 0, "losses": 0}},
        "by_ofi_bucket": {},
        "by_ensemble_bucket": {},
        "by_session": {},
        "timing_insights": [],
        "direction_bias_by_symbol": {}
    }
    
    for trade in trades:
        symbol = trade.get("symbol", "UNKNOWN")
        direction = trade.get("direction", "UNKNOWN")
        pnl = float(trade.get("realized_pnl", trade.get("net_pnl", 0)))
        is_win = pnl > 0
        
        if symbol not in analysis["by_symbol"]:
            analysis["by_symbol"][symbol] = {"wins": 0, "losses": 0, "total_pnl": 0, "by_direction": {}}
        
        if is_win:
            analysis["by_symbol"][symbol]["wins"] += 1
        else:
            analysis["by_symbol"][symbol]["losses"] += 1
        analysis["by_symbol"][symbol]["total_pnl"] += pnl
        
        if direction not in analysis["by_symbol"][symbol]["by_direction"]:
            analysis["by_symbol"][symbol]["by_direction"][direction] = {"wins": 0, "losses": 0, "pnl": 0}
        
        if is_win:
            analysis["by_symbol"][symbol]["by_direction"][direction]["wins"] += 1
        else:
            analysis["by_symbol"][symbol]["by_direction"][direction]["losses"] += 1
        analysis["by_symbol"][symbol]["by_direction"][direction]["pnl"] += pnl
        
        if direction in ["LONG", "SHORT"]:
            if is_win:
                analysis["by_direction"][direction]["wins"] += 1
            else:
                analysis["by_direction"][direction]["losses"] += 1
        
        ofi = trade.get("ofi_score", trade.get("ofi", 0))
        if ofi:
            bucket = categorize_ofi(ofi)
            if bucket not in analysis["by_ofi_bucket"]:
                analysis["by_ofi_bucket"][bucket] = {"wins": 0, "losses": 0, "pnl": 0}
            if is_win:
                analysis["by_ofi_bucket"][bucket]["wins"] += 1
            else:
                analysis["by_ofi_bucket"][bucket]["losses"] += 1
            analysis["by_ofi_bucket"][bucket]["pnl"] += pnl
        
        ensemble = trade.get("ensemble_score", trade.get("ensemble", 0))
        if ensemble:
            bucket = categorize_ensemble(ensemble)
            if bucket not in analysis["by_ensemble_bucket"]:
                analysis["by_ensemble_bucket"][bucket] = {"wins": 0, "losses": 0, "pnl": 0}
            if is_win:
                analysis["by_ensemble_bucket"][bucket]["wins"] += 1
            else:
                analysis["by_ensemble_bucket"][bucket]["losses"] += 1
            analysis["by_ensemble_bucket"][bucket]["pnl"] += pnl
    
    for symbol, data in analysis["by_symbol"].items():
        by_dir = data.get("by_direction", {})
        
        long_data = by_dir.get("LONG", {"wins": 0, "losses": 0, "pnl": 0})
        short_data = by_dir.get("SHORT", {"wins": 0, "losses": 0, "pnl": 0})
        
        long_wr = long_data["wins"] / (long_data["wins"] + long_data["losses"]) * 100 if (long_data["wins"] + long_data["losses"]) > 0 else 0
        short_wr = short_data["wins"] / (short_data["wins"] + short_data["losses"]) * 100 if (short_data["wins"] + short_data["losses"]) > 0 else 0
        
        if long_wr > short_wr + 10 and long_data["pnl"] > short_data["pnl"]:
            analysis["direction_bias_by_symbol"][symbol] = {
                "preferred": "LONG",
                "long_wr": long_wr,
                "short_wr": short_wr,
                "long_pnl": long_data["pnl"],
                "short_pnl": short_data["pnl"]
            }
        elif short_wr > long_wr + 10 and short_data["pnl"] > long_data["pnl"]:
            analysis["direction_bias_by_symbol"][symbol] = {
                "preferred": "SHORT",
                "long_wr": long_wr,
                "short_wr": short_wr,
                "long_pnl": long_data["pnl"],
                "short_pnl": short_data["pnl"]
            }
    
    return analysis


def categorize_ofi(ofi: float) -> str:
    """Categorize OFI score into bucket."""
    ofi = abs(ofi)
    if ofi < 0.3:
        return "weak"
    elif ofi < 0.5:
        return "moderate"
    elif ofi < 0.7:
        return "strong"
    elif ofi < 0.9:
        return "very_strong"
    else:
        return "extreme"


def categorize_ensemble(ensemble: float) -> str:
    """Categorize ensemble score into bucket."""
    if ensemble > 0.5:
        return "strong_bull"
    elif ensemble > 0.2:
        return "bull"
    elif ensemble > -0.2:
        return "neutral"
    elif ensemble > -0.5:
        return "bear"
    else:
        return "strong_bear"


def generate_leading_indicator_rules(analysis: Dict) -> List[Dict]:
    """
    Generate actionable rules from analysis.
    
    Rules like:
    - "For BNBUSDT, prefer SHORT over LONG (36% vs 18% WR)"
    - "When OFI is extreme, reduce size by 30%"
    """
    rules = []
    
    for symbol, bias in analysis.get("direction_bias_by_symbol", {}).items():
        preferred = bias["preferred"]
        opposite = "SHORT" if preferred == "LONG" else "LONG"
        rules.append({
            "type": "direction_preference",
            "symbol": symbol,
            "preferred_direction": preferred,
            "suppressed_direction": opposite,
            "confidence": abs(bias["long_wr"] - bias["short_wr"]) / 100,
            "pnl_advantage": abs(bias["long_pnl"] - bias["short_pnl"]),
            "action": f"boost_{preferred.lower()}_suppress_{opposite.lower()}"
        })
    
    for bucket, data in analysis.get("by_ofi_bucket", {}).items():
        total = data["wins"] + data["losses"]
        if total >= 10:
            wr = data["wins"] / total * 100
            avg_pnl = data["pnl"] / total
            
            if avg_pnl < -1.0 or wr < 15:
                rules.append({
                    "type": "ofi_suppression",
                    "ofi_bucket": bucket,
                    "win_rate": wr,
                    "avg_pnl": avg_pnl,
                    "sample_size": total,
                    "action": "reduce_size_30pct" if avg_pnl > -2.0 else "reduce_size_50pct"
                })
    
    for bucket, data in analysis.get("by_ensemble_bucket", {}).items():
        total = data["wins"] + data["losses"]
        if total >= 10:
            wr = data["wins"] / total * 100
            avg_pnl = data["pnl"] / total
            
            if avg_pnl > 0.5 and wr > 25:
                rules.append({
                    "type": "ensemble_boost",
                    "ensemble_bucket": bucket,
                    "win_rate": wr,
                    "avg_pnl": avg_pnl,
                    "sample_size": total,
                    "action": "boost_size_20pct"
                })
    
    return rules


def run_full_analysis() -> Dict:
    """
    Run complete pre-trade condition analysis and generate learning rules.
    """
    print("\n" + "="*60)
    print("PRE-TRADE CONDITION ANALYSIS")
    print("="*60)
    
    analysis = analyze_winning_vs_losing_conditions()
    
    if analysis.get("status") == "insufficient_data":
        print(f"   Insufficient data: {analysis.get('trade_count', 0)} trades")
        return analysis
    
    print(f"\n📊 TRADE OVERVIEW:")
    print(f"   Total: {analysis['total_trades']}")
    print(f"   Wins: {analysis['wins']} ({analysis['win_rate']:.1f}%)")
    print(f"   Losses: {analysis['losses']}")
    
    print(f"\n📈 DIRECTION PERFORMANCE:")
    for direction, data in analysis.get("by_direction", {}).items():
        total = data["wins"] + data["losses"]
        wr = data["wins"] / total * 100 if total > 0 else 0
        print(f"   {direction}: {data['wins']}W/{data['losses']}L ({wr:.1f}% WR)")
    
    print(f"\n🎯 SYMBOL DIRECTION PREFERENCES:")
    for symbol, bias in analysis.get("direction_bias_by_symbol", {}).items():
        print(f"   {symbol}: Prefer {bias['preferred']}")
        print(f"      LONG: {bias['long_wr']:.1f}% WR, ${bias['long_pnl']:.2f}")
        print(f"      SHORT: {bias['short_wr']:.1f}% WR, ${bias['short_pnl']:.2f}")
    
    rules = generate_leading_indicator_rules(analysis)
    
    print(f"\n📝 GENERATED {len(rules)} LEARNING RULES:")
    for rule in rules[:10]:
        print(f"   {rule['type']}: {rule.get('symbol', rule.get('ofi_bucket', rule.get('ensemble_bucket', '')))} → {rule['action']}")
    
    Path("feature_store").mkdir(exist_ok=True)
    
    with open(ANALYSIS_OUTPUT, 'w') as f:
        json.dump(analysis, f, indent=2, default=str)
    print(f"\n💾 Analysis saved to: {ANALYSIS_OUTPUT}")
    
    with open(LEARNING_RULES_OUTPUT, 'w') as f:
        json.dump({
            "generated_at": _now().isoformat(),
            "rules": rules,
            "source_analysis": {
                "total_trades": analysis["total_trades"],
                "win_rate": analysis["win_rate"]
            }
        }, f, indent=2)
    print(f"💾 Rules saved to: {LEARNING_RULES_OUTPUT}")
    
    return {
        "analysis": analysis,
        "rules": rules,
        "status": "ok"
    }


def get_direction_preference(symbol: str) -> Optional[str]:
    """
    Quick lookup: What direction should we prefer for this symbol?
    Returns "LONG", "SHORT", or None if no preference.
    """
    if os.path.exists(LEARNING_RULES_OUTPUT):
        try:
            with open(LEARNING_RULES_OUTPUT) as f:
                data = json.load(f)
            
            for rule in data.get("rules", []):
                if rule.get("type") == "direction_preference" and rule.get("symbol") == symbol:
                    return rule.get("preferred_direction")
        except:
            pass
    return None


if __name__ == "__main__":
    run_full_analysis()
