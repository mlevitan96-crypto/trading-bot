# src/intraday_scheduler.py
#
# Intraday Scheduler – Continuous learning loop with automatic surge layering
# Runs every 5–10 minutes:
#   1) Execute intraday_engine.intraday_cycle(...) to produce intraday_overrides.json
#   2) Execute performance_surge_pack.performance_surge_cycle(...) to produce surge_overrides.json
#   3) Merge and apply overrides with clear precedence (Surge > Intraday > Base)
#   4) Write final configs/intraday_applied.json for immediate use by the execution bridge
#
# Notes:
#   - Replace the mock data feeders with your live price/trade streams.
#   - This scheduler is pure Python; integrate with your existing orchestrator/service runner.
#   - Precedence: surge overrides clamp/boost/kill; intraday engine sets params/overlays/router.

import os, json, time, random
from datetime import datetime
from statistics import mean

# Paths
LOG_DIR = "logs"
CONFIG_DIR = "configs"
INTRA_LOG = os.path.join(LOG_DIR, "intraday_scheduler.jsonl")

INTRA_OVERRIDES_PATH = os.path.join(CONFIG_DIR, "intraday_overrides.json")
SURGE_OVERRIDES_PATH = os.path.join(CONFIG_DIR, "surge_overrides.json")
APPLIED_OVERRIDES_PATH = os.path.join(CONFIG_DIR, "intraday_applied.json")

# Assets universe
ASSETS = [
    "BTCUSDT","ETHUSDT","SOLUSDT","AVAXUSDT","DOTUSDT","TRXUSDT",
    "XRPUSDT","ADAUSDT","DOGEUSDT","BNBUSDT","MATICUSDT"
]

def _now(): return int(time.time())
def _ts(): return datetime.utcnow().isoformat()+"Z"
def _append_jsonl(path,obj): os.makedirs(os.path.dirname(path),exist_ok=True); open(path,"a").write(json.dumps(obj)+"\n")
def _read_json(path, default=None):
    if not os.path.exists(path): return default
    try:
        with open(path,"r") as f: return json.load(f)
    except: return default

# --------------------------------------------------------------------------------------
# Imports of previously defined modules (assumed in the project tree)
# --------------------------------------------------------------------------------------
# You already have these files from prior steps:
#   - src/intraday_engine.py
#   - src/performance_surge_pack.py
#
# We import their public functions here. If your environment prefers direct module imports,
# replace the relative imports accordingly.

try:
    from intraday_engine import intraday_cycle as run_intraday_cycle
except Exception:
    # Fallback: minimal stub to avoid import errors in dry runs; replace with actual import in prod
    def run_intraday_cycle(multi_asset_summary, per_trade_logs_by_asset, recent_prices_by_asset, base_overrides=None, current_position_scale=None):
        intraday_overrides = {"ts": _now(), "assets": {}}
        for a in ASSETS:
            intraday_overrides["assets"][a] = {
                "overlays": [{"overlay":"risk_reducer","enable":True,"params":{"position_scale":0.9}}],
                "bandit_params": {"lookback": 50, "threshold": 0.3, "stop_atr": 3, "take_atr": 4},
                "bandit_confidence": 0.7,
                "mid_session_swap": False,
                "execution_router": {"mode":"maker","post_only":True,"slice_parts":[3,5],"delay_ms":[50,80],"hold_orders":False},
                "position_scale": current_position_scale.get(a,1.0) if current_position_scale else 1.0,
                "apply_rules": {"capacity_checks": True, "intraday_enabled": True, "experiment_slots": 2}
            }
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(INTRA_OVERRIDES_PATH, "w") as f: json.dump(intraday_overrides, f, indent=2)
        return {"overrides": intraday_overrides, "audit": {"stub": True}}

try:
    from performance_surge_pack import performance_surge_cycle as run_surge_cycle
except Exception:
    def run_surge_cycle(multi_asset_summary, per_trade_logs_by_asset, intraday_overrides,
                        anomalies_history_by_asset=None, sentiment_series_by_asset=None, base_position_scales=None):
        surge = {"ts": _now(), "assets": {}}
        for a in ASSETS:
            surge["assets"][a] = {
                "apply_rules": {"halt_entries": False, "kill_params": False, "boost_params": False,
                                "router_harden": False, "sentiment_decay": 0.0, "capacity_checks": True},
                "position_scale": intraday_overrides.get("assets", {}).get(a, {}).get("position_scale", 1.0),
                "rolling_metrics": {"wr": 0.55, "ev": 0.0002, "pf": 1.35, "n": 40},
                "pnl_guard": {"halt_entries": False, "rolling_pnl": 0.003},
                "anomaly_counts": {},
                "parity_scale_info": {"base": 1.0, "parity": 1.0},
                "sentiment_health": {"decay": 0.0, "lag_ok": True, "variance_ok": True}
            }
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(SURGE_OVERRIDES_PATH, "w") as f: json.dump(surge, f, indent=2)
        return {"overrides": surge, "audit": {"stub": True}}

