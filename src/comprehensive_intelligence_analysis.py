#!/usr/bin/env python3
"""
Comprehensive Intelligence Analysis - Deep Multi-Timeframe Learning
Analyzes ALL data: executed, missed, blocked, counterfactual
Across ALL dimensions: symbols, directions, timing, volatility, regime, liquidity, correlations
Folds daily → multi-day → weekly → monthly for maximum pattern discovery
"""

import json
import os
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Any, Optional, Tuple
import statistics

try:
    from src.data_registry import DataRegistry as DR
except:
    class DR:
        ENRICHED_DECISIONS = "logs/enriched_decisions.jsonl"
        SIGNALS_UNIVERSE = "logs/signals_universe.jsonl"
        PORTFOLIO = "logs/portfolio.json"


def load_jsonl(path: str, limit: int = 50000) -> List[Dict]:
    rows = []
    if not os.path.exists(path):
        return rows
    try:
        with open(path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except:
                    continue
    except:
        pass
    return rows[-limit:]


def load_json(path: str, default=None):
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except:
        return default if default else {}


def save_json(path: str, data: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, 'w') as f:
        json.dump(data, f, indent=2, default=str)
    os.replace(tmp, path)


def parse_ts(ts) -> Optional[datetime]:
    if not ts:
        return None
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts)
        if isinstance(ts, str):
            for fmt in ["%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"]:
                try:
                    return datetime.strptime(ts.replace('Z', '').replace('+00:00', ''), fmt)
                except:
                    continue
            return datetime.fromisoformat(ts.replace('Z', '+00:00').replace('+00:00', ''))
    except:
        return None
    return None


def classify_ofi(ofi: float) -> str:
    ofi = abs(ofi)
    if ofi < 0.25: return "weak"
    elif ofi < 0.50: return "moderate"
    elif ofi < 0.75: return "strong"
    elif ofi < 0.90: return "very_strong"
    else: return "extreme"


def classify_ensemble(ens: float) -> str:
    if ens < 0.03: return "weak"
    elif ens < 0.06: return "moderate"
    elif ens < 0.10: return "strong"
    else: return "very_strong"


def classify_volatility(vol: float) -> str:
    if vol < 0.5: return "low"
    elif vol < 1.0: return "moderate"
    elif vol < 2.0: return "high"
    else: return "extreme"


def get_session(hour: int) -> str:
    if 0 <= hour < 8: return "asia"
    elif 8 <= hour < 16: return "europe"
    else: return "us"


def classify_duration(seconds: float) -> str:
    if seconds < 60: return "flash"
    elif seconds < 300: return "quick"
    elif seconds < 900: return "short"
    elif seconds < 3600: return "medium"
    elif seconds < 14400: return "long"
    else: return "extended"


def get_day_of_week(dt: datetime) -> str:
    return ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][dt.weekday()]


def get_time_bucket(dt: datetime) -> str:
    now = datetime.now()
    diff = now - dt
    if diff.total_seconds() < 3600: return "1h"
    elif diff.total_seconds() < 14400: return "4h"
    elif diff.total_seconds() < 86400: return "24h"
    elif diff.days < 3: return "3d"
    elif diff.days < 7: return "7d"
    elif diff.days < 14: return "14d"
    elif diff.days < 30: return "30d"
    else: return "30d+"


def calculate_stats(records: List[Dict]) -> Dict:
    if not records:
        return {"trades": 0, "wins": 0, "wr": 0, "pnl": 0, "avg_winner": 0, "avg_loser": 0, "rr": 0, "ev": 0, "sharpe": 0}
    
    pnls = [r.get('pnl', 0) for r in records]
    winners = [p for p in pnls if p > 0]
    losers = [p for p in pnls if p <= 0]
    
    n = len(records)
    wins = len(winners)
    wr = wins / n * 100 if n > 0 else 0
    total_pnl = sum(pnls)
    
    avg_winner = sum(winners) / len(winners) if winners else 0
    avg_loser = sum(losers) / len(losers) if losers else 0
    
    rr = abs(avg_winner / avg_loser) if avg_loser != 0 else 0
    ev = (wr/100) * avg_winner - ((100-wr)/100) * abs(avg_loser) if n > 0 else 0
    
    sharpe = 0
    if len(pnls) > 1:
        mean_pnl = statistics.mean(pnls)
        std_pnl = statistics.stdev(pnls)
        if std_pnl > 0:
            sharpe = mean_pnl / std_pnl
    
    return {
        "trades": n,
        "wins": wins,
        "wr": round(wr, 2),
        "pnl": round(total_pnl, 2),
        "avg_winner": round(avg_winner, 4),
        "avg_loser": round(avg_loser, 4),
        "rr": round(rr, 2),
        "ev": round(ev, 4),
        "sharpe": round(sharpe, 3)
    }


