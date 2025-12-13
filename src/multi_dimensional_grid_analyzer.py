#!/usr/bin/env python3
"""
MULTI-DIMENSIONAL INTELLIGENCE GRID ANALYZER
Slices all trades across every intelligence dimension to find optimal threshold combinations.

Analyzes:
- OFI thresholds (continuous → buckets)
- Ensemble score thresholds
- MTF confidence levels
- CoinGlass data (Fear/Greed, Taker ratios, Liquidations)
- Regime conditions
- Volatility levels
- Session timing
- Symbol × Direction combinations

For each combination, calculates: trades, WR, avg_winner, avg_loser, EV, R/R, P&L
Finds optimal thresholds that maximize cumulative profit.
"""

import json
import os
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Any, Tuple, Optional

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


def bucket_value(value: float, buckets: List[Tuple[float, float, str]]) -> str:
    """Assign a value to a bucket."""
    for low, high, label in buckets:
        if low <= value < high:
            return label
    return buckets[-1][2] if buckets else "unknown"


OFI_BUCKETS = [
    (0.0, 0.25, "ofi_weak"),
    (0.25, 0.50, "ofi_moderate"),
    (0.50, 0.75, "ofi_strong"),
    (0.75, 0.90, "ofi_very_strong"),
    (0.90, 2.0, "ofi_extreme")
]

ENSEMBLE_BUCKETS = [
    (-1.0, -0.06, "ens_strong_bear"),
    (-0.06, -0.03, "ens_bear"),
    (-0.03, 0.03, "ens_neutral"),
    (0.03, 0.06, "ens_bull"),
    (0.06, 1.0, "ens_strong_bull")
]

MTF_BUCKETS = [
    (0.0, 0.3, "mtf_low"),
    (0.3, 0.6, "mtf_med"),
    (0.6, 0.8, "mtf_high"),
    (0.8, 2.0, "mtf_very_high")
]

VOLATILITY_BUCKETS = [
    (0.0, 0.005, "vol_low"),
    (0.005, 0.015, "vol_med"),
    (0.015, 0.03, "vol_high"),
    (0.03, 1.0, "vol_extreme")
]

FEAR_GREED_BUCKETS = [
    (0, 20, "fg_extreme_fear"),
    (20, 40, "fg_fear"),
    (40, 60, "fg_neutral"),
    (60, 80, "fg_greed"),
    (80, 101, "fg_extreme_greed")
]

HOUR_BUCKETS = [
    (0, 4, "session_asia_night"),
    (4, 8, "session_asia_morning"),
    (8, 12, "session_europe_morning"),
    (12, 16, "session_us_morning"),
    (16, 20, "session_us_afternoon"),
    (20, 24, "session_evening")
]

ALIGNMENT_BUCKETS = [
    "aligned",
    "neutral",
    "misaligned"
]


def calculate_stats(trades: List[Dict]) -> Dict:
    """Calculate comprehensive stats for a group of trades."""
    if not trades:
        return {
            "trades": 0, "wins": 0, "wr": 0, 
            "pnl": 0, "avg_winner": 0, "avg_loser": 0,
            "rr": 0, "ev": 0, "breakeven_wr": 50
        }
    
    winners = [t['pnl'] for t in trades if t['pnl'] > 0]
    losers = [t['pnl'] for t in trades if t['pnl'] <= 0]
    
    n = len(trades)
    wins = len(winners)
    wr = wins / n * 100 if n > 0 else 0
    total_pnl = sum(t['pnl'] for t in trades)
    
    avg_winner = sum(winners) / len(winners) if winners else 0
    avg_loser = sum(losers) / len(losers) if losers else 0
    
    rr = abs(avg_winner / avg_loser) if avg_loser != 0 else 0
    ev = (wr/100) * avg_winner - ((100-wr)/100) * abs(avg_loser) if avg_winner or avg_loser else 0
    
    breakeven_wr = (1 / (1 + rr)) * 100 if rr > 0 else 50
    
    return {
        "trades": n,
        "wins": wins,
        "wr": round(wr, 1),
        "pnl": round(total_pnl, 2),
        "avg_winner": round(avg_winner, 2),
        "avg_loser": round(avg_loser, 2),
        "rr": round(rr, 2),
        "ev": round(ev, 2),
        "breakeven_wr": round(breakeven_wr, 1)
    }


