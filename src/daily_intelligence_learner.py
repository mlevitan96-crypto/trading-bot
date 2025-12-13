#!/usr/bin/env python3
"""
DAILY INTELLIGENCE LEARNER
Runs comprehensive multi-dimensional analysis daily, accumulates into long-term learning.

Analyzes ALL data sources:
- Executed trades (enriched_decisions.jsonl)
- Blocked signals (signals_universe.jsonl with disposition=BLOCKED)
- Missed opportunities (missed_opportunities.jsonl)
- Counterfactual outcomes (counterfactual_outcomes.jsonl)

Generates optimal thresholds per:
- Symbol × Direction
- OFI bucket
- Ensemble bucket
- Session timing
- Signal alignment
- Regime conditions

Accumulates daily snapshots into long-term analysis for trend detection.
"""

import json
import os
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

try:
    from src.data_registry import DataRegistry as DR
except ImportError:
    import sys
    sys.path.insert(0, '/home/runner/workspace')
    from src.data_registry import DataRegistry as DR


def load_jsonl(path: str) -> List[Dict]:
    """Load JSONL file into list of dicts."""
    records = []
    try:
        with open(path, 'r') as f:
            for line in f:
                try:
                    records.append(json.loads(line.strip()))
                except:
                    continue
    except FileNotFoundError:
        pass
    return records


def load_json(path: str) -> Dict:
    """Load JSON file."""
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except:
        return {}


def save_json(path: str, data: Dict):
    """Save JSON file atomically."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, 'w') as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, path)


def append_jsonl(path: str, record: Dict):
    """Append a record to JSONL file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'a') as f:
        f.write(json.dumps(record) + "\n")


OFI_THRESHOLDS = [0.15, 0.25, 0.35, 0.50, 0.65, 0.80, 0.90]
ENSEMBLE_THRESHOLDS = [-0.08, -0.05, -0.03, 0, 0.03, 0.05, 0.08]

def get_symbols():
    """Get enabled symbols from canonical config - NEVER hardcode."""
    return DR.get_enabled_symbols()

SYMBOLS = get_symbols()

SESSIONS = {
    "asia_night": (0, 4),
    "asia_morning": (4, 8),
    "europe_morning": (8, 12),
    "us_morning": (12, 16),
    "us_afternoon": (16, 20),
    "evening": (20, 24)
}

DURATION_BUCKETS = {
    "flash": (0, 60),           # <1 minute
    "quick": (60, 300),         # 1-5 minutes
    "short": (300, 900),        # 5-15 minutes
    "medium": (900, 3600),      # 15-60 minutes
    "extended": (3600, 14400),  # 1-4 hours
    "long": (14400, float('inf'))  # >4 hours
}


def classify_duration(duration_sec: float) -> str:
    """Classify duration into bucket."""
    for bucket, (min_s, max_s) in DURATION_BUCKETS.items():
        if min_s <= duration_sec < max_s:
            return bucket
    return "unknown"


def classify_ofi(ofi: float) -> str:
    """Classify OFI into bucket."""
    ofi = abs(ofi)
    if ofi < 0.25:
        return "weak"
    elif ofi < 0.50:
        return "moderate"
    elif ofi < 0.75:
        return "strong"
    elif ofi < 0.90:
        return "very_strong"
    else:
        return "extreme"


def classify_ensemble(ens: float) -> str:
    """Classify ensemble into bucket."""
    if ens < -0.06:
        return "strong_bear"
    elif ens < -0.03:
        return "bear"
    elif ens < 0.03:
        return "neutral"
    elif ens < 0.06:
        return "bull"
    else:
        return "strong_bull"


def get_session(hour: int) -> str:
    """Get session name from hour."""
    for name, (start, end) in SESSIONS.items():
        if start <= hour < end:
            return name
    return "unknown"


def calculate_alignment(direction: str, ofi_raw: float, ensemble: float) -> str:
    """Calculate signal alignment."""
    ofi_aligned = (
        (direction == "LONG" and ofi_raw > 0.01) or
        (direction == "SHORT" and ofi_raw < -0.01)
    )
    ens_aligned = (
        (direction == "LONG" and ensemble > 0.01) or
        (direction == "SHORT" and ensemble < -0.01)
    )
    
    if ofi_aligned and ens_aligned:
        return "fully_aligned"
    elif ofi_aligned or ens_aligned:
        return "partial"
    else:
        return "misaligned"


def calculate_stats(records: List[Dict]) -> Dict:
    """Calculate comprehensive stats for a group of records."""
    if not records:
        return {"trades": 0, "wins": 0, "wr": 0, "pnl": 0, "avg_winner": 0, 
                "avg_loser": 0, "rr": 0, "ev": 0}
    
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
    
    return {
        "trades": n,
        "wins": wins,
        "wr": round(wr, 2),
        "pnl": round(total_pnl, 2),
        "avg_winner": round(avg_winner, 2),
        "avg_loser": round(avg_loser, 2),
        "rr": round(rr, 2),
        "ev": round(ev, 2)
    }


