"""
UNIFIED PROFIT ANALYSIS
========================
Single, auditable pipeline for profit-seeking intelligence.
All metrics derive from the same filtered dataset.
Excludes anomaly dates defined in feature_store/anomaly_dates.json
"""

import json
import os
from datetime import datetime
from collections import defaultdict
from typing import Dict, List, Optional
import statistics

POSITIONS_FILE = "logs/positions_futures.json"
ANOMALY_FILE = "feature_store/anomaly_dates.json"
OUTPUT_FILE = "feature_store/unified_profit_rules.json"


def load_anomaly_dates() -> set:
    """Load dates to exclude from analysis."""
    try:
        with open(ANOMALY_FILE, 'r') as f:
            data = json.load(f)
        return {a["date"] for a in data.get("anomalies", []) if a.get("action") == "exclude_from_analysis"}
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def load_positions(exclude_anomalies: bool = True) -> tuple:
    """Load and filter positions to clean dataset."""
    with open(POSITIONS_FILE, 'r') as f:
        data = json.load(f)
    
    closed = data.get('closed_positions', [])
    anomaly_dates = load_anomaly_dates() if exclude_anomalies else set()
    
    clean = []
    excluded_count = 0
    
    for pos in closed:
        size = pos.get('size', 0) or 0
        fees = pos.get('trading_fees', 0) or 0
        
        if not (0 < size < 1000 and fees < 10):
            continue
        
        opened = pos.get('opened_at', '')
        if opened:
            date = opened.split('T')[0]
            if date in anomaly_dates:
                excluded_count += 1
                continue
        
        clean.append(pos)
    
    return clean, excluded_count, anomaly_dates


def compute_metrics(positions: List[Dict]) -> Dict:
    """Compute all metrics from single dataset."""
    
    if not positions:
        return {"error": "No positions to analyze"}
    
    total_trades = len(positions)
    
    wins = 0
    total_net_pnl = 0
    total_gross_pnl = 0
    total_fees = 0
    
    by_coin = defaultdict(lambda: {"trades": 0, "wins": 0, "net_pnl": 0, "fees": 0})
    by_direction = defaultdict(lambda: {"trades": 0, "wins": 0, "net_pnl": 0, "fees": 0})
    by_coin_dir = defaultdict(lambda: {"trades": 0, "wins": 0, "net_pnl": 0, "fees": 0, 
                                        "win_gross": [], "loss_gross": []})
    by_hour = defaultdict(lambda: {"trades": 0, "wins": 0, "net_pnl": 0})
    
    for pos in positions:
        symbol = pos.get('symbol', 'UNKNOWN')
        direction = pos.get('direction', 'UNKNOWN')
        coin_dir = f"{symbol}_{direction}"
        
        net_pnl = pos.get('net_pnl', pos.get('pnl', 0)) or 0
        fees = pos.get('trading_fees', 0) or 0
        gross_pnl = net_pnl + fees
        
        opened_at = pos.get('opened_at', '')
        hour = None
        if opened_at and 'T' in opened_at:
            try:
                hour = int(opened_at.split('T')[1].split(':')[0])
            except (ValueError, IndexError):
                pass
        
        is_win = gross_pnl > 0
        
        total_net_pnl += net_pnl
        total_gross_pnl += gross_pnl
        total_fees += fees
        if is_win:
            wins += 1
        
        by_coin[symbol]["trades"] += 1
        by_coin[symbol]["wins"] += 1 if is_win else 0
        by_coin[symbol]["net_pnl"] += net_pnl
        by_coin[symbol]["fees"] += fees
        
        by_direction[direction]["trades"] += 1
        by_direction[direction]["wins"] += 1 if is_win else 0
        by_direction[direction]["net_pnl"] += net_pnl
        by_direction[direction]["fees"] += fees
        
        by_coin_dir[coin_dir]["trades"] += 1
        by_coin_dir[coin_dir]["wins"] += 1 if is_win else 0
        by_coin_dir[coin_dir]["net_pnl"] += net_pnl
        by_coin_dir[coin_dir]["fees"] += fees
        if is_win:
            by_coin_dir[coin_dir]["win_gross"].append(gross_pnl)
        else:
            by_coin_dir[coin_dir]["loss_gross"].append(abs(gross_pnl))
        
        if hour is not None:
            by_hour[hour]["trades"] += 1
            by_hour[hour]["wins"] += 1 if is_win else 0
            by_hour[hour]["net_pnl"] += net_pnl
    
    overall_wr = wins / total_trades * 100 if total_trades > 0 else 0
    overall_ev = total_net_pnl / total_trades if total_trades > 0 else 0
    
    coin_dir_analysis = {}
    for key, data in by_coin_dir.items():
        wr = data["wins"] / data["trades"] * 100 if data["trades"] > 0 else 0
        ev = data["net_pnl"] / data["trades"] if data["trades"] > 0 else 0
        avg_fee = data["fees"] / data["trades"] if data["trades"] > 0 else 0
        
        avg_win_gross = statistics.mean(data["win_gross"]) if data["win_gross"] else 0
        avg_loss_gross = statistics.mean(data["loss_gross"]) if data["loss_gross"] else 0
        
        parts = key.split("_")
        symbol = parts[0] if parts else key
        direction = parts[1] if len(parts) > 1 else "UNKNOWN"
        
        if wr < 35:
            signal_meaning = f"Signals predict OPPOSITE - trade {'SHORT' if direction == 'LONG' else 'LONG'}"
        elif wr < 45:
            signal_meaning = "Weak signal - needs more data or caution"
        elif wr > 55:
            signal_meaning = "Reliable signal - trade as indicated"
        else:
            signal_meaning = "Neutral - near coin flip"
        
        coin_dir_analysis[key] = {
            "trades": data["trades"],
            "wins": data["wins"],
            "win_rate": round(wr, 2),
            "net_pnl": round(data["net_pnl"], 2),
            "net_ev": round(ev, 4),
            "avg_fee": round(avg_fee, 4),
            "signal_meaning": signal_meaning
        }
    
    hour_analysis = {}
    for hour, data in by_hour.items():
        wr = data["wins"] / data["trades"] * 100 if data["trades"] > 0 else 0
        ev = data["net_pnl"] / data["trades"] if data["trades"] > 0 else 0
        
        hour_analysis[str(hour)] = {
            "trades": data["trades"],
            "wins": data["wins"],
            "win_rate": round(wr, 2),
            "net_pnl": round(data["net_pnl"], 2),
            "net_ev": round(ev, 4)
        }
    
    return {
        "analysis_timestamp": datetime.utcnow().isoformat() + "Z",
        "dataset": {
            "source": POSITIONS_FILE,
            "total_positions": total_trades,
            "filter": "size < $1000, fees < $10, anomaly dates excluded"
        },
        "overall": {
            "total_trades": total_trades,
            "wins": wins,
            "losses": total_trades - wins,
            "win_rate": round(overall_wr, 2),
            "total_net_pnl": round(total_net_pnl, 2),
            "total_gross_pnl": round(total_gross_pnl, 2),
            "total_fees": round(total_fees, 2),
            "net_ev_per_trade": round(overall_ev, 4)
        },
        "by_direction": {
            dir_name: {
                "trades": data["trades"],
                "wins": data["wins"],
                "win_rate": round(data["wins"]/data["trades"]*100, 2) if data["trades"] > 0 else 0,
                "net_pnl": round(data["net_pnl"], 2),
                "net_ev": round(data["net_pnl"]/data["trades"], 4) if data["trades"] > 0 else 0
            }
            for dir_name, data in by_direction.items()
        },
        "coin_strategies": coin_dir_analysis,
        "by_hour": hour_analysis,
        "profitable_hours": {
            k: v for k, v in hour_analysis.items() 
            if v["net_ev"] > 0
        }
    }