def load_coinglass_data() -> Dict[str, Dict]:
    """Load CoinGlass cached data for correlation."""
    cg_data = {}
    cg_cache_dir = "feature_store/coinglass/cache"
    
    if os.path.exists(cg_cache_dir):
        for filename in os.listdir(cg_cache_dir):
            if filename.endswith('.json'):
                data = load_json(os.path.join(cg_cache_dir, filename))
                if data:
                    cg_data[filename.replace('.json', '')] = data
    
    fg_path = "feature_store/coinglass/fear_greed.json"
    if os.path.exists(fg_path):
        cg_data['fear_greed'] = load_json(fg_path)
    
    return cg_data


def enrich_trade_with_dimensions(trade: Dict, cg_data: Dict) -> Dict:
    """Extract all intelligence dimensions from a trade record."""
    ctx = trade.get('signal_ctx', {})
    outcome = trade.get('outcome', {})
    
    ofi_raw = ctx.get('ofi', 0)
    ofi = abs(ofi_raw)
    
    ensemble_raw = ctx.get('ensemble', ctx.get('ensemble_score', ctx.get('composite', 0)))
    ensemble = ensemble_raw
    
    mtf = ctx.get('mtf_confidence', ctx.get('mtf', 0.5))
    vol = ctx.get('volatility', ctx.get('vol_regime', 0.01))
    regime = ctx.get('regime', ctx.get('market_regime', 'unknown'))
    
    fg_value = ctx.get('fear_greed', ctx.get('fg_index', 50))
    taker_ratio = ctx.get('taker_buy_ratio', 0.5)
    liq_pressure = ctx.get('liquidation_pressure', 0)
    
    direction = ctx.get('side', ctx.get('direction', '')).upper()
    
    ensemble_direction = "LONG" if ensemble_raw > 0.01 else ("SHORT" if ensemble_raw < -0.01 else "NEUTRAL")
    ofi_direction = "LONG" if ofi_raw > 0.01 else ("SHORT" if ofi_raw < -0.01 else "NEUTRAL")
    
    ensemble_aligned = (
        (direction == "LONG" and ensemble_raw > 0.01) or
        (direction == "SHORT" and ensemble_raw < -0.01)
    )
    ofi_aligned = (
        (direction == "LONG" and ofi_raw > 0.01) or
        (direction == "SHORT" and ofi_raw < -0.01)
    )
    
    if ensemble_aligned and ofi_aligned:
        alignment = "fully_aligned"
    elif ensemble_aligned or ofi_aligned:
        alignment = "partial_aligned"
    elif abs(ensemble_raw) < 0.01 and abs(ofi_raw) < 0.2:
        alignment = "neutral"
    else:
        alignment = "misaligned"
    
    ts = trade.get('timestamp', trade.get('ts', ''))
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
    
    return {
        "symbol": trade.get('symbol', ''),
        "direction": direction,
        "pnl": outcome.get('pnl_usd', outcome.get('pnl', 0)),
        
        "ofi": ofi,
        "ofi_raw": ofi_raw,
        "ofi_bucket": bucket_value(ofi, OFI_BUCKETS),
        "ofi_direction": ofi_direction,
        
        "ensemble": ensemble,
        "ensemble_bucket": bucket_value(ensemble, ENSEMBLE_BUCKETS),
        "ensemble_direction": ensemble_direction,
        
        "alignment": alignment,
        "alignment_bucket": alignment,
        "ensemble_aligned": ensemble_aligned,
        "ofi_aligned": ofi_aligned,
        
        "mtf": mtf,
        "mtf_bucket": bucket_value(mtf, MTF_BUCKETS),
        
        "volatility": vol,
        "vol_bucket": bucket_value(vol, VOLATILITY_BUCKETS),
        
        "regime": regime,
        "regime_bucket": regime,
        
        "fear_greed": fg_value,
        "fg_bucket": bucket_value(fg_value, FEAR_GREED_BUCKETS),
        
        "taker_ratio": taker_ratio,
        "taker_bucket": "taker_buy" if taker_ratio > 0.52 else ("taker_sell" if taker_ratio < 0.48 else "taker_neutral"),
        
        "liq_pressure": liq_pressure,
        
        "hour": hour,
        "session_bucket": bucket_value(hour, HOUR_BUCKETS),
        
        "raw_ctx": ctx
    }