def enrich_record(record: Dict, source: str) -> Optional[Dict]:
    ctx = record.get('signal_ctx', record)
    outcome = record.get('outcome', record)
    
    symbol = record.get('symbol', ctx.get('symbol', ''))
    direction = ctx.get('side', ctx.get('direction', '')).upper()
    
    if not symbol:
        return None
    if not direction:
        direction = "UNKNOWN"
    
    # Portfolio trades use 'ofi_score', enriched records use 'ofi'
    ofi_raw = ctx.get('ofi', ctx.get('ofi_score', 0))
    ofi = abs(ofi_raw) if ofi_raw else 0
    ensemble = ctx.get('ensemble', ctx.get('ensemble_score', 0))
    regime = ctx.get('regime', 'unknown')
    volatility = ctx.get('volatility', record.get('volatility', 0))
    liquidity = ctx.get('liquidity', record.get('volume', 0))
    
    ts = record.get('timestamp', record.get('ts', record.get('entry_ts', '')))
    dt = parse_ts(ts)
    hour = dt.hour if dt else 12
    day_of_week = get_day_of_week(dt) if dt else "Unknown"
    time_bucket = get_time_bucket(dt) if dt else "30d+"
    
    pnl = 0
    if source == "executed":
        pnl = outcome.get('pnl_usd', outcome.get('pnl', record.get('pnl', 0)))
    elif source == "missed":
        pnl = record.get('potential_pnl', record.get('theoretical_pnl', 0))
    elif source == "counterfactual":
        pnl = record.get('theoretical_pnl', 0)
    elif source == "blocked":
        pnl = record.get('counterfactual_pnl', record.get('theoretical_pnl', 0))
    
    entry_ts = record.get('entry_ts', 0)
    exit_ts = record.get('exit_ts', 0)
    if isinstance(entry_ts, str):
        entry_dt = parse_ts(entry_ts)
        entry_ts = entry_dt.timestamp() if entry_dt else 0
    if isinstance(exit_ts, str):
        exit_dt = parse_ts(exit_ts)
        exit_ts = exit_dt.timestamp() if exit_dt else 0
    
    duration_sec = exit_ts - entry_ts if (exit_ts and entry_ts and exit_ts > entry_ts) else 0
    
    entry_price = ctx.get('entry_price', record.get('entry_price', 0))
    exit_price = outcome.get('exit_price', record.get('exit_price', 0))
    
    block_reason = record.get('block_reason', record.get('reason', ''))
    
    return {
        "source": source,
        "symbol": symbol,
        "direction": direction,
        "pnl": pnl,
        "ofi": ofi,
        "ofi_raw": ofi_raw,
        "ofi_bucket": classify_ofi(ofi),
        "ensemble": ensemble,
        "ensemble_bucket": classify_ensemble(ensemble),
        "regime": regime,
        "volatility": volatility,
        "vol_bucket": classify_volatility(volatility) if volatility else "unknown",
        "liquidity": liquidity,
        "liq_bucket": "low" if liquidity < 100000 else ("moderate" if liquidity < 500000 else "high"),
        "session": get_session(hour),
        "hour": hour,
        "day_of_week": day_of_week,
        "time_bucket": time_bucket,
        "duration_sec": duration_sec,
        "duration_bucket": classify_duration(duration_sec) if duration_sec > 0 else "unknown",
        "entry_price": entry_price,
        "exit_price": exit_price,
        "block_reason": block_reason,
        "timestamp": dt.isoformat() if dt else None
    }


