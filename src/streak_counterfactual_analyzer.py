"""
Streak Filter Counterfactual Analyzer

Analyzes what would have happened if we took the trades blocked by the streak filter.
Fetches market data for blocked signal timestamps and calculates theoretical P&L.
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Any, Optional
from collections import defaultdict

try:
    from src.data_registry import DataRegistry as DR
except ImportError:
    DR = None

try:
    from src.blofin_executor import get_historical_candles
except ImportError:
    get_historical_candles = None

LEARN_LOG = "logs/learning_updates.jsonl"
POSITIONS_FILE = "logs/positions_futures.json"
COUNTERFACTUAL_OUTPUT = "feature_store/streak_counterfactual_analysis.json"


def load_blocked_signals(hours_back: int = 48) -> List[Dict]:
    """Load all streak-blocked signals from learning log."""
    blocked = []
    cutoff_ts = datetime.now().timestamp() - (hours_back * 3600)
    
    if not os.path.exists(LEARN_LOG):
        return blocked
    
    with open(LEARN_LOG, 'r') as f:
        for line in f:
            try:
                data = json.loads(line.strip())
                if data.get("update_type") == "entry_skipped":
                    reason = data.get("reason", {})
                    if reason.get("skip") == "streak_filter":
                        ts = data.get("ts", 0)
                        if ts >= cutoff_ts:
                            blocked.append({
                                "timestamp": ts,
                                "symbol": data.get("symbol"),
                                "streak_reason": reason.get("streak_reason", "unknown"),
                                "datetime": datetime.fromtimestamp(ts).isoformat()
                            })
            except:
                continue
    
    return blocked


def load_executed_trades() -> List[Dict]:
    """Load executed trades to find context around blocked signals."""
    if not os.path.exists(POSITIONS_FILE):
        return []
    
    try:
        with open(POSITIONS_FILE, 'r') as f:
            data = json.load(f)
        
        if isinstance(data, dict):
            trades = data.get("closed_positions", [])
            trades.extend(data.get("open_positions", []))
            return trades
        return data if isinstance(data, list) else []
    except:
        return []


def find_signal_context(blocked: Dict, trades: List[Dict]) -> Dict:
    """Find the context of a blocked signal (what direction would it have been, etc.)."""
    symbol = blocked.get("symbol")
    ts = blocked.get("timestamp", 0)
    
    nearby_trades = []
    for trade in trades:
        if trade.get("symbol") != symbol:
            continue
        
        try:
            trade_ts = datetime.fromisoformat(trade.get("entry_time", "").replace("Z", "")).timestamp()
        except:
            continue
        
        time_diff = abs(trade_ts - ts)
        if time_diff < 7200:
            nearby_trades.append({
                "trade": trade,
                "time_diff": time_diff,
                "before": trade_ts < ts
            })
    
    nearby_trades.sort(key=lambda x: x["time_diff"])
    
    context = {
        "symbol": symbol,
        "likely_direction": None,
        "likely_strategy": None,
        "nearby_trade_count": len(nearby_trades)
    }
    
    if nearby_trades:
        closest = nearby_trades[0]["trade"]
        context["likely_direction"] = closest.get("direction", closest.get("side"))
        context["likely_strategy"] = closest.get("strategy_id", closest.get("strategy"))
        
        if nearby_trades[0]["before"]:
            context["likely_direction"] = "SHORT" if context["likely_direction"] == "LONG" else "LONG"
    
    return context


def fetch_price_at_timestamp(symbol: str, ts: float, minutes_after: int = 60) -> Optional[Dict]:
    """Fetch price data around the blocked signal timestamp."""
    if get_historical_candles is None:
        return None
    
    try:
        blofin_symbol = symbol.replace("USDT", "-USDT")
        candles = get_historical_candles(blofin_symbol, "5m", limit=24)
        
        if not candles:
            return None
        
        return {
            "open": float(candles[0][1]),
            "high": max(float(c[2]) for c in candles[:12]),
            "low": min(float(c[3]) for c in candles[:12]),
            "close": float(candles[-1][4]),
            "candle_count": len(candles)
        }
    except Exception as e:
        return None


def calculate_trade_pnl(trade: Dict) -> Optional[float]:
    """Calculate P&L from a trade record."""
    pnl = trade.get("pnl")
    if pnl is not None:
        try:
            return float(pnl)
        except:
            pass
    
    entry = trade.get("entry_price")
    exit_p = trade.get("exit_price")
    size = trade.get("size", 1)
    direction = trade.get("direction", "LONG").upper()
    
    if entry and exit_p:
        try:
            entry = float(entry)
            exit_p = float(exit_p)
            size = float(size)
            
            if direction == "LONG":
                return (exit_p - entry) * size
            else:
                return (entry - exit_p) * size
        except:
            pass
    
    return None


def estimate_pnl_from_similar_trades(symbol: str, direction: str, trades: List[Dict], 
                                      signal_time: datetime) -> Optional[Dict]:
    """
    Estimate P&L based on similar trades that were actually executed.
    Uses trades from the same symbol and direction.
    """
    similar = []
    
    for trade in trades:
        if trade.get("symbol") != symbol:
            continue
        
        trade_dir = trade.get("direction", trade.get("side", "")).upper()
        if trade_dir != direction.upper():
            continue
        
        pnl = calculate_trade_pnl(trade)
        if pnl is None:
            continue
        
        similar.append({
            "pnl": pnl,
            "win": pnl > 0
        })
    
    if not similar:
        return None
    
    avg_pnl = sum(t["pnl"] for t in similar) / len(similar)
    win_rate = sum(1 for t in similar if t["win"]) / len(similar)
    
    return {
        "estimated_pnl": round(avg_pnl, 4),
        "sample_size": len(similar),
        "win_rate": round(win_rate, 3),
        "outcome": "win" if avg_pnl > 0 else "loss",
        "method": "similar_trade_avg"
    }


def calculate_theoretical_pnl(entry_price: float, direction: str, 
                              high: float, low: float, close: float,
                              position_size: float = 5.0) -> Dict:
    """Calculate what P&L would have been for different exit scenarios."""
    if direction == "LONG":
        max_gain_pct = (high - entry_price) / entry_price * 100
        max_loss_pct = (entry_price - low) / entry_price * 100
        final_pct = (close - entry_price) / entry_price * 100
    else:
        max_gain_pct = (entry_price - low) / entry_price * 100
        max_loss_pct = (high - entry_price) / entry_price * 100
        final_pct = (entry_price - close) / entry_price * 100
    
    tp_hit = max_gain_pct >= 0.15
    sl_hit = max_loss_pct >= 0.30
    
    if tp_hit and sl_hit:
        outcome = "uncertain"
        realized_pct = 0
    elif tp_hit:
        outcome = "win"
        realized_pct = 0.15
    elif sl_hit:
        outcome = "loss"
        realized_pct = -0.30
    else:
        outcome = "hold"
        realized_pct = final_pct
    
    return {
        "max_gain_pct": round(max_gain_pct, 3),
        "max_loss_pct": round(max_loss_pct, 3),
        "final_pct": round(final_pct, 3),
        "realized_pct": round(realized_pct, 3),
        "realized_pnl": round(position_size * realized_pct / 100, 4),
        "outcome": outcome,
        "tp_hit": tp_hit,
        "sl_hit": sl_hit
    }


def analyze_blocked_signals_counterfactual(hours_back: int = 48) -> Dict:
    """
    Main analysis function - analyze all blocked signals and calculate counterfactual P&L.
    """
    print("=" * 70)
    print("STREAK FILTER COUNTERFACTUAL ANALYSIS")
    print("=" * 70)
    print(f"Analyzing blocked signals from last {hours_back} hours...")
    
    blocked = load_blocked_signals(hours_back)
    trades = load_executed_trades()
    
    print(f"Found {len(blocked)} blocked signals")
    print(f"Loaded {len(trades)} executed trades for context")
    
    if not blocked:
        return {"status": "no_blocked_signals", "blocked_count": 0}
    
    results = {
        "analysis_time": datetime.now().isoformat(),
        "hours_analyzed": hours_back,
        "blocked_count": len(blocked),
        "signals": [],
        "summary": {
            "by_symbol": defaultdict(lambda: {"count": 0, "wins": 0, "losses": 0, "uncertain": 0, "theoretical_pnl": 0}),
            "by_direction": defaultdict(lambda: {"count": 0, "wins": 0, "losses": 0, "uncertain": 0, "theoretical_pnl": 0}),
            "by_reason": defaultdict(lambda: {"count": 0, "wins": 0, "losses": 0, "uncertain": 0, "theoretical_pnl": 0}),
            "totals": {"count": 0, "wins": 0, "losses": 0, "uncertain": 0, "theoretical_pnl": 0}
        }
    }
    
    print("\nAnalyzing each blocked signal...")
    
    analyzed_count = 0
    for i, sig in enumerate(blocked):
        symbol = sig["symbol"]
        context = find_signal_context(sig, trades)
        
        direction = context.get("likely_direction", "LONG")
        if not direction:
            direction = "LONG"
        
        signal_time = datetime.fromtimestamp(sig["timestamp"])
        pnl_estimate = estimate_pnl_from_similar_trades(symbol, direction, trades, signal_time)
        
        if pnl_estimate:
            sig_result = {
                **sig,
                "direction": direction,
                "strategy": context.get("likely_strategy", "alpha"),
                **pnl_estimate
            }
            results["signals"].append(sig_result)
            
            outcome = pnl_estimate["outcome"]
            pnl = pnl_estimate["estimated_pnl"]
            reason = sig["streak_reason"]
            
            for bucket in [
                results["summary"]["by_symbol"][symbol],
                results["summary"]["by_direction"][direction],
                results["summary"]["by_reason"][reason],
                results["summary"]["totals"]
            ]:
                bucket["count"] += 1
                bucket["theoretical_pnl"] += pnl
                if outcome == "win":
                    bucket["wins"] += 1
                else:
                    bucket["losses"] += 1
            
            analyzed_count += 1
        
        if (i + 1) % 20 == 0:
            print(f"  Processed {i + 1}/{len(blocked)} signals (analyzed: {analyzed_count})...")
    
    results["summary"]["by_symbol"] = dict(results["summary"]["by_symbol"])
    results["summary"]["by_direction"] = dict(results["summary"]["by_direction"])
    results["summary"]["by_reason"] = dict(results["summary"]["by_reason"])
    
    print("\n" + "-" * 70)
    print("COUNTERFACTUAL SUMMARY")
    print("-" * 70)
    
    totals = results["summary"]["totals"]
    print(f"\nTotal blocked signals analyzed: {totals['count']}")
    print(f"Theoretical wins: {totals['wins']} ({totals['wins']/max(1,totals['count'])*100:.1f}%)")
    print(f"Theoretical losses: {totals['losses']} ({totals['losses']/max(1,totals['count'])*100:.1f}%)")
    print(f"Uncertain (both TP/SL hit): {totals['uncertain']}")
    print(f"Theoretical P&L: ${totals['theoretical_pnl']:.2f}")
    
    print("\nBy Symbol:")
    for sym, data in sorted(results["summary"]["by_symbol"].items(), key=lambda x: x[1]["theoretical_pnl"], reverse=True):
        wr = data["wins"] / max(1, data["count"]) * 100
        print(f"  {sym}: {data['count']} blocked, WR={wr:.0f}%, P&L=${data['theoretical_pnl']:.2f}")
    
    print("\nBy Direction:")
    for dir_, data in results["summary"]["by_direction"].items():
        wr = data["wins"] / max(1, data["count"]) * 100
        print(f"  {dir_}: {data['count']} blocked, WR={wr:.0f}%, P&L=${data['theoretical_pnl']:.2f}")
    
    os.makedirs(os.path.dirname(COUNTERFACTUAL_OUTPUT), exist_ok=True)
    with open(COUNTERFACTUAL_OUTPUT, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to: {COUNTERFACTUAL_OUTPUT}")
    
    return results


def analyze_alpha_vs_beta_blocked(hours_back: int = 48) -> Dict:
    """
    Analyze blocked signals specifically for Alpha vs Beta strategy comparison.
    Alpha = normal signal direction
    Beta = inverted signal direction
    """
    print("\n" + "=" * 70)
    print("ALPHA vs BETA COUNTERFACTUAL COMPARISON")
    print("=" * 70)
    
    blocked = load_blocked_signals(hours_back)
    trades = load_executed_trades()
    
    if not blocked:
        print("No blocked signals found")
        return {}
    
    comparison = {
        "alpha": {"count": 0, "wins": 0, "losses": 0, "pnl": 0, "signals": []},
        "beta": {"count": 0, "wins": 0, "losses": 0, "pnl": 0, "signals": []}
    }
    
    for sig in blocked:
        symbol = sig["symbol"]
        context = find_signal_context(sig, trades)
        signal_time = datetime.fromtimestamp(sig["timestamp"])
        
        alpha_direction = context.get("likely_direction", "LONG") or "LONG"
        beta_direction = "SHORT" if alpha_direction == "LONG" else "LONG"
        
        for strat, direction in [("alpha", alpha_direction), ("beta", beta_direction)]:
            pnl_estimate = estimate_pnl_from_similar_trades(symbol, direction, trades, signal_time)
            
            if not pnl_estimate:
                continue
            
            comparison[strat]["count"] += 1
            comparison[strat]["pnl"] += pnl_estimate["estimated_pnl"]
            
            if pnl_estimate["outcome"] == "win":
                comparison[strat]["wins"] += 1
            else:
                comparison[strat]["losses"] += 1
            
            comparison[strat]["signals"].append({
                "symbol": symbol,
                "direction": direction,
                "datetime": sig["datetime"],
                **pnl_estimate
            })
    
    print("\nResults:")
    for strat in ["alpha", "beta"]:
        data = comparison[strat]
        wr = data["wins"] / max(1, data["count"]) * 100
        print(f"\n{strat.upper()} Strategy (blocked signals):")
        print(f"  Signals analyzed: {data['count']}")
        print(f"  Theoretical wins: {data['wins']} ({wr:.1f}%)")
        print(f"  Theoretical losses: {data['losses']}")
        print(f"  Theoretical P&L: ${data['pnl']:.2f}")
    
    better = "alpha" if comparison["alpha"]["pnl"] > comparison["beta"]["pnl"] else "beta"
    diff = abs(comparison["alpha"]["pnl"] - comparison["beta"]["pnl"])
    print(f"\n{better.upper()} would have been ${diff:.2f} better on blocked signals")
    
    output_file = "feature_store/streak_alpha_beta_comparison.json"
    comparison_clean = {
        k: {kk: vv for kk, vv in v.items() if kk != "signals"} 
        for k, v in comparison.items()
    }
    comparison_clean["better_strategy"] = better
    comparison_clean["pnl_difference"] = diff
    comparison_clean["analysis_time"] = datetime.now().isoformat()
    
    with open(output_file, 'w') as f:
        json.dump(comparison_clean, f, indent=2)
    print(f"Comparison saved to: {output_file}")
    
    return comparison


def generate_learning_rules(analysis: Dict) -> List[Dict]:
    """Generate learning rules based on counterfactual analysis."""
    rules = []
    
    summary = analysis.get("summary", {})
    totals = summary.get("totals", {})
    
    if totals.get("theoretical_pnl", 0) > 0:
        rules.append({
            "type": "streak_filter_adjustment",
            "action": "loosen",
            "reason": f"Blocked signals would have been profitable (${totals['theoretical_pnl']:.2f})",
            "recommendation": "Consider reducing streak filter sensitivity",
            "confidence": min(0.9, totals["count"] / 100)
        })
    elif totals.get("theoretical_pnl", 0) < -10:
        rules.append({
            "type": "streak_filter_validation",
            "action": "keep",
            "reason": f"Streak filter saved us ${abs(totals['theoretical_pnl']):.2f}",
            "recommendation": "Current streak filter settings are protective",
            "confidence": min(0.9, totals["count"] / 100)
        })
    
    by_symbol = summary.get("by_symbol", {})
    for symbol, data in by_symbol.items():
        if data["theoretical_pnl"] > 5:
            rules.append({
                "type": "symbol_exception",
                "symbol": symbol,
                "action": "reduce_streak_sensitivity",
                "reason": f"Blocked {symbol} signals profitable (${data['theoretical_pnl']:.2f})",
                "confidence": min(0.8, data["count"] / 20)
            })
    
    return rules


def run_full_streak_analysis():
    """Run complete streak filter counterfactual analysis."""
    analysis = analyze_blocked_signals_counterfactual(hours_back=48)
    
    if analysis.get("blocked_count", 0) > 0:
        comparison = analyze_alpha_vs_beta_blocked(hours_back=48)
        
        rules = generate_learning_rules(analysis)
        if rules:
            print("\n" + "-" * 70)
            print("LEARNING RULES GENERATED")
            print("-" * 70)
            for rule in rules:
                print(f"  [{rule['type']}] {rule['action']}: {rule['reason']}")
        
        return {
            "analysis": analysis,
            "alpha_beta_comparison": comparison,
            "rules": rules
        }
    
    return {"status": "no_data"}


if __name__ == "__main__":
    run_full_streak_analysis()