def learn_direction_overrides(records: List[Dict]) -> List[Dict]:
    """
    Learn direction overrides from trade performance.
    Creates entries in direction_overrides table for symbol+direction combos with <35% WR.
    
    2025-12-09: Added to address finding that direction_overrides table was empty
    despite having symbols with 0% WR that should be inverted.
    """
    from collections import defaultdict
    import sqlite3
    import time
    
    MIN_TRADES = 15
    MAX_WR_FOR_INVERSION = 35
    
    symbol_direction_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'trades': 0, 'pnl': 0})
    
    for r in records:
        symbol = r.get('symbol', 'UNKNOWN')
        direction = r.get('direction', r.get('original_direction', 'UNKNOWN')).upper()
        pnl = r.get('pnl', 0)
        
        key = f"{symbol}_{direction}"
        symbol_direction_stats[key]['trades'] += 1
        symbol_direction_stats[key]['pnl'] += pnl
        if pnl > 0:
            symbol_direction_stats[key]['wins'] += 1
        else:
            symbol_direction_stats[key]['losses'] += 1
    
    overrides_created = []
    
    try:
        db = sqlite3.connect('data/trading_system.db')
        now_ts = int(time.time())
        expires_at = now_ts + (7 * 24 * 60 * 60)
        
        for key, stats in symbol_direction_stats.items():
            if stats['trades'] < MIN_TRADES:
                continue
                
            wr = 100 * stats['wins'] / stats['trades'] if stats['trades'] > 0 else 0
            
            if wr < MAX_WR_FOR_INVERSION:
                parts = key.rsplit('_', 1)
                if len(parts) != 2:
                    continue
                    
                symbol, original_direction = parts
                inverted_direction = 'SHORT' if original_direction == 'LONG' else 'LONG'
                
                existing = db.execute('''
                    SELECT id FROM direction_overrides 
                    WHERE symbol = ? AND original_direction = ? AND active = 1
                ''', (symbol, original_direction)).fetchone()
                
                if existing:
                    db.execute('''
                        UPDATE direction_overrides 
                        SET win_rate_original = ?, win_rate_inverted = ?, 
                            expires_at = ?, reason = ?
                        WHERE id = ?
                    ''', (wr, 100 - wr, expires_at, 
                          f"WR {wr:.0f}% < {MAX_WR_FOR_INVERSION}% over {stats['trades']} trades",
                          existing[0]))
                else:
                    db.execute('''
                        INSERT INTO direction_overrides 
                        (symbol, signal_name, original_direction, inverted_direction, 
                         reason, win_rate_original, win_rate_inverted, active, 
                         created_at, expires_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                    ''', (symbol, 'all', original_direction, inverted_direction,
                          f"WR {wr:.0f}% < {MAX_WR_FOR_INVERSION}% over {stats['trades']} trades",
                          wr, 100 - wr, now_ts, expires_at))
                
                overrides_created.append({
                    'symbol': symbol,
                    'original_direction': original_direction,
                    'inverted_direction': inverted_direction,
                    'win_rate_original': wr,
                    'trades': stats['trades']
                })
        
        db.commit()
        db.close()
        
    except Exception as e:
        print(f"   ⚠️ Error creating direction overrides: {e}")
    
    return overrides_created