def load_all_data() -> Dict[str, List[Dict]]:
    print("\n" + "="*70)
    print("📥 LOADING ALL DATA SOURCES")
    print("="*70)
    
    data = {
        "executed": [],
        "blocked": [],
        "missed": [],
        "counterfactual": []
    }
    
    executed = load_jsonl(DR.ENRICHED_DECISIONS)
    print(f"   Enriched decisions file: {len(executed)} records")
    for rec in executed:
        enriched = enrich_record(rec, "executed")
        if enriched:
            data["executed"].append(enriched)
    
    signals = load_jsonl(DR.SIGNALS_UNIVERSE)
    print(f"   Signals universe file: {len(signals)} records")
    blocked_count = 0
    for sig in signals:
        disp = sig.get('disposition', '').upper()
        if disp == 'BLOCKED' or 'block' in str(sig.get('block_reason', '')).lower():
            enriched = enrich_record(sig, "blocked")
            if enriched:
                data["blocked"].append(enriched)
                blocked_count += 1
    print(f"   Blocked signals extracted: {blocked_count}")
    
    missed_paths = [
        'logs/missed_opportunities.jsonl',
        'logs/missed_signals.jsonl',
        getattr(DR, 'MISSED_OPPORTUNITIES', 'logs/missed_opportunities.jsonl')
    ]
    for mp in missed_paths:
        if os.path.exists(mp):
            missed = load_jsonl(mp)
            print(f"   Missed opportunities ({mp}): {len(missed)} records")
            for rec in missed:
                enriched = enrich_record(rec, "missed")
                if enriched:
                    data["missed"].append(enriched)
    
    cf_paths = [
        'logs/counterfactual_outcomes.jsonl',
        getattr(DR, 'COUNTERFACTUAL_OUTCOMES', 'logs/counterfactual_outcomes.jsonl')
    ]
    for cp in cf_paths:
        if os.path.exists(cp):
            cf = load_jsonl(cp)
            print(f"   Counterfactual outcomes ({cp}): {len(cf)} records")
            for rec in cf:
                enriched = enrich_record(rec, "counterfactual")
                if enriched:
                    data["counterfactual"].append(enriched)
    
    # Load portfolio data (closed positions) - use PORTFOLIO_MASTER which points to positions_futures.json
    try:
        portfolio_path = DR.PORTFOLIO_MASTER
        portfolio = load_json(portfolio_path, {})
        # Handle both old format (completed_trades) and new format (closed_positions)
        trades = portfolio.get('completed_trades', portfolio.get('closed_positions', []))
        print(f"   Portfolio completed trades: {len(trades)} records")
        for trade in trades:
            if trade not in [e.get('_raw') for e in data["executed"]]:
                enriched = enrich_record(trade, "executed")
                if enriched:
                    enriched['_raw'] = trade
                    data["executed"].append(enriched)
    except AttributeError:
        # PORTFOLIO_MASTER doesn't exist, skip portfolio loading
        print(f"   Portfolio file not available (skipping)")
    
    print(f"\n   📊 TOTAL RECORDS:")
    print(f"      Executed: {len(data['executed'])}")
    print(f"      Blocked: {len(data['blocked'])}")
    print(f"      Missed: {len(data['missed'])}")
    print(f"      Counterfactual: {len(data['counterfactual'])}")
    print(f"      GRAND TOTAL: {sum(len(v) for v in data.values())}")
    
    return data


def analyze_single_dimension(records: List[Dict], dim_key: str) -> Dict:
    buckets = defaultdict(list)
    for rec in records:
        bucket = rec.get(dim_key, "unknown")
        if bucket:
            buckets[str(bucket)].append(rec)
    
    return {bucket: calculate_stats(recs) for bucket, recs in buckets.items() if len(recs) >= 2}


def analyze_all_dimensions(records: List[Dict], source_name: str) -> Dict:
    print(f"\n   Analyzing {source_name} ({len(records)} records)...")
    
    dimensions = [
        "symbol", "direction", "ofi_bucket", "ensemble_bucket", "regime",
        "vol_bucket", "liq_bucket", "session", "hour", "day_of_week",
        "time_bucket", "duration_bucket"
    ]
    
    results = {}
    for dim in dimensions:
        dim_stats = analyze_single_dimension(records, dim)
        if dim_stats:
            results[dim] = dim_stats
    
    return results


