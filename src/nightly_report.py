"""
Nightly Learning Report Generator
Analyzes trading performance, strategy effectiveness, governance actions, and leverage impact.

Phase 4 Migration: Uses SQLite for closed trades analytics via DataRegistry.
"""

import time
import json
import os
from collections import defaultdict

try:
    from src.data_registry import DataRegistry as DR
except ImportError:
    import sys
    sys.path.insert(0, '/home/runner/workspace')
    from src.data_registry import DataRegistry as DR

REPORT_LOG = "logs/nightly_report.jsonl"
SELF_HEAL_LOG = "logs/self_heal.jsonl"

def _load_json_lines(path):
    """Load JSON lines file, handling both JSON arrays and JSONL formats."""
    if not os.path.exists(path):
        return []
    
    out = []
    try:
        with open(path, "r") as f:
            first_char = f.read(1)
            f.seek(0)
            
            if first_char == '[':
                data = json.load(f)
                return data if isinstance(data, list) else []
            else:
                for line in f:
                    s = line.strip()
                    if s:
                        try:
                            out.append(json.loads(s))
                        except:
                            continue
    except:
        pass
    
    return out

def generate_nightly_report():
    """Generate comprehensive nightly learning report."""
    now = int(time.time())
    
    trades = DR.get_closed_trades_from_db()
    heals = _load_json_lines(SELF_HEAL_LOG)
    
    report = {
        "ts": now,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
        "executed_trades": len(trades),
        "blocked_trades": sum(1 for t in trades if t.get("event") == "blocked"),
        "missed_trades": sum(1 for t in trades if t.get("event") == "missed"),
        "low_profit_trades": [
            {
                "symbol": t.get("symbol"),
                "strategy": t.get("strategy"),
                "roi": float(t.get("roi", 0)),
                "net_pnl_usd": float(t.get("net_pnl_usd", 0))
            }
            for t in trades if float(t.get("roi", 0)) < 0.002
        ],
        "strategy_performance": {},
        "governance_actions": heals[-10:] if heals else [],
        "leverage_impact": {
            "leveraged_trades": sum(1 for t in trades if int(t.get("leverage", 1)) > 1),
            "leveraged_profit": round(sum(float(t.get("net_pnl_usd", 0)) for t in trades if int(t.get("leverage", 1)) > 1), 2),
            "baseline_profit": round(sum(float(t.get("net_pnl_usd", 0)) for t in trades if int(t.get("leverage", 1)) == 1), 2),
        }
    }
    
    # Aggregate strategy performance
    strat_stats = defaultdict(lambda: {"wins": 0, "losses": 0, "total_pnl": 0.0})
    for t in trades:
        strat = t.get("strategy", "unknown")
        pnl = float(t.get("net_pnl_usd", 0))
        strat_stats[strat]["total_pnl"] += pnl
        if pnl >= 0:
            strat_stats[strat]["wins"] += 1
        else:
            strat_stats[strat]["losses"] += 1
    
    report["strategy_performance"] = dict(strat_stats)
    
    # Ensure logs directory exists
    os.makedirs(os.path.dirname(REPORT_LOG), exist_ok=True)
    
    # Write report
    with open(REPORT_LOG, "a") as f:
        f.write(json.dumps(report) + "\n")
    
    print(f"\n📊 [NIGHTLY REPORT] Generated at {time.ctime(now)}")
    print(f"   Executed: {report['executed_trades']} trades")
    print(f"   Blocked: {report['blocked_trades']} | Missed: {report['missed_trades']}")
    print(f"   Low-profit trades: {len(report['low_profit_trades'])}")
    print(f"   Leveraged trades: {report['leverage_impact']['leveraged_trades']}")
    print(f"   Leveraged P&L: ${report['leverage_impact']['leveraged_profit']:.2f}")
    print(f"   Baseline P&L: ${report['leverage_impact']['baseline_profit']:.2f}")
    
    if report["strategy_performance"]:
        print("   Strategy Performance:")
        for strat, stats in report["strategy_performance"].items():
            total = stats["wins"] + stats["losses"]
            wr = (stats["wins"] / total * 100) if total > 0 else 0
            print(f"      {strat}: {stats['wins']}W/{stats['losses']}L ({wr:.1f}% WR) | P&L: ${stats['total_pnl']:.2f}")
    
    return report
