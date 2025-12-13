"""
Coin Profile Engine - Applies unique trading characteristics per coin.

Each of the 15 coins has distinct volatility, trend, and behavioral patterns.
This module loads analyzed profiles and provides coin-specific recommendations
for sizing, thresholds, exit styles, and hold times.

CONTINUOUS EVOLUTION: Profiles are NOT static - they evolve based on trade
outcomes. The evolve_profiles() function runs during learning loops to:
- Promote winning configurations (increase size, lower thresholds)
- Demote losing configurations (decrease size, raise thresholds)
- Adapt exit styles based on actual timing performance
"""

import json
from pathlib import Path
from typing import Dict, Optional, List, Tuple
from datetime import datetime, timedelta
from collections import defaultdict

PROFILES_PATH = Path("feature_store/coin_profiles.json")
EVOLUTION_HISTORY_PATH = Path("feature_store/profile_evolution_history.jsonl")
_profiles_cache: Dict = {}
_cache_time: Optional[datetime] = None
CACHE_TTL_HOURS = 4

MIN_TRADES_FOR_EVOLUTION = 5
EVOLUTION_WR_THRESHOLD = 0.40
SIZE_STEP = 0.05
OFI_STEP = 0.02
MIN_SIZE_MULT = 0.25
MAX_SIZE_MULT = 1.25
MIN_OFI_THRESHOLD = 0.35
MAX_OFI_THRESHOLD = 0.70


def load_profiles(force_reload: bool = False) -> Dict:
    """Load coin profiles with caching."""
    global _profiles_cache, _cache_time
    
    if not force_reload and _profiles_cache and _cache_time:
        if datetime.utcnow() - _cache_time < timedelta(hours=CACHE_TTL_HOURS):
            return _profiles_cache
    
    if PROFILES_PATH.exists():
        try:
            _profiles_cache = json.loads(PROFILES_PATH.read_text())
            _cache_time = datetime.utcnow()
            return _profiles_cache
        except Exception as e:
            print(f"⚠️ [COIN-PROFILE] Error loading profiles: {e}")
    
    return {}


def get_profile(symbol: str) -> Optional[Dict]:
    """Get profile for a specific coin."""
    profiles = load_profiles()
    return profiles.get(symbol)


def get_size_multiplier(symbol: str) -> float:
    """
    Get position size multiplier based on coin volatility.
    
    HIGH volatility coins → 0.5x (smaller positions)
    MEDIUM volatility → 0.75x
    LOW volatility → 1.0x (full size)
    """
    profile = get_profile(symbol)
    if profile and "recommendations" in profile:
        return profile["recommendations"].get("size_multiplier", 1.0)
    return 1.0


def get_ofi_threshold(symbol: str) -> float:
    """
    Get recommended OFI threshold for entry.
    
    Higher thresholds for noisy/volatile coins to filter false signals.
    """
    profile = get_profile(symbol)
    if profile and "recommendations" in profile:
        return profile["recommendations"].get("ofi_threshold", 0.50)
    return 0.50


def get_exit_style(symbol: str) -> str:
    """
    Get recommended exit style based on coin behavior.
    
    TRENDING coins → 'trailing' (let winners run)
    MEAN_REVERTING → 'fixed_target' (take profits quickly)
    NEUTRAL → 'ladder' (scaled exits)
    """
    profile = get_profile(symbol)
    if profile and "recommendations" in profile:
        return profile["recommendations"].get("exit_style", "ladder")
    return "ladder"


def get_min_hold_seconds(symbol: str) -> int:
    """
    Get minimum hold time based on volatility.
    
    Volatile coins need shorter holds to capture quick moves.
    Stable coins benefit from longer holds.
    """
    profile = get_profile(symbol)
    if profile and "recommendations" in profile:
        return profile["recommendations"].get("min_hold_seconds", 420)
    return 420


def get_volatility_class(symbol: str) -> str:
    """Get volatility classification: HIGH, MEDIUM, or LOW."""
    profile = get_profile(symbol)
    if profile and "volatility" in profile:
        return profile["volatility"].get("class", "MEDIUM")
    return "MEDIUM"