def analyze_multi_dimensional(records: List[Dict], min_trades: int = 3) -> Dict:
    combos = defaultdict(list)
    
    for rec in records:
        sym = rec.get('symbol', '')
        dir = rec.get('direction', '')
        ofi = rec.get('ofi_bucket', '')
        ens = rec.get('ensemble_bucket', '')
        regime = rec.get('regime', '')
        vol = rec.get('vol_bucket', '')
        liq = rec.get('liq_bucket', '')
        session = rec.get('session', '')
        dur = rec.get('duration_bucket', '')
        dow = rec.get('day_of_week', '')
        tb = rec.get('time_bucket', '')
        
        combos[f"sym={sym}|dir={dir}"].append(rec)
        combos[f"sym={sym}|dir={dir}|ofi={ofi}"].append(rec)
        combos[f"sym={sym}|dir={dir}|regime={regime}"].append(rec)
        combos[f"sym={sym}|dir={dir}|vol={vol}"].append(rec)
        combos[f"dir={dir}|ofi={ofi}"].append(rec)
        combos[f"dir={dir}|regime={regime}"].append(rec)
        combos[f"dir={dir}|session={session}"].append(rec)
        combos[f"dir={dir}|dow={dow}"].append(rec)
        combos[f"ofi={ofi}|regime={regime}"].append(rec)
        combos[f"ofi={ofi}|vol={vol}"].append(rec)
        combos[f"regime={regime}|vol={vol}"].append(rec)
        combos[f"regime={regime}|session={session}"].append(rec)
        combos[f"sym={sym}|session={session}"].append(rec)
        combos[f"sym={sym}|dow={dow}"].append(rec)
        combos[f"sym={sym}|regime={regime}|vol={vol}"].append(rec)
        combos[f"sym={sym}|dir={dir}|ofi={ofi}|regime={regime}"].append(rec)
        combos[f"dir={dir}|ofi={ofi}|vol={vol}"].append(rec)
        combos[f"dir={dir}|regime={regime}|vol={vol}"].append(rec)
        
        if dur and dur != 'unknown':
            combos[f"sym={sym}|dur={dur}"].append(rec)
            combos[f"dir={dir}|dur={dur}"].append(rec)
            combos[f"ofi={ofi}|dur={dur}"].append(rec)
            combos[f"regime={regime}|dur={dur}"].append(rec)
            combos[f"sym={sym}|dir={dir}|dur={dur}"].append(rec)
        
        if tb:
            combos[f"time={tb}"].append(rec)
            combos[f"sym={sym}|time={tb}"].append(rec)
            combos[f"dir={dir}|time={tb}"].append(rec)
    
    results = {}
    for combo_key, recs in combos.items():
        if len(recs) >= min_trades:
            results[combo_key] = calculate_stats(recs)
    
    return results


def find_patterns(combos: Dict, pattern_type: str = "profitable") -> List[Dict]:
    patterns = []
    
    for combo_key, stats in combos.items():
        if stats['trades'] < 3:
            continue
        
        if pattern_type == "profitable":
            if stats['pnl'] > 0 and stats['wr'] >= 40:
                patterns.append({
                    "pattern": combo_key,
                    "type": "profitable",
                    "confidence": min(stats['trades'] / 10, 1.0),
                    **stats
                })
        
        elif pattern_type == "high_potential":
            if stats['pnl'] <= 0 and stats['rr'] >= 1.0 and stats['wr'] >= 35:
                breakeven_wr = (1 / (1 + stats['rr'])) * 100 if stats['rr'] > 0 else 50
                wr_gap = stats['wr'] - breakeven_wr
                if wr_gap > -10:
                    patterns.append({
                        "pattern": combo_key,
                        "type": "high_potential",
                        "wr_gap": round(wr_gap, 2),
                        "breakeven_wr": round(breakeven_wr, 2),
                        **stats
                    })
        
        elif pattern_type == "losing":
            if stats['pnl'] < -5 or (stats['wr'] < 35 and stats['trades'] >= 5):
                patterns.append({
                    "pattern": combo_key,
                    "type": "losing",
                    "severity": abs(stats['pnl']) if stats['pnl'] < 0 else (50 - stats['wr']),
                    **stats
                })
        
        elif pattern_type == "missed_opportunity":
            if stats['pnl'] > 0:
                patterns.append({
                    "pattern": combo_key,
                    "type": "missed_opportunity",
                    "potential_pnl": stats['pnl'],
                    **stats
                })
    
    sort_key = 'pnl' if pattern_type in ['profitable', 'missed_opportunity'] else 'severity' if pattern_type == 'losing' else 'wr_gap'
    reverse = pattern_type != 'losing'
    
    return sorted(patterns, key=lambda x: x.get(sort_key, 0), reverse=reverse)