def generate_coin_profiles(metrics: Dict) -> Dict:
    """Generate individual coin strategy profiles."""
    coin_strategies = metrics.get("coin_strategies", {})
    
    profiles = {}
    for config, data in coin_strategies.items():
        parts = config.split("_")
        if len(parts) < 2:
            continue
        symbol, direction = parts[0], parts[1]
        
        if symbol not in profiles:
            profiles[symbol] = {"short": None, "long": None}
        
        profiles[symbol][direction.lower()] = {
            "trades": data["trades"],
            "win_rate": data["win_rate"],
            "net_ev": data["net_ev"],
            "signal_meaning": data["signal_meaning"]
        }
    
    return profiles


def run_analysis():
    """Run complete analysis and save results."""
    print("=" * 80)
    print("UNIFIED PROFIT ANALYSIS")
    print("Individual coin strategies - anomaly dates excluded")
    print("=" * 80)
    print()
    
    positions, excluded, anomaly_dates = load_positions(exclude_anomalies=True)
    print(f"Loaded {len(positions)} clean positions")
    if excluded > 0:
        print(f"Excluded {excluded} positions from anomaly dates: {anomaly_dates}")
    print()
    
    metrics = compute_metrics(positions)
    
    overall = metrics.get("overall", {})
    print("=== OVERALL METRICS ===")
    print(f"Total Trades: {overall.get('total_trades', 0)}")
    print(f"Wins: {overall.get('wins', 0)} | Losses: {overall.get('losses', 0)}")
    print(f"Win Rate: {overall.get('win_rate', 0)}%")
    print(f"Total Net P&L: ${overall.get('total_net_pnl', 0):.2f}")
    print(f"Total Fees Paid: ${overall.get('total_fees', 0):.2f}")
    print(f"Net EV per Trade: ${overall.get('net_ev_per_trade', 0):.4f}")
    print()
    
    print("=== BY DIRECTION ===")
    for direction, data in metrics.get("by_direction", {}).items():
        print(f"{direction}: {data['trades']} trades, {data['win_rate']}% WR, ${data['net_pnl']:.2f} P&L")
    print()
    
    print("=== COIN STRATEGY PROFILES ===")
    profiles = generate_coin_profiles(metrics)
    for symbol, dirs in sorted(profiles.items()):
        print(f"\n{symbol}:")
        if dirs.get("short"):
            s = dirs["short"]
            print(f"  SHORT: {s['trades']} trades, {s['win_rate']}% WR → {s['signal_meaning']}")
        if dirs.get("long"):
            l = dirs["long"]
            print(f"  LONG:  {l['trades']} trades, {l['win_rate']}% WR → {l['signal_meaning']}")
    print()
    
    metrics["coin_profiles"] = profiles
    
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(metrics, f, indent=2)
    
    print(f"Analysis saved to {OUTPUT_FILE}")
    
    return metrics


if __name__ == "__main__":
    run_analysis()