def analyze_single_dimension(trades: List[Dict], dimension: str) -> Dict:
    """Analyze a single dimension and find optimal threshold."""
    buckets = defaultdict(list)
    
    for trade in trades:
        bucket = trade.get(f"{dimension}_bucket", trade.get(dimension, "unknown"))
        buckets[bucket].append(trade)
    
    results = {}
    for bucket_name, bucket_trades in buckets.items():
        results[bucket_name] = calculate_stats(bucket_trades)
    
    return results


def analyze_combination(trades: List[Dict], dimensions: List[str]) -> Dict:
    """Analyze a combination of dimensions."""
    combos = defaultdict(list)
    
    for trade in trades:
        key_parts = []
        for dim in dimensions:
            bucket_key = f"{dim}_bucket"
            val = trade.get(bucket_key, trade.get(dim, "unknown"))
            key_parts.append(f"{dim}={val}")
        
        combo_key = " | ".join(key_parts)
        combos[combo_key].append(trade)
    
    results = {}
    for combo_name, combo_trades in combos.items():
        stats = calculate_stats(combo_trades)
        if stats['trades'] >= 3:
            results[combo_name] = stats
    
    return results


def find_optimal_threshold(trades: List[Dict], dimension: str, values_key: str) -> Dict:
    """Find the optimal threshold for a continuous dimension."""
    sorted_trades = sorted(trades, key=lambda t: t.get(values_key, 0))
    
    thresholds = []
    for threshold in [0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.5, 0.6, 0.7, 0.8]:
        above = [t for t in trades if t.get(values_key, 0) >= threshold]
        below = [t for t in trades if t.get(values_key, 0) < threshold]
        
        above_stats = calculate_stats(above)
        below_stats = calculate_stats(below)
        
        thresholds.append({
            "threshold": threshold,
            "above_trades": above_stats['trades'],
            "above_pnl": above_stats['pnl'],
            "above_ev": above_stats['ev'],
            "above_wr": above_stats['wr'],
            "below_trades": below_stats['trades'],
            "below_pnl": below_stats['pnl'],
            "below_ev": below_stats['ev'],
            "below_wr": below_stats['wr'],
            "differential": above_stats['pnl'] - below_stats['pnl']
        })
    
    best = max(thresholds, key=lambda x: x['above_pnl']) if thresholds else None
    
    return {
        "dimension": dimension,
        "all_thresholds": thresholds,
        "optimal": best
    }