def analyze_timeframes(records: List[Dict]) -> Dict:
    print("\n" + "="*70)
    print("⏰ MULTI-TIMEFRAME ANALYSIS")
    print("="*70)
    
    now = datetime.now()
    timeframes = {
        "1h": timedelta(hours=1),
        "4h": timedelta(hours=4),
        "24h": timedelta(days=1),
        "3d": timedelta(days=3),
        "7d": timedelta(days=7),
        "14d": timedelta(days=14),
        "30d": timedelta(days=30)
    }
    
    results = {}
    for tf_name, tf_delta in timeframes.items():
        cutoff = now - tf_delta
        tf_records = []
        for rec in records:
            ts = rec.get('timestamp')
            if ts:
                dt = parse_ts(ts)
                if dt and dt >= cutoff:
                    tf_records.append(rec)
        
        if tf_records:
            results[tf_name] = {
                "stats": calculate_stats(tf_records),
                "by_symbol": analyze_single_dimension(tf_records, "symbol"),
                "by_direction": analyze_single_dimension(tf_records, "direction"),
                "by_session": analyze_single_dimension(tf_records, "session"),
                "record_count": len(tf_records)
            }
            print(f"   {tf_name}: {len(tf_records)} records, P&L=${results[tf_name]['stats']['pnl']:.2f}, WR={results[tf_name]['stats']['wr']}%")
    
    return results


def analyze_blocked_signals(blocked: List[Dict]) -> Dict:
    print("\n" + "="*70)
    print("🚫 BLOCKED SIGNALS ANALYSIS")
    print("="*70)
    
    if not blocked:
        print("   No blocked signals to analyze")
        return {}
    
    by_reason = defaultdict(list)
    for rec in blocked:
        reason = rec.get('block_reason', 'unknown')
        if isinstance(reason, dict):
            reason = reason.get('reason', str(reason))
        by_reason[str(reason)[:50]].append(rec)
    
    reason_stats = {}
    for reason, recs in by_reason.items():
        stats = calculate_stats(recs)
        reason_stats[reason] = stats
        potential = stats['pnl']
        print(f"   {reason}: {len(recs)} blocked, potential P&L=${potential:.2f}")
    
    by_symbol = analyze_single_dimension(blocked, "symbol")
    by_direction = analyze_single_dimension(blocked, "direction")
    by_ofi = analyze_single_dimension(blocked, "ofi_bucket")
    
    opportunities = []
    for sym, stats in by_symbol.items():
        if stats['pnl'] > 0:
            opportunities.append({
                "symbol": sym,
                "missed_pnl": stats['pnl'],
                "blocked_count": stats['trades'],
                "wr": stats['wr']
            })
    
    opportunities.sort(key=lambda x: x['missed_pnl'], reverse=True)
    
    if opportunities:
        print(f"\n   💰 TOP MISSED OPPORTUNITIES (from blocked signals):")
        for opp in opportunities[:10]:
            print(f"      {opp['symbol']}: ${opp['missed_pnl']:.2f} missed ({opp['blocked_count']} blocked, {opp['wr']}% WR)")
    
    return {
        "by_reason": reason_stats,
        "by_symbol": by_symbol,
        "by_direction": by_direction,
        "by_ofi": by_ofi,
        "opportunities": opportunities
    }


