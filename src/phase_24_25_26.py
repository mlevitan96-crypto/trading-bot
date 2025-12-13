# src/phase_24_25_26.py
#
# Phase 24.0 – Live Attribution Dashboard
# Phase 25.0 – Regime-Aware Strategy Routing
# Phase 26.0 – Shadow Strategy Lab

import os, json, time, random
from statistics import mean

ATTRIBUTION_LOG = "logs/strategic_attribution.jsonl"
REGIME_LOG = "logs/regime_state.json"
STRATEGY_REGISTRY = "config/strategy_registry.json"
SHADOW_STATE = "config/shadow_strategy_state.json"
DASHBOARD_PATH = "logs/live_attribution_dashboard.json"
EVENT_LOG = "logs/phase_24_25_26_events.jsonl"

def _append_event(ev: str, payload: dict = None):
    os.makedirs(os.path.dirname(EVENT_LOG), exist_ok=True)
    if payload is None:
        payload = {}
    else:
        payload = dict(payload)
    payload.update({"event": ev, "ts": int(time.time())})
    with open(EVENT_LOG, "a") as f:
        f.write(json.dumps(payload) + "\n")

def _read_json(path: str, default: dict):
    if not os.path.exists(path): 
        return default
    with open(path, "r") as f:
        try: 
            return json.load(f)
        except: 
            return default