def get_trend_class(symbol: str) -> str:
    """Get trend classification: TRENDING, MEAN_REVERTING, or NEUTRAL."""
    profile = get_profile(symbol)
    if profile and "trend" in profile:
        return profile["trend"].get("class", "NEUTRAL")
    return "NEUTRAL"


def apply_coin_profile_to_signal(signal: Dict) -> Dict:
    """
    Enhance signal with coin-specific profile adjustments.
    
    Modifies:
    - base_size_usd (multiplied by size_multiplier)
    - confidence_threshold (uses coin-specific OFI threshold)
    - exit_style (from profile)
    - min_hold_seconds (from profile)
    """
    symbol = signal.get("symbol", "")
    if not symbol:
        return signal
    
    profile = get_profile(symbol)
    if not profile:
        return signal
    
    recs = profile.get("recommendations", {})
    
    enhanced = signal.copy()
    
    if "base_size_usd" in enhanced:
        mult = recs.get("size_multiplier", 1.0)
        enhanced["base_size_usd"] = enhanced["base_size_usd"] * mult
        enhanced["size_multiplier_applied"] = mult
    
    enhanced["coin_ofi_threshold"] = recs.get("ofi_threshold", 0.50)
    enhanced["coin_exit_style"] = recs.get("exit_style", "ladder")
    enhanced["coin_min_hold_seconds"] = recs.get("min_hold_seconds", 420)
    enhanced["coin_volatility_class"] = profile.get("volatility", {}).get("class", "MEDIUM")
    enhanced["coin_trend_class"] = profile.get("trend", {}).get("class", "NEUTRAL")
    enhanced["coin_profile_applied"] = True
    
    return enhanced


def get_all_profiles_summary() -> str:
    """Generate a summary of all coin profiles for display."""
    profiles = load_profiles()
    
    if not profiles:
        return "No coin profiles loaded."
    
    lines = ["=" * 60, "COIN TRADING PROFILES SUMMARY", "=" * 60, ""]
    lines.append(f"{'Symbol':12} {'Vol':>6} {'Trend':>14} {'Size':>6} {'OFI':>5} {'Exit':>12}")
    lines.append("-" * 60)
    
    for symbol in sorted(profiles.keys()):
        p = profiles[symbol]
        vol_class = p.get("volatility", {}).get("class", "?")[:3]
        trend_class = p.get("trend", {}).get("class", "?")
        recs = p.get("recommendations", {})
        size_mult = recs.get("size_multiplier", 1.0)
        ofi = recs.get("ofi_threshold", 0.5)
        exit_style = recs.get("exit_style", "?")
        
        lines.append(f"{symbol:12} {vol_class:>6} {trend_class:>14} {size_mult:>5.2f}x {ofi:>5.2f} {exit_style:>12}")
    
    lines.append("=" * 60)
    return "\n".join(lines)