def analyze_timing_patterns(records: List[Dict]) -> Dict:
    print("\n" + "="*70)
    print("⏱️ TIMING PATTERN ANALYSIS")
    print("="*70)
    
    by_session = analyze_single_dimension(records, "session")
    by_hour = analyze_single_dimension(records, "hour")
    by_dow = analyze_single_dimension(records, "day_of_week")
    by_duration = analyze_single_dimension(records, "duration_bucket")
    
    print("\n   📊 BY SESSION:")
    for session, stats in sorted(by_session.items(), key=lambda x: x[1]['pnl'], reverse=True):
        print(f"      {session}: P&L=${stats['pnl']:.2f}, WR={stats['wr']}%, trades={stats['trades']}")
    
    print("\n   📊 BY DAY OF WEEK:")
    for dow, stats in sorted(by_dow.items(), key=lambda x: x[1]['pnl'], reverse=True):
        print(f"      {dow}: P&L=${stats['pnl']:.2f}, WR={stats['wr']}%, trades={stats['trades']}")
    
    print("\n   📊 BY HOUR (Top 5 & Bottom 5):")
    hour_sorted = sorted(by_hour.items(), key=lambda x: x[1]['pnl'], reverse=True)
    for hour, stats in hour_sorted[:5]:
        print(f"      Hour {hour}: P&L=${stats['pnl']:.2f}, WR={stats['wr']}%")
    print("      ...")
    for hour, stats in hour_sorted[-5:]:
        print(f"      Hour {hour}: P&L=${stats['pnl']:.2f}, WR={stats['wr']}%")
    
    print("\n   📊 BY HOLD DURATION:")
    for dur, stats in sorted(by_duration.items(), key=lambda x: x[1]['pnl'], reverse=True):
        print(f"      {dur}: P&L=${stats['pnl']:.2f}, WR={stats['wr']}%, R:R={stats['rr']:.2f}")
    
    best_sessions = sorted(by_session.items(), key=lambda x: x[1]['pnl'], reverse=True)[:3]
    worst_sessions = sorted(by_session.items(), key=lambda x: x[1]['pnl'])[:3]
    best_days = sorted(by_dow.items(), key=lambda x: x[1]['pnl'], reverse=True)[:3]
    best_durations = sorted(by_duration.items(), key=lambda x: x[1]['pnl'], reverse=True)[:3]
    
    return {
        "by_session": by_session,
        "by_hour": by_hour,
        "by_day_of_week": by_dow,
        "by_duration": by_duration,
        "recommendations": {
            "best_sessions": [s[0] for s in best_sessions],
            "avoid_sessions": [s[0] for s in worst_sessions if s[1]['pnl'] < 0],
            "best_days": [d[0] for d in best_days],
            "optimal_durations": [d[0] for d in best_durations]
        }
    }


def analyze_correlations(records: List[Dict]) -> Dict:
    print("\n" + "="*70)
    print("🔗 CORRELATION & REGIME ANALYSIS")
    print("="*70)
    
    by_regime = analyze_single_dimension(records, "regime")
    by_volatility = analyze_single_dimension(records, "vol_bucket")
    by_liquidity = analyze_single_dimension(records, "liq_bucket")
    
    print("\n   📊 BY REGIME:")
    for regime, stats in sorted(by_regime.items(), key=lambda x: x[1]['pnl'], reverse=True):
        print(f"      {regime}: P&L=${stats['pnl']:.2f}, WR={stats['wr']}%, trades={stats['trades']}")
    
    print("\n   📊 BY VOLATILITY:")
    for vol, stats in sorted(by_volatility.items(), key=lambda x: x[1]['pnl'], reverse=True):
        print(f"      {vol}: P&L=${stats['pnl']:.2f}, WR={stats['wr']}%, R:R={stats['rr']:.2f}")
    
    print("\n   📊 BY LIQUIDITY:")
    for liq, stats in sorted(by_liquidity.items(), key=lambda x: x[1]['pnl'], reverse=True):
        print(f"      {liq}: P&L=${stats['pnl']:.2f}, WR={stats['wr']}%")
    
    regime_vol_combos = defaultdict(list)
    for rec in records:
        regime = rec.get('regime', 'unknown')
        vol = rec.get('vol_bucket', 'unknown')
        regime_vol_combos[f"{regime}|{vol}"].append(rec)
    
    print("\n   📊 REGIME x VOLATILITY MATRIX:")
    for combo, recs in sorted(regime_vol_combos.items(), key=lambda x: calculate_stats(x[1])['pnl'], reverse=True):
        if len(recs) >= 3:
            stats = calculate_stats(recs)
            print(f"      {combo}: P&L=${stats['pnl']:.2f}, WR={stats['wr']}%, n={stats['trades']}")
    
    return {
        "by_regime": by_regime,
        "by_volatility": by_volatility,
        "by_liquidity": by_liquidity,
        "regime_vol_matrix": {k: calculate_stats(v) for k, v in regime_vol_combos.items() if len(v) >= 3}
    }