# --------------------------------------------------------------------------------------
# Merge logic: Surge > Intraday > Base
# --------------------------------------------------------------------------------------

def merge_overrides(intraday_overrides, surge_overrides):
    """
    Field precedence per asset:
      - position_scale: surge clamp/boost wins
      - apply_rules: merge keys; surge's kill/halt/harden/decay set hard constraints
      - execution_router: start from intraday; if router_harden, increase slices & delay, avoid maker queues
      - overlays: intraday overlays retained; if halt_entries, prefer risk_reducer overlay on
      - bandit_params: intraday chose params; if kill_params, mark as disabled
    """
    final = {"ts": _now(), "source": "intraday_scheduler", "assets": {}}

    for a in ASSETS:
        intra = (intraday_overrides or {}).get("assets", {}).get(a, {})
        surge = (surge_overrides or {}).get("assets", {}).get(a, {})

        # Base fields
        position_scale = surge.get("position_scale", intra.get("position_scale", 1.0))
        apply_rules_intra = intra.get("apply_rules", {})
        apply_rules_surge = surge.get("apply_rules", {})

        # Merge apply rules (surge constraints dominate)
        apply_rules = dict(apply_rules_intra)
        for k, v in apply_rules_surge.items():
            apply_rules[k] = v

        # Execution router: start from intraday plan
        router = intra.get("execution_router", {"mode":"maker","post_only":True,"slice_parts":[3,5],"delay_ms":[50,80],"hold_orders":False})
        if apply_rules.get("router_harden"):
            # Harden: more slices, more delay, avoid maker queues if adverse selection risk
            router["slice_parts"] = [max(router["slice_parts"][0], 5), max(router["slice_parts"][-1], 9)]
            router["delay_ms"] = [max(router["delay_ms"][0], 100), max(router["delay_ms"][-1], 160)]
            router["mode"] = "taker" if router.get("mode") == "maker" else router.get("mode", "taker")
            router["post_only"] = False
            router["hold_orders"] = True

        # Overlays: ensure risk reducer if entries halted
        overlays = intra.get("overlays", [])
        if apply_rules.get("halt_entries"):
            has_rr = any(o.get("overlay")=="risk_reducer" and o.get("enable") for o in overlays)
            if not has_rr:
                overlays.append({"overlay":"risk_reducer","enable":True,"params":{"position_scale":max(0.5, position_scale)}})

        # Bandit params and kill/boost
        bandit_params = intra.get("bandit_params", {})
        if apply_rules.get("kill_params"):
            bandit_params = {"disabled": True, "reason": "mid_session_kill"}
        elif apply_rules.get("boost_params"):
            # Small risk-aware boost to take profit
            position_scale = round(min(1.0, position_scale + 0.03), 4)

        final["assets"][a] = {
            "position_scale": position_scale,
            "apply_rules": apply_rules,
            "execution_router": router,
            "overlays": overlays,
            "bandit_params": bandit_params,
            "bandit_confidence": intra.get("bandit_confidence"),
            "mid_session_swap": intra.get("mid_session_swap", False),
            "rolling_metrics": surge.get("rolling_metrics", {}),
            "pnl_guard": surge.get("pnl_guard", {}),
            "anomaly_counts": surge.get("anomaly_counts", {}),
            "sentiment_health": surge.get("sentiment_health", {})
        }

    return final

# --------------------------------------------------------------------------------------
# Data feeders (replace with live system hooks)
# --------------------------------------------------------------------------------------

def mock_multi_asset_summary():
    def mock_asset(a):
        return {
            "asset": a,
            "regime": random.choice(["trend","chop","uncertain"]),
            "metrics": {
                "expectancy": random.uniform(-0.001, 0.004),
                "win_rate": random.uniform(0.45, 0.75),
                "profit_factor": random.uniform(1.0, 2.5),
                "drawdown": random.uniform(-0.08, -0.01),
                "n": random.randint(50, 140)
            },
            "capacity": {
                "avg_slippage": random.uniform(0.0004, 0.0022),
                "avg_fill_quality": random.uniform(0.80, 0.90),
                "max_drawdown": random.uniform(-0.06, -0.01),
                "n": random.randint(20, 40)
            }
        }
    return {"assets": [mock_asset(a) for a in ASSETS]}