def _parse_timestamp(val) -> float:
    """Parse timestamp from various formats."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            dt = datetime.fromisoformat(val.replace('Z', '+00:00'))
            return dt.timestamp()
        except Exception:
            try:
                return float(val)
            except Exception:
                return 0.0
    return 0.0


def _load_recent_trades(hours: int = 72) -> List[Dict]:
    """
    Load recent trades for evolution analysis from CANONICAL source only.
    Uses DataRegistry to ensure single source of truth (logs/portfolio.json).
    """
    from src.data_registry import DataRegistry as DR
    
    trades = DR.get_trades(hours=hours)
    
    seen = set()
    unique_trades = []
    for t in trades:
        ts = t.get("timestamp") or t.get("close_time") or t.get("entry_time") or t.get("ts_iso") or ""
        key = (t.get("symbol", ""), str(ts), t.get("action", t.get("side", "")))
        if key not in seen:
            seen.add(key)
            unique_trades.append(t)
    
    return unique_trades


def _analyze_coin_performance(trades: List[Dict]) -> Dict[str, Dict]:
    """
    Analyze performance per coin from recent trades.
    Returns: {symbol: {wins, losses, total_pnl, avg_pnl, win_rate, early_exits, late_exits}}
    """
    stats = defaultdict(lambda: {
        "wins": 0, "losses": 0, "total_pnl": 0.0, 
        "trades": [], "early_exits": 0, "late_exits": 0,
        "hold_times": [], "exit_styles_used": defaultdict(int)
    })
    
    for t in trades:
        symbol = t.get("symbol", "")
        if not symbol:
            continue
        
        pnl = t.get("net_profit") or t.get("net_pnl") or t.get("realized_pnl", 0)
        
        if pnl > 0:
            stats[symbol]["wins"] += 1
        else:
            stats[symbol]["losses"] += 1
        
        stats[symbol]["total_pnl"] += pnl
        stats[symbol]["trades"].append(t)
        
        hold_time = t.get("hold_seconds") or t.get("hold_duration_seconds", 0)
        if hold_time > 0:
            stats[symbol]["hold_times"].append(hold_time)
        
        exit_style = t.get("exit_style") or t.get("exit_reason", "unknown")
        stats[symbol]["exit_styles_used"][exit_style] += 1
        
        if t.get("exited_early") or t.get("early_exit"):
            stats[symbol]["early_exits"] += 1
        if t.get("exited_late") or t.get("late_exit"):
            stats[symbol]["late_exits"] += 1
    
    result = {}
    for symbol, s in stats.items():
        total = s["wins"] + s["losses"]
        if total == 0:
            continue
        
        result[symbol] = {
            "wins": s["wins"],
            "losses": s["losses"],
            "total_trades": total,
            "total_pnl": s["total_pnl"],
            "avg_pnl": s["total_pnl"] / total,
            "win_rate": s["wins"] / total,
            "early_exit_rate": s["early_exits"] / total if total > 0 else 0,
            "late_exit_rate": s["late_exits"] / total if total > 0 else 0,
            "avg_hold_time": sum(s["hold_times"]) / len(s["hold_times"]) if s["hold_times"] else 0,
            "dominant_exit_style": max(s["exit_styles_used"], key=s["exit_styles_used"].get) if s["exit_styles_used"] else "unknown"
        }
    
    return result


def evolve_profiles(dry_run: bool = False) -> Dict[str, List[str]]:
    """
    CORE EVOLUTION FUNCTION - Updates profiles based on recent trade performance.
    
    Evolution Rules:
    1. WINNING COINS (WR >= 40% AND positive P&L):
       - Increase size_multiplier by SIZE_STEP (max 1.25x)
       - Decrease ofi_threshold by OFI_STEP (min 0.35)
    
    2. LOSING COINS (WR < 40% OR negative P&L):
       - Decrease size_multiplier by SIZE_STEP (min 0.25x)
       - Increase ofi_threshold by OFI_STEP (max 0.70)
    
    3. EXIT STYLE ADAPTATION:
       - High early_exit_rate (>50%) → switch to trailing or increase hold
       - High late_exit_rate (>30%) → switch to fixed_target
    
    Returns: {symbol: [list of changes made]}
    """
    print("=" * 60)
    print("🧬 COIN PROFILE EVOLUTION")
    print("=" * 60)
    
    profiles = load_profiles(force_reload=True)
    if not profiles:
        print("⚠️ No profiles to evolve")
        return {}
    
    trades = _load_recent_trades(hours=72)
    print(f"📊 Analyzing {len(trades)} trades from last 72 hours")
    
    performance = _analyze_coin_performance(trades)
    
    changes = {}
    evolution_log = []
    
    for symbol, perf in performance.items():
        if perf["total_trades"] < MIN_TRADES_FOR_EVOLUTION:
            continue
        
        if symbol not in profiles:
            continue
        
        profile = profiles[symbol]
        recs = profile.get("recommendations", {})
        symbol_changes = []
        
        current_size = recs.get("size_multiplier", 1.0)
        current_ofi = recs.get("ofi_threshold", 0.50)
        current_exit = recs.get("exit_style", "ladder")
        
        wr = perf["win_rate"]
        pnl = perf["total_pnl"]
        
        is_winning = wr >= EVOLUTION_WR_THRESHOLD and pnl > 0
        
        if is_winning:
            new_size = min(MAX_SIZE_MULT, current_size + SIZE_STEP)
            new_ofi = max(MIN_OFI_THRESHOLD, current_ofi - OFI_STEP)
            
            if new_size != current_size:
                symbol_changes.append(f"📈 size: {current_size:.2f}x → {new_size:.2f}x (winning)")
                recs["size_multiplier"] = round(new_size, 2)
            
            if new_ofi != current_ofi:
                symbol_changes.append(f"📉 OFI: {current_ofi:.2f} → {new_ofi:.2f} (winning)")
                recs["ofi_threshold"] = round(new_ofi, 2)
        else:
            new_size = max(MIN_SIZE_MULT, current_size - SIZE_STEP)
            new_ofi = min(MAX_OFI_THRESHOLD, current_ofi + OFI_STEP)
            
            if new_size != current_size:
                symbol_changes.append(f"📉 size: {current_size:.2f}x → {new_size:.2f}x (losing)")
                recs["size_multiplier"] = round(new_size, 2)
            
            if new_ofi != current_ofi:
                symbol_changes.append(f"📈 OFI: {current_ofi:.2f} → {new_ofi:.2f} (losing)")
                recs["ofi_threshold"] = round(new_ofi, 2)
        
        early_rate = perf.get("early_exit_rate", 0)
        late_rate = perf.get("late_exit_rate", 0)
        
        if early_rate > 0.50 and current_exit != "trailing":
            recs["exit_style"] = "trailing"
            symbol_changes.append(f"🔄 exit: {current_exit} → trailing (early exits {early_rate:.0%})")
        elif late_rate > 0.30 and current_exit != "fixed_target":
            recs["exit_style"] = "fixed_target"
            symbol_changes.append(f"🔄 exit: {current_exit} → fixed_target (late exits {late_rate:.0%})")
        
        if symbol_changes:
            changes[symbol] = symbol_changes
            status = "✅ WINNING" if is_winning else "⚠️ LOSING"
            print(f"\n{symbol} ({status}: WR={wr:.0%}, P&L=${pnl:.2f}, n={perf['total_trades']})")
            for change in symbol_changes:
                print(f"   {change}")
            
            evolution_log.append({
                "ts": datetime.utcnow().isoformat(),
                "symbol": symbol,
                "performance": {
                    "win_rate": wr,
                    "total_pnl": pnl,
                    "trades": perf["total_trades"]
                },
                "changes": symbol_changes,
                "is_winning": is_winning
            })
    
    if not dry_run and changes:
        PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)
        PROFILES_PATH.write_text(json.dumps(profiles, indent=2))
        print(f"\n💾 Saved evolved profiles to {PROFILES_PATH}")
        
        global _profiles_cache, _cache_time
        _profiles_cache = profiles
        _cache_time = datetime.utcnow()
        
        EVOLUTION_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(EVOLUTION_HISTORY_PATH, "a") as f:
            for log_entry in evolution_log:
                f.write(json.dumps(log_entry) + "\n")
        print(f"📜 Logged {len(evolution_log)} evolution events")
    
    if not changes:
        print("\n✅ No evolution changes needed (all coins stable or insufficient data)")
    
    print("=" * 60)
    return changes


def get_evolution_summary() -> str:
    """Get summary of recent profile evolutions."""
    if not EVOLUTION_HISTORY_PATH.exists():
        return "No evolution history yet."
    
    recent = []
    try:
        lines = EVOLUTION_HISTORY_PATH.read_text().strip().split("\n")
        for line in lines[-50:]:
            if line.strip():
                recent.append(json.loads(line))
    except Exception:
        return "Error reading evolution history."
    
    if not recent:
        return "No evolution history yet."
    
    summary_lines = ["=" * 50, "RECENT PROFILE EVOLUTIONS", "=" * 50]
    
    by_symbol = defaultdict(list)
    for entry in recent:
        by_symbol[entry.get("symbol", "?")].append(entry)
    
    for symbol in sorted(by_symbol.keys()):
        events = by_symbol[symbol]
        latest = events[-1]
        summary_lines.append(f"\n{symbol}:")
        summary_lines.append(f"   Last update: {latest.get('ts', '?')[:16]}")
        summary_lines.append(f"   Performance: WR={latest['performance']['win_rate']:.0%}, P&L=${latest['performance']['total_pnl']:.2f}")
        for change in latest.get("changes", []):
            summary_lines.append(f"   {change}")
    
    return "\n".join(summary_lines)


if __name__ == "__main__":
    print(get_all_profiles_summary())
    print("\n")
    evolve_profiles(dry_run=True)