def analyze_symbols_deep(records: List[Dict]) -> Dict:
    print("\n" + "="*70)
    print("🎯 DEEP SYMBOL ANALYSIS")
    print("="*70)
    
    by_symbol = defaultdict(list)
    for rec in records:
        sym = rec.get('symbol', '')
        if sym:
            by_symbol[sym].append(rec)
    
    symbol_analysis = {}
    for sym, recs in by_symbol.items():
        stats = calculate_stats(recs)
        long_recs = [r for r in recs if r.get('direction') == 'LONG']
        short_recs = [r for r in recs if r.get('direction') == 'SHORT']
        
        long_stats = calculate_stats(long_recs)
        short_stats = calculate_stats(short_recs)
        
        direction_bias = "LONG" if long_stats['pnl'] > short_stats['pnl'] else "SHORT"
        direction_advantage = abs(long_stats['pnl'] - short_stats['pnl'])
        
        symbol_analysis[sym] = {
            "overall": stats,
            "long": long_stats,
            "short": short_stats,
            "direction_bias": direction_bias,
            "direction_advantage": round(direction_advantage, 2),
            "by_regime": analyze_single_dimension(recs, "regime"),
            "by_session": analyze_single_dimension(recs, "session"),
            "by_ofi": analyze_single_dimension(recs, "ofi_bucket")
        }
    
    print("\n   📊 SYMBOL PERFORMANCE RANKING:")
    sorted_symbols = sorted(symbol_analysis.items(), key=lambda x: x[1]['overall']['pnl'], reverse=True)
    for sym, analysis in sorted_symbols:
        stats = analysis['overall']
        bias = analysis['direction_bias']
        adv = analysis['direction_advantage']
        print(f"      {sym}: P&L=${stats['pnl']:.2f}, WR={stats['wr']}%, Bias={bias} (+${adv:.2f})")
    
    return symbol_analysis


def generate_actionable_rules(analysis_results: Dict) -> Dict:
    print("\n" + "="*70)
    print("🔧 GENERATING ACTIONABLE RULES")
    print("="*70)
    
    rules = {
        "threshold_adjustments": {},
        "symbol_biases": {},
        "timing_rules": {},
        "regime_rules": {},
        "sizing_adjustments": {},
        "blocks_to_remove": [],
        "generated_at": datetime.now().isoformat()
    }
    
    profitable = analysis_results.get('profitable_patterns', [])
    for p in profitable[:20]:
        pattern = p['pattern']
        if p['trades'] >= 5 and p['wr'] >= 45:
            reduction = min(0.15, 0.05 * (p['wr'] - 40) / 10)
            rules["threshold_adjustments"][pattern] = {
                "ofi_threshold_reduction": round(reduction, 3),
                "confidence": round(p['trades'] / 20, 2),
                "wr": p['wr'],
                "pnl": p['pnl']
            }
    
    symbols = analysis_results.get('symbol_analysis', {})
    for sym, analysis in symbols.items():
        if analysis['direction_advantage'] > 5:
            rules["symbol_biases"][sym] = {
                "preferred_direction": analysis['direction_bias'],
                "advantage": analysis['direction_advantage'],
                "opposite_penalty": 0.5
            }
    
    timing = analysis_results.get('timing_patterns', {})
    if timing.get('recommendations'):
        rules["timing_rules"] = timing['recommendations']
    
    correlations = analysis_results.get('correlations', {})
    for regime, stats in correlations.get('by_regime', {}).items():
        if stats['pnl'] < -10:
            rules["regime_rules"][regime] = {"action": "reduce_size", "multiplier": 0.5}
        elif stats['pnl'] > 10 and stats['wr'] >= 50:
            rules["regime_rules"][regime] = {"action": "increase_size", "multiplier": 1.25}
    
    blocked = analysis_results.get('blocked_analysis', {})
    for opp in blocked.get('opportunities', [])[:5]:
        if opp['missed_pnl'] > 10 and opp['wr'] >= 50:
            rules["blocks_to_remove"].append({
                "symbol": opp['symbol'],
                "potential_pnl": opp['missed_pnl'],
                "wr": opp['wr']
            })
    
    print(f"   Generated {len(rules['threshold_adjustments'])} threshold adjustments")
    print(f"   Generated {len(rules['symbol_biases'])} symbol biases")
    print(f"   Generated {len(rules['regime_rules'])} regime rules")
    print(f"   Identified {len(rules['blocks_to_remove'])} blocks to reconsider")
    
    return rules


