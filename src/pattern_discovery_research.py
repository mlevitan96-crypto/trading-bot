#!/usr/bin/env python3
# File: src/pattern_discovery_research.py
# Purpose: Analyze enriched decisions to discover profitable patterns
# Outputs: feature_store/pattern_summary.json for orchestrator consumption

import os, json, time, argparse, statistics
from collections import defaultdict

ENRICHED_EXEC = "logs/enriched_decisions.jsonl"
ENRICHED_BLOCK = "logs/enriched_blocked_signals.jsonl"
OUTPUT_PATH = "feature_store/pattern_summary.json"
LOG_PATH = "logs/pattern_discovery.jsonl"

def _now(): return int(time.time())

def _append_jsonl(path, row):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a") as f: f.write(json.dumps(row) + "\n")

def _write_json(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f: json.dump(obj, f, indent=2)

def _read_jsonl(path, limit=1000000):
    rows = []
    if not os.path.exists(path): return rows
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                obj = json.loads(line)
                # Handle both single objects and arrays
                if isinstance(obj, list):
                    rows.extend(obj)
                else:
                    rows.append(obj)
            except: continue
    return rows[-limit:]

def _wr(pnls):
    if not pnls: return 0.0
    wins = sum(1 for x in pnls if x > 0)
    return wins / len(pnls)

def _ctx(record):
    c = record.get("signal_ctx", {}) or {}
    return {
        "ofi": float(c.get("ofi") or c.get("ofi_score") or c.get("ofi_value") or 0.0),
        "ens": float(c.get("ensemble") or c.get("ens") or 0.0),
        "roi": float(c.get("roi") or c.get("min_roi") or 0.0),
        "vol": float(c.get("volatility") or c.get("vol") or 0.0),
        "liq": float(c.get("liquidity") or c.get("liq") or 0.0),
        "trend": float(c.get("trend") or 0.0),
        "session": int(c.get("session") or -1)
    }

def _direction(record):
    side = (record.get("side") or record.get("direction") or "").lower()
    if side in ("long", "buy"): return "long"
    if side in ("short", "sell"): return "short"
    cs = _ctx(record)
    return "long"

def _bin(x, edges):
    for i, e in enumerate(edges):
        if x <= e: return i
    return len(edges)

def discover_patterns(window_days=7, max_slices=800):
    print(f"[RESEARCH] Pattern Discovery (window={window_days}d, max_slices={max_slices})")
    
    # Load enriched decisions
    cutoff = _now() - (window_days * 86400)
    exec_rows = _read_jsonl(ENRICHED_EXEC, 100000)
    exec_rows = [r for r in exec_rows if int(r.get("ts", 0)) >= cutoff]
    
    block_rows = _read_jsonl(ENRICHED_BLOCK, 100000)
    block_rows = [r for r in block_rows if int(r.get("ts", 0)) >= cutoff]
    
    print(f"[RESEARCH] Loaded {len(exec_rows)} executed, {len(block_rows)} blocked signals")
    
    if len(exec_rows) < 20:
        print(f"[RESEARCH] Insufficient data ({len(exec_rows)} trades), creating empty pattern_summary.json")
        _write_json(OUTPUT_PATH, {"patterns": [], "meta": {
            "ts": _now(),
            "window_days": window_days,
            "exec_count": len(exec_rows),
            "block_count": len(block_rows)
        }})
        return
    
    # Build multi-dimensional slices
    slices = defaultdict(list)
    for r in exec_rows:
        # --- AUTO-INJECT: ensure pnl_usd exists for pattern discovery ---
        if 'pnl_usd' not in r.get('outcome', {}) and 'net_pnl' in r:
            if 'outcome' not in r:
                r['outcome'] = {}
            r['outcome']['pnl_usd'] = r.get('net_pnl', 0.0)
        # --- END AUTO-INJECT ---
        
        sym = r.get("symbol", "UNKNOWN")
        dirn = _direction(r)
        c = _ctx(r)
        
        # Bin dimensions
        vol_bin = _bin(c["vol"], [10, 20, 35, 60])
        liq_bin = _bin(c["liq"], [1e5, 5e5, 1e6])
        trend_bin = _bin(c["trend"], [-0.5, -0.2, 0.0, 0.2, 0.5])
        session_bin = c["session"] if c["session"] in (0, 1, 2) else 3
        
        # Regime (from record if present)
        regime = r.get("regime", "unknown")
        
        key = (sym, dirn, vol_bin, liq_bin, trend_bin, session_bin, regime)
        slices[key].append(r)
    
    # Analyze each slice for profitability
    patterns = []
    for key, rows in slices.items():
        if len(rows) < 10: continue  # Need at least 10 trades
        
        sym, dirn, vol_bin, liq_bin, trend_bin, session_bin, regime = key
        
        # Calculate performance
        pnls = [float(r.get("outcome", {}).get("pnl_usd", 0.0) or 0.0) for r in rows]
        wr = _wr(pnls)
        total_pnl = sum(pnls)
        avg_pnl = statistics.mean(pnls) if pnls else 0.0
        
        # Compute average thresholds used in this slice
        contexts = [_ctx(r) for r in rows]
        avg_ofi = statistics.mean([abs(c["ofi"]) for c in contexts]) if contexts else 0.5
        avg_ens = statistics.mean([abs(c["ens"]) for c in contexts]) if contexts else 0.05
        avg_roi = statistics.mean([abs(c["roi"]) for c in contexts]) if contexts else 0.003
        
        # Determine status
        if wr >= 0.40 and total_pnl > 0:
            status = "strict"
        elif wr >= 0.30 and total_pnl > -10:
            status = "candidate"
        else:
            status = "rejected"
            continue  # Skip rejected patterns
        
        # Gate combo (simplified - assume all three gates)
        combo = "all_three"
        
        pattern = {
            "slice": {
                "symbol": sym,
                "direction": dirn,
                "vol_bin": vol_bin,
                "liq_bin": liq_bin,
                "trend_bin": trend_bin,
                "session_bin": session_bin,
                "regime": regime,
                "combo": combo
            },
            "thresholds": {
                "ofi": round(avg_ofi, 3),
                "ensemble": round(avg_ens, 3),
                "roi": round(avg_roi, 6)
            },
            "expected": {
                "wr": round(wr, 3),
                "pnl": round(total_pnl, 2),
                "avg_pnl": round(avg_pnl, 2),
                "count": len(rows)
            },
            "status": status
        }
        patterns.append(pattern)
        
        if len(patterns) >= max_slices:
            break
    
    # Sort by performance (strict first, then by PnL)
    patterns.sort(key=lambda p: (
        0 if p["status"] == "strict" else 1,
        -p["expected"]["pnl"]
    ))
    
    strict_count = sum(1 for p in patterns if p["status"] == "strict")
    candidate_count = sum(1 for p in patterns if p["status"] == "candidate")
    
    # Write output
    output = {
        "patterns": patterns,
        "meta": {
            "ts": _now(),
            "window_days": window_days,
            "exec_count": len(exec_rows),
            "block_count": len(block_rows),
            "strict_patterns": strict_count,
            "candidate_patterns": candidate_count,
            "total_patterns": len(patterns)
        }
    }
    
    _write_json(OUTPUT_PATH, output)
    _append_jsonl(LOG_PATH, {
        "ts": _now(),
        "type": "pattern_discovery_complete",
        "strict": strict_count,
        "candidates": candidate_count,
        "total": len(patterns)
    })
    
    print(f"[RESEARCH] ✅ Discovered {len(patterns)} patterns (strict={strict_count}, candidates={candidate_count})")
    print(f"[RESEARCH] Output: {OUTPUT_PATH}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--window_days", type=int, default=7)
    parser.add_argument("--max_slices", type=int, default=800)
    args = parser.parse_args()
    
    discover_patterns(args.window_days, args.max_slices)