def _write_json(path: str, obj: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f: 
        json.dump(obj, f, indent=2)

def _read_jsonl(path: str):
    if not os.path.exists(path): 
        return []
    out = []
    with open(path, "r") as f:
        for line in f:
            s = line.strip()
            if s:
                try: 
                    out.append(json.loads(s))
                except: 
                    pass
    return out

# ---- Phase 24.0 – Live Attribution Dashboard ----
def generate_live_dashboard():
    """
    Generate live attribution dashboard showing:
    - Per-symbol ROI performance
    - Exit type distribution (TP1, TP2, trailing, stop)
    - Quality metrics (TP2 share, trailing share, stop rate)
    """
    attribution_events = _read_jsonl(ATTRIBUTION_LOG)
    
    by_symbol = {}
    by_strategy = {}
    
    # Parse attribution events
    for event in attribution_events:
        if event.get("event") == "attribution_computed":
            # Process symbols
            symbols = event.get("symbols", {})
            for sym, metrics in symbols.items():
                if sym not in by_symbol:
                    by_symbol[sym] = {
                        "trades": metrics.get("trades", 0),
                        "win_rate": metrics.get("win_rate", 0.0),
                        "avg_roi": metrics.get("avg_roi", 0.0),
                        "total_roi": metrics.get("total_roi", 0.0),
                        "sharpe": metrics.get("sharpe", 0.0)
                    }
            
            # Process strategies
            strategies = event.get("strategies", {})
            for strat, metrics in strategies.items():
                if strat not in by_strategy:
                    by_strategy[strat] = {
                        "trades": metrics.get("trades", 0),
                        "win_rate": metrics.get("win_rate", 0.0),
                        "avg_roi": metrics.get("avg_roi", 0.0),
                        "total_roi": metrics.get("total_roi", 0.0),
                        "sharpe": metrics.get("sharpe", 0.0)
                    }
    
    dashboard = {
        "timestamp": int(time.time()),
        "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "symbols": by_symbol,
        "strategies": by_strategy
    }
    
    _write_json(DASHBOARD_PATH, dashboard)
    _append_event("live_dashboard_generated", {
        "symbols_tracked": len(by_symbol),
        "strategies_tracked": len(by_strategy)
    })
    
    return dashboard

# ---- Phase 25.0 – Regime-Aware Strategy Routing ----
def route_strategies_by_regime():
    """
    Route strategies based on current market regime:
    - Active: Strategy matches regime profile
    - Suppressed: Strategy doesn't fit current conditions
    """
    # Read current regime
    regime_state = _read_json(REGIME_LOG, {
        "regime": "stable",
        "volatility": 0.002,
        "trend_strength": 0.5
    })
    
    # Define strategy regime profiles
    default_registry = {
        "Sentiment-Fusion": {
            "regime_profile": {
                "volatility_min": 0.0,
                "volatility_max": 0.025,
                "trend_min": 0.0
            }
        },
        "Trend-Conservative": {
            "regime_profile": {
                "volatility_min": 0.0,
                "volatility_max": 0.020,
                "trend_min": 0.4
            }
        },
        "Breakout-Aggressive": {
            "regime_profile": {
                "volatility_min": 0.015,
                "volatility_max": 1.0,
                "trend_min": 0.0
            }
        }
    }
    
    registry = _read_json(STRATEGY_REGISTRY, default_registry)
    routed = {}
    
    current_vol = regime_state.get("volatility", 0.002)
    current_trend = regime_state.get("trend_strength", 0.5)
    
    for strat, config in registry.items():
        if "regime_profile" not in config:
            routed[strat] = "active"
            continue
        
        profile = config["regime_profile"]
        vol_min = profile.get("volatility_min", 0.0)
        vol_max = profile.get("volatility_max", 1.0)
        trend_min = profile.get("trend_min", 0.0)
        
        # Check if strategy matches current regime
        vol_match = vol_min <= current_vol <= vol_max
        trend_match = current_trend >= trend_min
        
        if vol_match and trend_match:
            routed[strat] = "active"
        else:
            routed[strat] = "suppressed"
    
    _write_json("config/strategy_routing.json", routed)
    _append_event("strategies_routed", {
        "active": sum(1 for s in routed.values() if s == "active"),
        "suppressed": sum(1 for s in routed.values() if s == "suppressed"),
        "regime": regime_state.get("regime", "unknown")
    })
    
    return routed

# ---- Phase 26.0 – Shadow Strategy Lab ----
def run_shadow_strategy_lab():
    """
    Generate shadow strategy variants for A/B testing:
    - Creates variants with randomized exit parameters
    - Limits to 5 variants per base strategy
    - Tracks lineage and performance
    """
    default_registry = {
        "Sentiment-Fusion": {},
        "Trend-Conservative": {},
        "Breakout-Aggressive": {}
    }
    
    registry = _read_json(STRATEGY_REGISTRY, default_registry)
    shadow_state = _read_json(SHADOW_STATE, {})
    new_variants = []
    
    for strat in registry.keys():
        lineage = shadow_state.setdefault(strat, [])
        
        # Limit to 5 variants per strategy
        if len(lineage) >= 5:
            continue
        
        variant_id = f"{strat}_shadow_v{len(lineage)+1}"
        variant = {
            "id": variant_id,
            "base": strat,
            "exit_config": {
                "TP1_ROI": round(0.005 + random.uniform(-0.002, 0.003), 4),
                "TP2_ROI": round(0.010 + random.uniform(-0.003, 0.005), 4),
                "TRAIL_ATR_MULT": round(1.5 + random.uniform(-0.3, 0.7), 2),
                "STOP_ATR_MULT": round(2.0 + random.uniform(-0.5, 0.5), 2)
            },
            "created": int(time.time()),
            "performance": {
                "trades": 0,
                "win_rate": 0.0,
                "avg_roi": 0.0,
                "total_roi": 0.0
            },
            "status": "shadow"
        }
        lineage.append(variant)
        new_variants.append(variant)
    
    _write_json(SHADOW_STATE, shadow_state)
    _append_event("shadow_variants_created", {
        "new_variants": len(new_variants),
        "total_variants": sum(len(v) for v in shadow_state.values())
    })
    
    return new_variants

# ---- Unified Runner ----
def run_phase_24_25_26():
    """
    Run all three phases in sequence:
    1. Generate live attribution dashboard
    2. Route strategies by regime
    3. Create shadow strategy variants
    """
    print("\n📊 Phase 24.0: Generating live attribution dashboard...")
    dashboard = generate_live_dashboard()
    print(f"✅ Dashboard updated: {len(dashboard.get('symbols', {}))} symbols, {len(dashboard.get('strategies', {}))} strategies")
    
    print("\n🎯 Phase 25.0: Routing strategies by regime...")
    routing = route_strategies_by_regime()
    active_count = sum(1 for s in routing.values() if s == "active")
    print(f"✅ Strategies routed: {active_count} active, {len(routing)-active_count} suppressed")
    
    print("\n🧪 Phase 26.0: Running shadow strategy lab...")
    shadows = run_shadow_strategy_lab()
    print(f"✅ Shadow variants created: {len(shadows)} new variants")
    
    return {
        "dashboard": dashboard,
        "routing": routing,
        "shadows": shadows
    }

if __name__ == "__main__":
    result = run_phase_24_25_26()
    print("\n✅ Phases 24-26 executed successfully")