def run_full_grid_analysis():
    """Run the complete multi-dimensional grid analysis."""
    print("="*80)
    print("🔬 MULTI-DIMENSIONAL INTELLIGENCE GRID ANALYZER")
    print("="*80)
    
    enriched_raw = load_jsonl(DR.ENRICHED_DECISIONS)
    blocked_signals = [s for s in load_jsonl(DR.SIGNALS_UNIVERSE) if s.get('disposition') == 'BLOCKED']
    
    cg_data = load_coinglass_data()
    print(f"\n📊 Data loaded:")
    print(f"   - Executed trades: {len(enriched_raw)}")
    print(f"   - Blocked signals: {len(blocked_signals)}")
    print(f"   - CoinGlass datasets: {list(cg_data.keys())}")
    
    trades = [enrich_trade_with_dimensions(t, cg_data) for t in enriched_raw]
    trades = [t for t in trades if t['symbol'] and t['direction']]
    
    print(f"   - Enriched trades: {len(trades)}")
    
    print("\n" + "="*80)
    print("📈 SINGLE DIMENSION ANALYSIS")
    print("="*80)
    
    dimensions = ['ofi', 'ensemble', 'mtf', 'vol', 'fg', 'session', 'taker']
    
    for dim in dimensions:
        dim_results = analyze_single_dimension(trades, dim)
        print(f"\n🔹 {dim.upper()} BUCKETS:")
        print(f"   {'Bucket':<25} {'Trades':>7} {'WR%':>6} {'P&L':>10} {'EV':>8} {'R/R':>6}")
        print("   " + "-"*65)
        
        for bucket, stats in sorted(dim_results.items(), key=lambda x: x[1]['ev'], reverse=True):
            print(f"   {bucket:<25} {stats['trades']:>7} {stats['wr']:>5.1f}% ${stats['pnl']:>8.2f} ${stats['ev']:>7.2f} {stats['rr']:>5.2f}")
    
    print("\n" + "="*80)
    print("📊 OPTIMAL THRESHOLD SEARCH")
    print("="*80)
    
    ofi_optimal = find_optimal_threshold(trades, 'OFI', 'ofi')
    print(f"\n🎯 OFI Threshold Sweep:")
    print(f"   {'Threshold':>10} {'Above':>7} {'Above P&L':>10} {'Below':>7} {'Below P&L':>10} {'Diff':>10}")
    print("   " + "-"*60)
    for t in ofi_optimal['all_thresholds']:
        diff_str = f"+${t['differential']:.2f}" if t['differential'] > 0 else f"${t['differential']:.2f}"
        print(f"   {t['threshold']:>10.2f} {t['above_trades']:>7} ${t['above_pnl']:>9.2f} {t['below_trades']:>7} ${t['below_pnl']:>9.2f} {diff_str:>10}")
    
    if ofi_optimal['optimal']:
        print(f"\n   ✅ OPTIMAL OFI: ≥{ofi_optimal['optimal']['threshold']:.2f} (P&L=${ofi_optimal['optimal']['above_pnl']:.2f})")
    
    ensemble_optimal = find_optimal_threshold(trades, 'Ensemble', 'ensemble')
    print(f"\n🎯 Ensemble Threshold Sweep:")
    if ensemble_optimal['optimal']:
        print(f"   ✅ OPTIMAL Ensemble: ≥{ensemble_optimal['optimal']['threshold']:.2f} (P&L=${ensemble_optimal['optimal']['above_pnl']:.2f})")
    
    mtf_optimal = find_optimal_threshold(trades, 'MTF', 'mtf')
    print(f"\n🎯 MTF Threshold Sweep:")
    if mtf_optimal['optimal']:
        print(f"   ✅ OPTIMAL MTF: ≥{mtf_optimal['optimal']['threshold']:.2f} (P&L=${mtf_optimal['optimal']['above_pnl']:.2f})")
    
    print("\n" + "="*80)
    print("🔗 COMBINATION ANALYSIS (2D)")
    print("="*80)
    
    combo_pairs = [
        ['alignment', 'direction'],
        ['alignment', 'ofi'],
        ['ofi', 'direction'],
        ['ofi', 'regime'],
        ['ensemble', 'direction'],
        ['ensemble', 'ofi'],
        ['session', 'direction'],
        ['regime', 'direction'],
        ['regime', 'ofi']
    ]
    
    for pair in combo_pairs:
        combo_results = analyze_combination(trades, pair)
        if combo_results:
            print(f"\n🔹 {pair[0].upper()} × {pair[1].upper()}:")
            print(f"   {'Combination':<45} {'Trades':>6} {'WR%':>6} {'P&L':>9} {'EV':>7}")
            print("   " + "-"*75)
            
            sorted_combos = sorted(combo_results.items(), key=lambda x: x[1]['pnl'], reverse=True)[:8]
            for combo, stats in sorted_combos:
                print(f"   {combo:<45} {stats['trades']:>6} {stats['wr']:>5.1f}% ${stats['pnl']:>8.2f} ${stats['ev']:>6.2f}")
    
    print("\n" + "="*80)
    print("🏆 SYMBOL × DIRECTION × OFI (3D)")
    print("="*80)
    
    for symbol in ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'DOTUSDT', 'AVAXUSDT']:
        symbol_trades = [t for t in trades if t['symbol'] == symbol]
        if len(symbol_trades) < 5:
            continue
        
        print(f"\n🔸 {symbol}:")
        for direction in ['LONG', 'SHORT']:
            dir_trades = [t for t in symbol_trades if t['direction'] == direction]
            if len(dir_trades) < 3:
                continue
            
            ofi_sweep = find_optimal_threshold(dir_trades, 'OFI', 'ofi')
            if ofi_sweep['optimal'] and ofi_sweep['optimal']['above_trades'] >= 2:
                opt = ofi_sweep['optimal']
                print(f"   {direction}: OFI≥{opt['threshold']:.2f} → {opt['above_trades']} trades, P&L=${opt['above_pnl']:.2f}, EV=${opt['above_ev']:.2f}")
    
    print("\n" + "="*80)
    print("📊 BLOCKED SIGNAL ANALYSIS")
    print("="*80)
    
    if blocked_signals:
        print(f"\n🚫 Analyzing {len(blocked_signals)} blocked signals...")
        
        block_reasons = defaultdict(list)
        for sig in blocked_signals:
            reason = sig.get('block_reason', sig.get('disposition_reason', 'unknown'))
            block_reasons[reason].append(sig)
        
        print(f"   {'Block Reason':<40} {'Count':>7}")
        print("   " + "-"*50)
        for reason, sigs in sorted(block_reasons.items(), key=lambda x: -len(x[1]))[:10]:
            print(f"   {reason[:40]:<40} {len(sigs):>7}")
    else:
        print("   No blocked signals found in logs/signals.jsonl")
    
    print("\n" + "="*80)
    print("🎯 KEY INSIGHTS")
    print("="*80)
    
    positive_ev_combos = []
    for pair in combo_pairs:
        combo_results = analyze_combination(trades, pair)
        for combo, stats in combo_results.items():
            if stats['ev'] > 0 and stats['trades'] >= 5:
                positive_ev_combos.append((combo, stats))
    
    if positive_ev_combos:
        print("\n✅ POSITIVE EV COMBINATIONS (trade MORE of these):")
        for combo, stats in sorted(positive_ev_combos, key=lambda x: x[1]['pnl'], reverse=True)[:10]:
            print(f"   {combo}: EV=${stats['ev']:.2f}/trade, {stats['trades']} trades, P&L=${stats['pnl']:.2f}")
    else:
        print("\n⚠️ No positive EV combinations found yet - need more data!")
    
    high_rr_combos = []
    for pair in combo_pairs:
        combo_results = analyze_combination(trades, pair)
        for combo, stats in combo_results.items():
            if stats['rr'] >= 1.0 and stats['pnl'] < 0 and stats['trades'] >= 5:
                wr_gap = stats['wr'] - stats['breakeven_wr']
                if wr_gap > -15:
                    high_rr_combos.append((combo, stats, wr_gap))
    
    if high_rr_combos:
        print("\n⚖️ HIGH R/R COMBINATIONS (close to profitable):")
        for combo, stats, gap in sorted(high_rr_combos, key=lambda x: x[2], reverse=True)[:10]:
            gap_str = f"+{gap:.0f}%" if gap > 0 else f"{gap:.0f}%"
            print(f"   {combo}: R/R={stats['rr']:.2f}, WR gap={gap_str}, {stats['trades']} trades")
    
    optimal_thresholds = {
        "generated_at": datetime.now().isoformat(),
        "ofi": ofi_optimal['optimal'],
        "ensemble": ensemble_optimal['optimal'],
        "mtf": mtf_optimal['optimal'],
        "positive_ev_combos": [{"combo": c, "stats": s} for c, s in positive_ev_combos[:20]],
        "high_rr_combos": [{"combo": c, "stats": s, "wr_gap": g} for c, s, g in high_rr_combos[:20]]
    }
    
    output_path = "feature_store/optimal_thresholds.json"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(optimal_thresholds, f, indent=2)
    print(f"\n💾 Optimal thresholds saved to: {output_path}")
    
    return optimal_thresholds


if __name__ == "__main__":
    run_full_grid_analysis()