def run_comprehensive_analysis() -> Dict:
    print("\n" + "="*70)
    print("🧠 COMPREHENSIVE INTELLIGENCE ANALYSIS")
    print("="*70)
    print(f"   Started: {datetime.now().isoformat()}")
    
    data = load_all_data()
    
    all_records = data['executed'] + data['blocked'] + data['missed'] + data['counterfactual']
    
    print("\n" + "="*70)
    print("📊 EXECUTED TRADES ANALYSIS")
    print("="*70)
    executed_dims = analyze_all_dimensions(data['executed'], "executed")
    executed_multi = analyze_multi_dimensional(data['executed'])
    profitable_patterns = find_patterns(executed_multi, "profitable")
    high_potential = find_patterns(executed_multi, "high_potential")
    losing_patterns = find_patterns(executed_multi, "losing")
    
    print(f"\n   🏆 PROFITABLE PATTERNS: {len(profitable_patterns)}")
    for p in profitable_patterns[:10]:
        print(f"      {p['pattern']}: P&L=${p['pnl']:.2f}, WR={p['wr']}%, n={p['trades']}")
    
    print(f"\n   ⚡ HIGH POTENTIAL PATTERNS: {len(high_potential)}")
    for p in high_potential[:5]:
        print(f"      {p['pattern']}: WR gap={p['wr_gap']}%, R:R={p['rr']:.2f}")
    
    print(f"\n   ⚠️ LOSING PATTERNS (to avoid): {len(losing_patterns)}")
    for p in losing_patterns[:5]:
        print(f"      {p['pattern']}: P&L=${p['pnl']:.2f}, WR={p['wr']}%")
    
    blocked_analysis = analyze_blocked_signals(data['blocked'])
    
    missed_multi = analyze_multi_dimensional(data['missed'])
    missed_opportunities = find_patterns(missed_multi, "missed_opportunity")
    print(f"\n   💸 MISSED OPPORTUNITIES: {len(missed_opportunities)}")
    for p in missed_opportunities[:5]:
        print(f"      {p['pattern']}: potential=${p['potential_pnl']:.2f}")
    
    timeframe_analysis = analyze_timeframes(data['executed'])
    timing_patterns = analyze_timing_patterns(data['executed'])
    correlations = analyze_correlations(data['executed'])
    symbol_analysis = analyze_symbols_deep(data['executed'])
    
    analysis_results = {
        "generated_at": datetime.now().isoformat(),
        "data_summary": {
            "executed": len(data['executed']),
            "blocked": len(data['blocked']),
            "missed": len(data['missed']),
            "counterfactual": len(data['counterfactual']),
            "total": len(all_records)
        },
        "executed_dimensions": executed_dims,
        "profitable_patterns": profitable_patterns,
        "high_potential_patterns": high_potential,
        "losing_patterns": losing_patterns,
        "blocked_analysis": blocked_analysis,
        "missed_opportunities": missed_opportunities,
        "timeframe_analysis": timeframe_analysis,
        "timing_patterns": timing_patterns,
        "correlations": correlations,
        "symbol_analysis": symbol_analysis
    }
    
    rules = generate_actionable_rules(analysis_results)
    analysis_results['actionable_rules'] = rules
    
    save_json("feature_store/comprehensive_analysis.json", analysis_results)
    save_json("feature_store/daily_learning_rules.json", {
        "generated_at": datetime.now().isoformat(),
        "profitable_patterns": {p['pattern']: rules['threshold_adjustments'].get(p['pattern'], {"action": "trade"}) 
                               for p in profitable_patterns[:30]},
        "high_potential_patterns": {p['pattern']: {"action": "monitor", "wr_gap": p.get('wr_gap', 0)} 
                                   for p in high_potential[:20]},
        "losing_patterns": {p['pattern']: {"action": "avoid"} for p in losing_patterns[:20]},
        "symbol_biases": rules['symbol_biases'],
        "timing_rules": rules['timing_rules'],
        "regime_rules": rules['regime_rules']
    })
    
    print("\n" + "="*70)
    print("✅ ANALYSIS COMPLETE")
    print("="*70)
    print(f"   Total records analyzed: {len(all_records)}")
    print(f"   Profitable patterns: {len(profitable_patterns)}")
    print(f"   High potential: {len(high_potential)}")
    print(f"   Losing patterns to avoid: {len(losing_patterns)}")
    print(f"   Saved to: feature_store/comprehensive_analysis.json")
    print(f"   Rules saved to: feature_store/daily_learning_rules.json")
    
    return analysis_results


if __name__ == "__main__":
    results = run_comprehensive_analysis()