def analyze_time_slices(records: List[Dict]) -> Dict:
    """
    Analyze performance across time slices (10%, 25%, 50%, 100%) to detect trends.
    
    Returns insights on:
    - Improving: Recent slices better than historical = bot is learning
    - Decaying: Recent slices worse = strategy decay or regime shift
    - Stable: Consistent across slices = robust patterns
    - Emerging: Only strong in recent = new opportunities
    - Fading: Only strong in historical = patterns no longer working
    """
    if len(records) < 20:
        return {"error": "Insufficient data for slice analysis", "total_records": len(records)}
    
    n = len(records)
    slices = {
        "recent_10pct": records[-max(1, n // 10):],
        "recent_25pct": records[-max(1, n // 4):],
        "recent_50pct": records[-max(1, n // 2):],
        "all_100pct": records
    }
    
    slice_stats = {}
    for slice_name, slice_records in slices.items():
        stats = calculate_stats(slice_records)
        slice_stats[slice_name] = stats
    
    insights = []
    trend_scores = {}
    
    wr_10 = slice_stats["recent_10pct"]["wr"]
    wr_25 = slice_stats["recent_25pct"]["wr"]
    wr_50 = slice_stats["recent_50pct"]["wr"]
    wr_100 = slice_stats["all_100pct"]["wr"]
    
    ev_10 = slice_stats["recent_10pct"]["ev"]
    ev_25 = slice_stats["recent_25pct"]["ev"]
    ev_50 = slice_stats["recent_50pct"]["ev"]
    ev_100 = slice_stats["all_100pct"]["ev"]
    
    if wr_10 > wr_100 + 5:
        insights.append(f"IMPROVING: Recent 10% WR ({wr_10:.1f}%) exceeds overall ({wr_100:.1f}%) by {wr_10-wr_100:.1f}pts")
        trend_scores["win_rate_trend"] = "improving"
    elif wr_10 < wr_100 - 5:
        insights.append(f"DECAYING: Recent 10% WR ({wr_10:.1f}%) below overall ({wr_100:.1f}%) by {wr_100-wr_10:.1f}pts")
        trend_scores["win_rate_trend"] = "decaying"
    else:
        insights.append(f"STABLE: Recent 10% WR ({wr_10:.1f}%) consistent with overall ({wr_100:.1f}%)")
        trend_scores["win_rate_trend"] = "stable"
    
    if ev_10 > ev_100 + 0.02:
        insights.append(f"EV IMPROVING: Recent 10% EV (${ev_10:.2f}) exceeds overall (${ev_100:.2f})")
        trend_scores["ev_trend"] = "improving"
    elif ev_10 < ev_100 - 0.02:
        insights.append(f"EV DECAYING: Recent 10% EV (${ev_10:.2f}) below overall (${ev_100:.2f})")
        trend_scores["ev_trend"] = "decaying"
    else:
        insights.append(f"EV STABLE: Recent 10% EV (${ev_10:.2f}) consistent with overall (${ev_100:.2f})")
        trend_scores["ev_trend"] = "stable"
    
    gradient = [
        ("10%", wr_10),
        ("25%", wr_25),
        ("50%", wr_50),
        ("100%", wr_100)
    ]
    
    monotonic_improving = all(gradient[i][1] >= gradient[i+1][1] for i in range(len(gradient)-1))
    monotonic_decaying = all(gradient[i][1] <= gradient[i+1][1] for i in range(len(gradient)-1))
    
    if monotonic_improving:
        insights.append("TREND: Monotonic improvement - recent trades consistently better")
        trend_scores["monotonic"] = "improving"
    elif monotonic_decaying:
        insights.append("TREND: Monotonic decay - recent trades consistently worse")
        trend_scores["monotonic"] = "decaying"
    
    pnl_10 = slice_stats["recent_10pct"]["pnl"]
    pnl_25 = slice_stats["recent_25pct"]["pnl"]
    trades_10 = slice_stats["recent_10pct"]["trades"]
    trades_25 = slice_stats["recent_25pct"]["trades"]
    
    if trades_10 > 0 and trades_25 > 0:
        pnl_per_trade_10 = pnl_10 / trades_10
        pnl_per_trade_25 = pnl_25 / trades_25
        insights.append(f"P&L/Trade: Recent 10%=${pnl_per_trade_10:.3f}, Recent 25%=${pnl_per_trade_25:.3f}")
    
    return {
        "slice_stats": slice_stats,
        "insights": insights,
        "trend_scores": trend_scores,
        "recommendation": _generate_slice_recommendation(trend_scores)
    }


def _generate_slice_recommendation(trend_scores: Dict) -> str:
    """Generate actionable recommendation based on slice trends."""
    wr_trend = trend_scores.get("win_rate_trend", "stable")
    ev_trend = trend_scores.get("ev_trend", "stable")
    monotonic = trend_scores.get("monotonic", None)
    
    if wr_trend == "improving" and ev_trend == "improving":
        return "POSITIVE: Learning is working. Consider gradually increasing position sizes."
    elif wr_trend == "decaying" and ev_trend == "decaying":
        return "CAUTION: Performance declining. Review recent market conditions and signal weights."
    elif monotonic == "decaying":
        return "WARNING: Consistent decay pattern. Consider pausing and analyzing what changed."
    elif wr_trend == "stable" and ev_trend == "stable":
        return "NEUTRAL: Performance stable. Continue current approach."
    else:
        return "MIXED: Some metrics improving, others declining. Monitor closely."


def classify_volatility(vol: float) -> str:
    """Classify volatility into bucket for pattern analysis."""
    if vol < 0.5:
        return "low"
    elif vol < 1.0:
        return "moderate"
    elif vol < 2.0:
        return "high"
    else:
        return "extreme"


def enrich_record(record: Dict, source: str) -> Optional[Dict]:
    """Enrich a record with dimensional data including volatility context."""
    ctx = record.get('signal_ctx', record)
    outcome = record.get('outcome', record)
    
    symbol = record.get('symbol', ctx.get('symbol', ''))
    direction = ctx.get('side', ctx.get('direction', '')).upper()
    
    if not symbol or not direction:
        return None
    
    ofi_raw = ctx.get('ofi', 0)
    ofi = abs(ofi_raw)
    ensemble = ctx.get('ensemble', ctx.get('ensemble_score', 0))
    regime = ctx.get('regime', 'unknown')
    
    volatility = ctx.get('volatility', record.get('volatility', 0))
    vol_bucket = classify_volatility(volatility) if volatility else "unknown"
    
    liquidity = ctx.get('liquidity', record.get('volume', 0))
    liq_bucket = "low" if liquidity < 100000 else ("moderate" if liquidity < 500000 else "high")
    
    ts = record.get('timestamp', record.get('ts', ''))
    hour = 12
    if ts:
        try:
            if isinstance(ts, str):
                dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            else:
                dt = datetime.fromtimestamp(ts)
            hour = dt.hour
        except:
            pass
    
    pnl = 0
    if source == "executed":
        pnl = outcome.get('pnl_usd', outcome.get('pnl', 0))
    elif source == "missed":
        pnl = record.get('potential_pnl', record.get('theoretical_pnl', 0))
    elif source == "counterfactual":
        pnl = record.get('theoretical_pnl', 0)
    elif source == "blocked":
        pnl = record.get('counterfactual_pnl', 0)
    
    entry_ts = record.get('entry_ts', 0)
    exit_ts = record.get('exit_ts', 0)
    duration_sec = exit_ts - entry_ts if (exit_ts and entry_ts and exit_ts > entry_ts) else 0
    duration_bucket = classify_duration(duration_sec) if duration_sec > 0 else "unknown"
    
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
        "alignment": calculate_alignment(direction, ofi_raw, ensemble),
        "regime": regime,
        "volatility": volatility,
        "vol_bucket": vol_bucket,
        "liquidity": liquidity,
        "liq_bucket": liq_bucket,
        "session": get_session(hour),
        "hour": hour,
        "duration_sec": duration_sec,
        "duration_bucket": duration_bucket
    }


def load_all_data() -> Dict[str, List[Dict]]:
    """Load all data sources."""
    data = {
        "executed": [],
        "blocked": [],
        "missed": [],
        "counterfactual": []
    }
    
    executed = load_jsonl(DR.ENRICHED_DECISIONS)
    for rec in executed:
        enriched = enrich_record(rec, "executed")
        if enriched:
            data["executed"].append(enriched)
    
    signals = load_jsonl(DR.SIGNALS_UNIVERSE)
    for sig in signals:
        if sig.get('disposition') == 'BLOCKED':
            enriched = enrich_record(sig, "blocked")
            if enriched:
                data["blocked"].append(enriched)
    
    missed_path = getattr(DR, 'MISSED_OPPORTUNITIES', 'logs/missed_opportunities.jsonl')
    missed = load_jsonl(missed_path)
    for rec in missed:
        enriched = enrich_record(rec, "missed")
        if enriched:
            data["missed"].append(enriched)
    
    counterfactual_path = getattr(DR, 'COUNTERFACTUAL_OUTCOMES', 'logs/counterfactual_outcomes.jsonl')
    counterfactual = load_jsonl(counterfactual_path)
    for rec in counterfactual:
        enriched = enrich_record(rec, "counterfactual")
        if enriched:
            data["counterfactual"].append(enriched)
    
    return data


def analyze_dimension(records: List[Dict], dim_key: str) -> Dict:
    """Analyze a single dimension."""
    buckets = defaultdict(list)
    for rec in records:
        bucket = rec.get(dim_key, "unknown")
        buckets[bucket].append(rec)
    
    return {bucket: calculate_stats(recs) for bucket, recs in buckets.items()}


def find_optimal_thresholds(records: List[Dict]) -> Dict:
    """Find optimal thresholds for continuous dimensions."""
    results = {}
    
    ofi_sweep = []
    for threshold in OFI_THRESHOLDS:
        above = [r for r in records if r.get('ofi', 0) >= threshold]
        below = [r for r in records if r.get('ofi', 0) < threshold]
        above_stats = calculate_stats(above)
        below_stats = calculate_stats(below)
        
        ofi_sweep.append({
            "threshold": threshold,
            "above": above_stats,
            "below": below_stats,
            "above_better": above_stats['pnl'] > below_stats['pnl']
        })
    
    best_ofi = max(ofi_sweep, key=lambda x: x['above']['pnl']) if ofi_sweep else None
    results['ofi'] = {
        "sweep": ofi_sweep,
        "optimal": best_ofi['threshold'] if best_ofi else 0.50,
        "optimal_pnl": best_ofi['above']['pnl'] if best_ofi else 0
    }
    
    ens_sweep = []
    for threshold in ENSEMBLE_THRESHOLDS:
        above = [r for r in records if r.get('ensemble', 0) >= threshold]
        below = [r for r in records if r.get('ensemble', 0) < threshold]
        above_stats = calculate_stats(above)
        below_stats = calculate_stats(below)
        
        ens_sweep.append({
            "threshold": threshold,
            "above": above_stats,
            "below": below_stats
        })
    
    results['ensemble'] = {"sweep": ens_sweep}
    
    return results


def analyze_combinations(records: List[Dict]) -> Dict:
    """Analyze multi-dimensional combinations including duration, volatility, and regime."""
    combos = defaultdict(list)
    
    for rec in records:
        symbol = rec.get('symbol', '')
        direction = rec.get('direction', '')
        ofi_bucket = rec.get('ofi_bucket', '')
        ens_bucket = rec.get('ensemble_bucket', '')
        session = rec.get('session', '')
        alignment = rec.get('alignment', '')
        duration_bucket = rec.get('duration_bucket', 'unknown')
        vol_bucket = rec.get('vol_bucket', 'unknown')
        regime = rec.get('regime', 'unknown')
        liq_bucket = rec.get('liq_bucket', 'unknown')
        
        combos[f"sym={symbol}|dir={direction}"].append(rec)
        combos[f"sym={symbol}|dir={direction}|ofi={ofi_bucket}"].append(rec)
        combos[f"sym={symbol}|dir={direction}|ens={ens_bucket}"].append(rec)
        combos[f"dir={direction}|ofi={ofi_bucket}"].append(rec)
        combos[f"dir={direction}|ens={ens_bucket}"].append(rec)
        combos[f"dir={direction}|session={session}"].append(rec)
        combos[f"alignment={alignment}|dir={direction}"].append(rec)
        combos[f"sym={symbol}|ofi={ofi_bucket}|ens={ens_bucket}"].append(rec)
        
        if vol_bucket != 'unknown':
            combos[f"vol={vol_bucket}"].append(rec)
            combos[f"sym={symbol}|vol={vol_bucket}"].append(rec)
            combos[f"dir={direction}|vol={vol_bucket}"].append(rec)
            combos[f"sym={symbol}|dir={direction}|vol={vol_bucket}"].append(rec)
            combos[f"ofi={ofi_bucket}|vol={vol_bucket}"].append(rec)
        
        if regime != 'unknown':
            combos[f"regime={regime}"].append(rec)
            combos[f"sym={symbol}|regime={regime}"].append(rec)
            combos[f"dir={direction}|regime={regime}"].append(rec)
            combos[f"sym={symbol}|dir={direction}|regime={regime}"].append(rec)
            combos[f"ofi={ofi_bucket}|regime={regime}"].append(rec)
            combos[f"vol={vol_bucket}|regime={regime}"].append(rec)
        
        if liq_bucket != 'unknown':
            combos[f"liq={liq_bucket}"].append(rec)
            combos[f"sym={symbol}|liq={liq_bucket}"].append(rec)
        
        if duration_bucket != 'unknown':
            combos[f"dur={duration_bucket}"].append(rec)
            combos[f"sym={symbol}|dur={duration_bucket}"].append(rec)
            combos[f"sym={symbol}|dir={direction}|dur={duration_bucket}"].append(rec)
            combos[f"dir={direction}|dur={duration_bucket}"].append(rec)
            combos[f"ofi={ofi_bucket}|dur={duration_bucket}"].append(rec)
            combos[f"ens={ens_bucket}|dur={duration_bucket}"].append(rec)
            combos[f"session={session}|dur={duration_bucket}"].append(rec)
            combos[f"sym={symbol}|ofi={ofi_bucket}|dur={duration_bucket}"].append(rec)
    
    results = {}
    for combo_key, recs in combos.items():
        if len(recs) >= 3:
            results[combo_key] = calculate_stats(recs)
    
    return results


def find_profitable_patterns(combos: Dict, min_trades: int = 5) -> List[Dict]:
    """Find profitable patterns from combinations."""
    profitable = []
    
    for combo_key, stats in combos.items():
        if stats['trades'] >= min_trades:
            if stats['pnl'] > 0 or stats['ev'] > 0:
                profitable.append({
                    "pattern": combo_key,
                    "profitable": stats['pnl'] > 0,
                    "positive_ev": stats['ev'] > 0,
                    **stats
                })
    
    return sorted(profitable, key=lambda x: x['pnl'], reverse=True)


def find_high_potential_patterns(combos: Dict, min_trades: int = 5) -> List[Dict]:
    """Find patterns with high R/R that are close to profitable."""
    high_potential = []
    
    for combo_key, stats in combos.items():
        if stats['trades'] >= min_trades and stats['rr'] >= 1.0 and stats['pnl'] < 0:
            breakeven_wr = (1 / (1 + stats['rr'])) * 100 if stats['rr'] > 0 else 50
            wr_gap = stats['wr'] - breakeven_wr
            
            if wr_gap > -15:
                high_potential.append({
                    "pattern": combo_key,
                    "breakeven_wr": round(breakeven_wr, 1),
                    "wr_gap": round(wr_gap, 1),
                    **stats
                })
    
    return sorted(high_potential, key=lambda x: x['wr_gap'], reverse=True)


def generate_execution_rules(profitable: List[Dict], high_potential: List[Dict]) -> Dict:
    """Generate execution rules from analysis."""
    rules = {
        "generated_at": datetime.now().isoformat(),
        "profitable_patterns": {},
        "high_potential_patterns": {},
        "per_symbol_direction": {},
        "per_ofi_bucket": {},
        "per_session": {},
        "global_adjustments": {}
    }
    
    for pattern in profitable[:20]:
        pattern_key = pattern['pattern']
        rules["profitable_patterns"][pattern_key] = {
            "action": "trade_aggressive",
            "size_multiplier": min(1.5, 1.0 + pattern['ev'] / 2),
            "ofi_threshold_reduction": 0.10,
            **{k: v for k, v in pattern.items() if k != 'pattern'}
        }
    
    for pattern in high_potential[:20]:
        pattern_key = pattern['pattern']
        rules["high_potential_patterns"][pattern_key] = {
            "action": "explore",
            "size_multiplier": 0.75,
            "ofi_threshold_reduction": 0.05,
            **{k: v for k, v in pattern.items() if k != 'pattern'}
        }
    
    return rules


def run_daily_analysis(save_snapshot: bool = True) -> Dict:
    """Run the complete daily analysis."""
    print("="*70)
    print("📊 DAILY INTELLIGENCE LEARNER")
    print("="*70)
    print(f"Run time: {datetime.now().isoformat()}")
    
    data = load_all_data()
    
    print(f"\n📁 Data Sources Loaded:")
    print(f"   - Executed trades: {len(data['executed'])}")
    print(f"   - Blocked signals: {len(data['blocked'])}")
    print(f"   - Missed opportunities: {len(data['missed'])}")
    print(f"   - Counterfactual outcomes: {len(data['counterfactual'])}")
    
    all_records = data['executed'] + data['blocked'] + data['missed'] + data['counterfactual']
    executed_only = data['executed']
    
    print(f"\n🔬 Analyzing {len(all_records)} total records...")
    
    print("\n📊 TIME-SLICE TREND ANALYSIS:")
    print("-"*50)
    slice_analysis = analyze_time_slices(executed_only)
    if "error" not in slice_analysis:
        print("\n   Performance by Data Slice:")
        for slice_name, stats in slice_analysis["slice_stats"].items():
            pct_label = slice_name.replace("recent_", "").replace("all_", "").replace("pct", "%")
            print(f"   {pct_label:>8}: n={stats['trades']:>4} WR={stats['wr']:>5.1f}% EV=${stats['ev']:>6.2f} P&L=${stats['pnl']:>8.2f}")
        
        print("\n   Trend Insights:")
        for insight in slice_analysis["insights"]:
            print(f"   {insight}")
        
        print(f"\n   >>> {slice_analysis['recommendation']}")
    else:
        print(f"   {slice_analysis['error']} ({slice_analysis['total_records']} records)")
    
    print("\n📈 SINGLE DIMENSION ANALYSIS (Executed Trades):")
    print("-"*50)
    
    single_dim_stats = {}
    for dim in ['ofi_bucket', 'ensemble_bucket', 'session', 'alignment', 'duration_bucket']:
        dim_stats = analyze_dimension(executed_only, dim)
        single_dim_stats[dim.upper()] = dim_stats
        print(f"\n{dim.upper()}:")
        for bucket, stats in sorted(dim_stats.items(), key=lambda x: x[1]['ev'], reverse=True):
            print(f"   {bucket:<20} n={stats['trades']:>3} WR={stats['wr']:>5.1f}% P&L=${stats['pnl']:>7.2f} EV=${stats['ev']:>6.2f} R/R={stats['rr']:>4.2f}")
    
    print("\n🎯 OPTIMAL THRESHOLD SEARCH:")
    print("-"*50)
    thresholds = find_optimal_thresholds(executed_only)
    
    if thresholds.get('ofi', {}).get('optimal'):
        print(f"   OFI Optimal: ≥{thresholds['ofi']['optimal']:.2f} (P&L=${thresholds['ofi']['optimal_pnl']:.2f})")
    
    print("\n🔗 COMBINATION ANALYSIS:")
    print("-"*50)
    combos = analyze_combinations(executed_only)
    
    profitable = find_profitable_patterns(combos)
    high_potential = find_high_potential_patterns(combos)
    
    print(f"\n✅ PROFITABLE PATTERNS ({len(profitable)}):")
    for p in profitable[:10]:
        print(f"   {p['pattern']}: P&L=${p['pnl']:.2f}, EV=${p['ev']:.2f}, n={p['trades']}")
    
    print(f"\n⚖️ HIGH POTENTIAL PATTERNS ({len(high_potential)}):")
    for p in high_potential[:10]:
        print(f"   {p['pattern']}: R/R={p['rr']:.2f}, WR gap={p['wr_gap']:+.0f}%, n={p['trades']}")
    
    print("\n🔄 MISSED OPPORTUNITY ANALYSIS:")
    print("-"*50)
    if data['missed']:
        missed_combos = analyze_combinations(data['missed'])
        missed_profitable = find_profitable_patterns(missed_combos, min_trades=2)
        print(f"   Found {len(missed_profitable)} profitable missed patterns")
        for p in missed_profitable[:5]:
            print(f"   {p['pattern']}: Potential P&L=${p['pnl']:.2f}")
    else:
        print("   No missed opportunity data available")
    
    print("\n🔄 CROSS-COIN ROTATION ANALYSIS:")
    print("-"*50)
    rotation_data = {}
    try:
        from src.cross_coin_rotation_analyzer import CrossCoinRotationAnalyzer
        rotation_analyzer = CrossCoinRotationAnalyzer(lookback_hours=24)
        rotation_data = rotation_analyzer.run_full_analysis()
        
        rot_opps = rotation_data.get('total_opportunities', 0)
        rot_cost = rotation_data.get('total_opportunity_cost_pct', 0)
        print(f"   Rotation opportunities: {rot_opps}")
        print(f"   Total opportunity cost: {rot_cost:.1f}%")
        
        if rotation_data.get('frequently_rotated_from'):
            print("\n   Coins to EXIT FASTER:")
            for sym, info in list(rotation_data['frequently_rotated_from'].items())[:3]:
                print(f"      {sym}: {info['count']} rotations, avg cost {info['avg_cost']:.1f}%")
        
        if rotation_data.get('frequently_rotated_to'):
            print("\n   Coins to SCAN MORE:")
            for sym, info in list(rotation_data['frequently_rotated_to'].items())[:3]:
                print(f"      {sym}: {info['count']} rotations, avg move {info['avg_move']:.1f}%")
        
    except Exception as e:
        print(f"   ⚠️ Rotation analysis unavailable: {e}")
        rotation_data = {}
    
    rules = generate_execution_rules(profitable, high_potential)
    
    rules_path = "feature_store/daily_learning_rules.json"
    save_json(rules_path, rules)
    print(f"\n💾 Execution rules saved to: {rules_path}")
    
    print("\n⚖️ UPDATING SIGNAL FUSION WEIGHTS:")
    print("-"*50)
    try:
        from src.weighted_signal_fusion import WeightedSignalFusion, SIGNAL_WEIGHTS_PATH
        from src.weighted_signal_fusion import normalize_weights, MIN_WEIGHT, MAX_WEIGHT, save_json as save_weights_json
        
        fusion = WeightedSignalFusion()
        weights = fusion.entry_weights.copy()
        adjustments_made = []
        
        ofi_performance = single_dim_stats.get('OFI_BUCKET', {})
        best_ofi = max(ofi_performance.items(), key=lambda x: x[1].get('ev', float('-inf')), default=(None, None))
        worst_ofi = min(ofi_performance.items(), key=lambda x: x[1].get('ev', float('inf')), default=(None, None))
        
        if best_ofi[0] and best_ofi[1].get('ev', 0) > 0:
            weights['ofi'] = min(weights.get('ofi', 0.25) * 1.05, MAX_WEIGHT)
            adjustments_made.append(f"ofi +5% (best bucket: {best_ofi[0]} EV=${best_ofi[1].get('ev', 0):.2f})")
        elif worst_ofi[0] and worst_ofi[1].get('ev', 0) < -1.0:
            weights['ofi'] = max(weights.get('ofi', 0.25) * 0.95, MIN_WEIGHT)
            adjustments_made.append(f"ofi -5% (worst bucket: {worst_ofi[0]} EV=${worst_ofi[1].get('ev', 0):.2f})")
        
        ensemble_performance = single_dim_stats.get('ENSEMBLE_BUCKET', {})
        best_ens = max(ensemble_performance.items(), key=lambda x: x[1].get('ev', float('-inf')), default=(None, None))
        worst_ens = min(ensemble_performance.items(), key=lambda x: x[1].get('ev', float('inf')), default=(None, None))
        
        if best_ens[0] and best_ens[1].get('ev', 0) > 0:
            weights['ensemble'] = min(weights.get('ensemble', 0.20) * 1.05, MAX_WEIGHT)
            adjustments_made.append(f"ensemble +5% (best: {best_ens[0]} EV=${best_ens[1].get('ev', 0):.2f})")
        elif worst_ens[0] and worst_ens[1].get('ev', 0) < -1.5:
            weights['ensemble'] = max(weights.get('ensemble', 0.20) * 0.95, MIN_WEIGHT)
            adjustments_made.append(f"ensemble -5% (worst: {worst_ens[0]} EV=${worst_ens[1].get('ev', 0):.2f})")
        
        session_performance = single_dim_stats.get('SESSION', {})
        best_session = max(session_performance.items(), key=lambda x: x[1].get('ev', float('-inf')), default=(None, None))
        worst_session = min(session_performance.items(), key=lambda x: x[1].get('ev', float('inf')), default=(None, None))
        
        if best_session[0] and worst_session[0]:
            session_variance = best_session[1].get('ev', 0) - worst_session[1].get('ev', 0)
            if session_variance > 1.0:
                weights['session'] = min(weights.get('session', 0.05) * 1.10, MAX_WEIGHT)
                adjustments_made.append(f"session +10% (high variance: ${session_variance:.2f})")
        
        if adjustments_made:
            weights = normalize_weights(weights)
            save_weights_json(SIGNAL_WEIGHTS_PATH, {
                "weights": weights,
                "updated_at": datetime.now().isoformat(),
                "adjustments": adjustments_made,
                "source": "daily_intelligence_learner"
            })
            
            for adj in adjustments_made:
                print(f"   ✅ {adj}")
            print(f"   💾 Weights updated and saved")
        else:
            print(f"   ℹ️ No weight adjustments needed (performance within bounds)")
        
    except Exception as e:
        print(f"   ⚠️ Weight update error: {e}")
    
    print("\n🔄 DIRECTION OVERRIDE LEARNING:")
    print("-"*50)
    try:
        direction_overrides = learn_direction_overrides(executed_only)
        if direction_overrides:
            print(f"   ✅ Created {len(direction_overrides)} new direction overrides")
            for override in direction_overrides:
                print(f"      {override['symbol']}: {override['original_direction']} → {override['inverted_direction']} (WR {override['win_rate_original']:.0f}% → {100-override['win_rate_original']:.0f}%)")
        else:
            print(f"   ℹ️ No new direction overrides needed")
    except Exception as e:
        print(f"   ⚠️ Direction override learning error: {e}")
    
    print("\n🔄 COMPLETE FEEDBACK LOOP ANALYSIS:")
    print("-"*50)
    try:
        from src.complete_feedback_loop import run_complete_feedback_loop
        feedback_summary = run_complete_feedback_loop()
        
        if feedback_summary.get('recommendations'):
            print(f"\n   ⚠️ {len(feedback_summary['recommendations'])} improvement recommendations generated")
            print(f"   Direction accuracy: {feedback_summary.get('direction_analysis', {}).get('accuracy_pct', 0):.1f}%")
            print(f"   Timing rules learned: {feedback_summary.get('timing_rules_learned', 0)}")
    except Exception as e:
        print(f"   ⚠️ Feedback loop error: {e}")
    
    if save_snapshot:
        snapshot = {
            "timestamp": datetime.now().isoformat(),
            "data_counts": {k: len(v) for k, v in data.items()},
            "profitable_count": len(profitable),
            "high_potential_count": len(high_potential),
            "top_profitable": profitable[:5],
            "top_high_potential": high_potential[:5],
            "thresholds": thresholds,
            "rotation_analysis": {
                "opportunities": rotation_data.get('total_opportunities', 0),
                "opportunity_cost_pct": rotation_data.get('total_opportunity_cost_pct', 0),
                "exit_faster_coins": list(rotation_data.get('frequently_rotated_from', {}).keys())[:3],
                "scan_more_coins": list(rotation_data.get('frequently_rotated_to', {}).keys())[:3],
            },
            "time_slice_analysis": slice_analysis if "error" not in slice_analysis else None
        }
        
        history_path = "feature_store/learning_history.jsonl"
        append_jsonl(history_path, snapshot)
        print(f"📜 Snapshot appended to: {history_path}")
        
        slice_path = "feature_store/time_slice_analysis.json"
        save_json(slice_path, {
            "generated_at": datetime.now().isoformat(),
            "analysis": slice_analysis
        })
        print(f"📊 Time-slice analysis saved to: {slice_path}")
    
    return {
        "data": data,
        "thresholds": thresholds,
        "profitable": profitable,
        "high_potential": high_potential,
        "rules": rules
    }


def analyze_learning_trends() -> Dict:
    """Analyze trends across historical learning snapshots."""
    history_path = "feature_store/learning_history.jsonl"
    history = load_jsonl(history_path)
    
    if len(history) < 2:
        return {"status": "insufficient_history", "snapshots": len(history)}
    
    recent = history[-7:] if len(history) >= 7 else history
    
    profitable_trend = [s.get('profitable_count', 0) for s in recent]
    high_potential_trend = [s.get('high_potential_count', 0) for s in recent]
    
    trends = {
        "snapshots_analyzed": len(recent),
        "profitable_trend": profitable_trend,
        "profitable_improving": profitable_trend[-1] > profitable_trend[0] if len(profitable_trend) > 1 else None,
        "high_potential_trend": high_potential_trend,
        "patterns_stabilizing": set()
    }
    
    pattern_counts = defaultdict(int)
    for snapshot in recent:
        for pattern in snapshot.get('top_profitable', []):
            pattern_counts[pattern.get('pattern', '')] += 1
    
    trends["stable_profitable_patterns"] = [
        p for p, count in pattern_counts.items() 
        if count >= len(recent) * 0.7 and p
    ]
    
    return trends


def run_coin_profile_evolution():
    """Run coin profile evolution as part of daily learning."""
    try:
        from src.coin_profile_engine import evolve_profiles
        print("\n" + "="*70)
        print("🧬 COIN PROFILE EVOLUTION")
        print("="*70)
        changes = evolve_profiles(dry_run=False)
        if changes:
            print(f"   ✅ Evolved {len(changes)} coin profiles")
        else:
            print("   ✅ All profiles stable (no changes needed)")
        return changes
    except Exception as e:
        print(f"   ⚠️ Profile evolution error: {e}")
        return {}


if __name__ == "__main__":
    results = run_daily_analysis()
    
    run_coin_profile_evolution()
    
    print("\n" + "="*70)
    print("📈 LEARNING TREND ANALYSIS")
    print("="*70)
    trends = analyze_learning_trends()
    
    if trends.get('status') == 'insufficient_history':
        print(f"   Need more snapshots for trend analysis (have {trends['snapshots']}, need 2+)")
    else:
        print(f"   Snapshots analyzed: {trends['snapshots_analyzed']}")
        print(f"   Profitable improving: {trends['profitable_improving']}")
        print(f"   Stable profitable patterns: {trends['stable_profitable_patterns'][:5]}")