def mock_per_trade_logs_by_asset():
    def mock_trade():
        roi = random.uniform(-0.02, 0.03)
        expected = 100 + random.uniform(-1,1)
        actual = expected*(1 + random.uniform(-0.0015, 0.0025))
        order = {"size": random.uniform(0.1, 1.5)}
        fills = [{"size": order["size"]*random.uniform(0.4,0.7), "latency_ms": random.randint(80,220)},
                 {"size": order["size"]*random.uniform(0.3,0.6), "latency_ms": random.randint(120,260)}]
        return {"roi": roi, "expected": expected, "actual": actual, "order": order, "fills": fills}
    return {a: [mock_trade() for _ in range(random.randint(80, 160))] for a in ASSETS}

def mock_recent_prices_by_asset():
    def mock_prices(n=220):
        base = 100 + random.uniform(-2,2)
        series = [base]
        for _ in range(n-1):
            series.append(series[-1]*(1 + random.uniform(-0.003,0.003)))
        return series
    return {a: mock_prices(random.randint(120,220)) for a in ASSETS}

# --------------------------------------------------------------------------------------
# Scheduler loop
# --------------------------------------------------------------------------------------

def run_once():
    # Fetch data
    multi_asset_summary = mock_multi_asset_summary()
    per_trade_logs_by_asset = mock_per_trade_logs_by_asset()
    recent_prices_by_asset = mock_recent_prices_by_asset()

    # Intraday engine
    intra = run_intraday_cycle(
        multi_asset_summary=multi_asset_summary,
        per_trade_logs_by_asset=per_trade_logs_by_asset,
        recent_prices_by_asset=recent_prices_by_asset,
        base_overrides=_read_json(os.path.join(CONFIG_DIR, "profit_push_overrides.json")) or _read_json(os.path.join(CONFIG_DIR, "accelerator_overrides.json")) or _read_json(os.path.join(CONFIG_DIR, "strategy_overrides.json")),
        current_position_scale={a: random.uniform(0.6, 1.0) for a in ASSETS}
    )

    # Surge pack
    surge = run_surge_cycle(
        multi_asset_summary=multi_asset_summary,
        per_trade_logs_by_asset=per_trade_logs_by_asset,
        intraday_overrides=intra["overrides"],
        anomalies_history_by_asset={a: [] for a in ASSETS},
        sentiment_series_by_asset={a: [{"ts": _now()-random.randint(60,1200), "score": random.uniform(-0.3,0.3)} for _ in range(random.randint(3,8))] for a in ASSETS},
        base_position_scales={a: intra["overrides"]["assets"][a]["position_scale"] for a in ASSETS}
    )

    # Merge and apply
    final_overrides = merge_overrides(intraday_overrides=intra["overrides"], surge_overrides=surge["overrides"])
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(APPLIED_OVERRIDES_PATH, "w") as f:
        json.dump(final_overrides, f, indent=2)

    # Log summary
    summary = {
        "ts": _ts(),
        "intraday_written": INTRA_OVERRIDES_PATH,
        "surge_written": SURGE_OVERRIDES_PATH,
        "applied_written": APPLIED_OVERRIDES_PATH,
        "example_asset": ASSETS[0],
        "position_scale": final_overrides["assets"][ASSETS[0]]["position_scale"],
        "halt_entries": final_overrides["assets"][ASSETS[0]]["apply_rules"]["halt_entries"],
        "kill_params": final_overrides["assets"][ASSETS[0]]["apply_rules"]["kill_params"],
        "router_mode": final_overrides["assets"][ASSETS[0]]["execution_router"]["mode"]
    }
    _append_jsonl(INTRA_LOG, summary)
    print(json.dumps(summary, indent=2))

def run_scheduler_loop(interval_seconds=480, max_cycles=None):
    """
    Run continuously with a fixed sleep interval (default 8 minutes).
    Set max_cycles for testing; leave as None for indefinite.
    """
    cycles = 0
    while True:
        run_once()
        cycles += 1
        if max_cycles and cycles >= max_cycles:
            break
        time.sleep(interval_seconds)

# --------------------------------------------------------------------------------------
# CLI quick run
# --------------------------------------------------------------------------------------

if __name__ == "__main__":
    # For demo/testing, run 2 cycles with 5-second interval
    run_scheduler_loop(interval_seconds=5, max_cycles=2)
