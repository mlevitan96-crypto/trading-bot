# src/multi_asset_orchestration.py
#
# Multi-Asset Orchestration for 11 USDT futures tickers (Major + L1 tiers)
# - Per-asset metrics & capacity evaluation
# - Regime-aware scoring and portfolio reweighting (tier-aware)
# - Scaling decisions (shadow → canary → production) with capacity gates
# - Portfolio-level capacity curves (global scaling frontier across all 11)
# - Unified audit packet for operator transparency
#
# Assets (USDT futures only):
# Major (2): BTCUSDT, ETHUSDT
# L1 (9): SOLUSDT, AVAXUSDT, DOTUSDT, TRXUSDT, XRPUSDT, ADAUSDT, DOGEUSDT, BNBUSDT, MATICUSDT

import os, json, time, math, random
from statistics import mean, stdev

# Use absolute paths relative to project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
AUDIT_LOG = os.path.join(LOG_DIR, "multi_asset_audit.jsonl")
PORTFOLIO_CAPACITY_LOG = os.path.join(LOG_DIR, "portfolio_capacity.jsonl")

ASSETS = [
    "BTCUSDT","ETHUSDT",
    "SOLUSDT","AVAXUSDT","DOTUSDT","TRXUSDT","XRPUSDT","ADAUSDT","DOGEUSDT","BNBUSDT","MATICUSDT"
]

TIERS = {
    "BTCUSDT":"major", "ETHUSDT":"major",
    "SOLUSDT":"l1","AVAXUSDT":"l1","DOTUSDT":"l1","TRXUSDT":"l1","XRPUSDT":"l1","ADAUSDT":"l1","DOGEUSDT":"l1","BNBUSDT":"l1","MATICUSDT":"l1"
}

# Tier multipliers (liquidity/robustness bias)
TIER_MULT = {"major":1.0,"l1":0.85}

def _now(): return int(time.time())
def _append_jsonl(path,obj): os.makedirs(os.path.dirname(path),exist_ok=True); open(path,"a").write(json.dumps(obj)+"\n")

# ----------------------------------------------------------------------
# Helpers: drawdown, profit factor, simple regime
# ----------------------------------------------------------------------
def max_drawdown(returns):
    eq, peak, mdd = 1.0, 1.0, 0.0
    for r in returns:
        eq *= (1+r)
        peak = max(peak, eq)
        dd = (eq - peak) / peak
        mdd = min(mdd, dd)
    return mdd

def profit_factor(returns):
    gains = sum(r for r in returns if r > 0)
    losses = abs(sum(r for r in returns if r < 0))
    return (gains / losses) if losses > 0 else float('inf')

def label_regime(price_series, lookback=50, chop_threshold=0.6):
    if len(price_series) < lookback+1: return "uncertain", 0.5, 0.01
    window = price_series[-lookback:]
    ups = sum(1 for i in range(1,len(window)) if window[i]["price"] > window[i-1]["price"])
    direction = ups / (lookback-1)
    returns = [math.log(window[i]["price"]/window[i-1]["price"]) for i in range(1,len(window))]
    vol = stdev(returns) if len(returns) > 1 else 0.0
    if abs(direction-0.5) <= 0.1 and vol <= 0.01: regime = "chop"
    elif direction >= chop_threshold and 0.005 <= vol <= 0.03: regime = "trend"
    else: regime = "uncertain"
    return regime, direction, vol

# ----------------------------------------------------------------------
# Metrics: expectancy, win rate, profit factor, drawdown
# ----------------------------------------------------------------------
def compute_metrics_from_trades(trades):
    rois = [t.get("roi",0.0) for t in trades if t.get("roi") is not None]
    if not rois:
        return {"expectancy":0.0,"win_rate":0.0,"profit_factor":0.0,"drawdown":0.0,"n":0}
    exp = mean(rois)
    wr = sum(1 for r in rois if r>0)/len(rois)
    pf = profit_factor(rois)
    dd = max_drawdown(rois)
    return {"expectancy":round(exp,6),"win_rate":round(wr,4),"profit_factor":round(pf,4),"drawdown":round(dd,4),"n":len(rois)}

# ----------------------------------------------------------------------
# Capacity: slippage, fill quality, capped drawdown
# ----------------------------------------------------------------------
def measure_slippage(expected_price, actual_price):
    return (actual_price-expected_price)/expected_price

def fill_quality(order, fills):
    total_filled = sum(f.get("size",0.0) for f in fills)
    completeness = total_filled / max(order.get("size",1.0), 1e-9)
    latencies = [f.get("latency_ms",0) for f in fills]
    avg_latency = mean(latencies) if latencies else 0.0
    latency_penalty = avg_latency/1000.0
    return completeness - latency_penalty

def compute_capacity(trades):
    if not trades:
        return {"avg_slippage":0.0,"avg_fill_quality":0.0,"max_drawdown":0.0,"n":0}
    slippages = [measure_slippage(t["expected"],t["actual"]) for t in trades if "expected" in t and "actual" in t]
    qualities = [fill_quality(t["order"],t.get("fills",[])) for t in trades if "order" in t]
    pnl_series = [t.get("roi", random.uniform(-0.02,0.03)) for t in trades]
    dd = max_drawdown(pnl_series)
    return {
        "avg_slippage":round(mean(slippages) if slippages else 0.0,6),
        "avg_fill_quality":round(mean(qualities) if qualities else 0.0,4),
        "max_drawdown":round(dd,4),
        "n":len(trades)
    }

# ----------------------------------------------------------------------
# Thresholds and scoring
# ----------------------------------------------------------------------
def perf_thresholds(m):
    return (m["expectancy"]>0 and m["win_rate"]>=0.60 and m["profit_factor"]>=1.5 and m["drawdown"]>=-0.05)

def capacity_thresholds(c):
    return (c["avg_slippage"]<=0.002 and c["avg_fill_quality"]>=0.80 and c["max_drawdown"]>=-0.05)

def asset_score(metrics, capacity, regime, tier, stability_penalty=0.1, fee_penalty=0.0005):
    regime_mult = {"trend":1.0,"chop":0.7,"uncertain":0.5}.get(regime,0.6)
    tier_mult = TIER_MULT.get(tier,0.85)
    lift = metrics["expectancy"]
    wr   = metrics["win_rate"]
    pf   = metrics["profit_factor"]
    dd   = metrics["drawdown"]
    stability = max(0.0, 0.5 - 0.25*pf + 0.2*(0.6-wr))
    cap_drag = 0.5*capacity["avg_slippage"] - 0.2*(capacity["avg_fill_quality"]-0.8)
    score = tier_mult * regime_mult * (lift + 0.2*wr + 0.1*pf + dd) - stability_penalty*stability - fee_penalty - cap_drag
    return round(score,6)

# ----------------------------------------------------------------------
# Portfolio reweighting (tier-aware, fee and stability aware)
# ----------------------------------------------------------------------
def reweight_portfolio(asset_packets, min_obs=30, min_capacity_obs=10):
    scored = []
    for ap in asset_packets:
        m, c = ap["metrics"], ap["capacity"]
        if m["n"] < min_obs or c["n"] < min_capacity_obs:
            scored.append({"asset":ap["asset"],"tier":ap["tier"],"score":0.0}); continue
        score = asset_score(m,c,ap["regime"],ap["tier"])
        if not (perf_thresholds(m) and capacity_thresholds(c)):
            score = max(0.0, score*0.2)
        scored.append({"asset":ap["asset"],"tier":ap["tier"],"score":max(0.0,score)})
    total = sum(s["score"] for s in scored) or 1.0
    weights = {s["asset"]: round(s["score"]/total,6) for s in scored}
    # Enforce minimum presence for majors
    for major in ["BTCUSDT","ETHUSDT"]:
        weights[major] = max(weights.get(major,0.0), 0.05)
    # Normalize after baseline bump
    norm = sum(weights.values()) or 1.0
    weights = {a: round(w/norm,6) for a,w in weights.items()}
    return {"weights":weights,"scored":scored}

# ----------------------------------------------------------------------
# Scaling decisions per asset
# ----------------------------------------------------------------------
def scaling_decision(current_mode, metrics, capacity, audit_pass=True):
    decision = {"current_mode":current_mode}
    ok = audit_pass and perf_thresholds(metrics) and capacity_thresholds(capacity)
    if not ok:
        decision["next_mode"] = current_mode; decision["action"] = "HOLD"
    else:
        if current_mode=="shadow":
            decision["next_mode"]="canary"; decision["action"]="PROMOTE"
        elif current_mode=="canary":
            decision["next_mode"]="production"; decision["action"]="PROMOTE"
        else:
            decision["next_mode"]="production"; decision["action"]="HOLD"
    return decision

# ----------------------------------------------------------------------
# Portfolio-level capacity curve (global scaling frontier)
# ----------------------------------------------------------------------
def portfolio_capacity_curve(total_allocations, per_asset_capacity_trades, portfolio_weights):
    """
    total_allocations: list of total portfolio allocation fractions to test (e.g., [0.05,0.1,0.2,0.4])
    per_asset_capacity_trades: {symbol: [{"expected":..,"actual":..,"order":{...},"fills":[...],"roi":..},...]}
    portfolio_weights: {symbol: weight} (from reweighting)
    Returns curves summarizing avg slippage, fill quality, and drawdown at portfolio level.
    """
    curves = []
    # Normalize weights to ensure sum=1 even if missing assets
    norm = sum(portfolio_weights.values()) or 1.0
    weights = {a: (portfolio_weights.get(a,0.0)/norm) for a in ASSETS}

    for alloc in total_allocations:
        # Weighted aggregation across assets
        asset_stats = []
        for a in ASSETS:
            trades = per_asset_capacity_trades.get(a, [])
            if not trades: 
                asset_stats.append({"asset":a,"w":weights[a],"slip":0.0,"fq":0.0,"roi_series":[0.0]})
                continue
            slippages = [measure_slippage(t["expected"], t["actual"]) for t in trades if "expected" in t and "actual" in t]
            qualities = [fill_quality(t["order"], t.get("fills",[])) for t in trades if "order" in t]
            rois = [t.get("roi", random.uniform(-0.02,0.03)) for t in trades]
            # Scale impact with allocation weight (higher alloc → more slippage pressure, lower fill quality)
            w = weights[a]
            slip_w = (mean(slippages) if slippages else 0.0) * (1 + 2.0 * alloc * w)   # pressure factor
            fq_w   = (mean(qualities) if qualities else 0.0) - (0.1 * alloc * w)      # small quality drag
            roi_w  = [r * (1 - 0.5 * alloc * w) for r in rois]                        # performance drag with size
            asset_stats.append({"asset":a,"w":w,"slip":slip_w,"fq":fq_w,"roi_series":roi_w})

        # Aggregate portfolio-level stats
        avg_slippage = sum(s["slip"] * s["w"] for s in asset_stats)
        avg_fill_quality = sum(s["fq"] * s["w"] for s in asset_stats)
        # Merge ROI series by weight (approximate)
        merged_roi = []
        for s in asset_stats:
            # sample a subset proportional to weight to avoid huge series
            take = max(5, int(20 * s["w"]))
            merged_roi.extend(s["roi_series"][:take])
        max_dd = max_drawdown(merged_roi if merged_roi else [0.0])

        curves.append({
            "allocation": round(alloc,4),
            "avg_slippage": round(avg_slippage,6),
            "avg_fill_quality": round(avg_fill_quality,4),
            "max_drawdown": round(max_dd,4)
        })

    packet = {"ts":_now(),"weights":weights,"curves":curves}
    _append_jsonl(PORTFOLIO_CAPACITY_LOG, packet)
    return curves

# ----------------------------------------------------------------------
# Orchestration cycle
# ----------------------------------------------------------------------
def multi_asset_cycle(price_series_by_asset, trades_by_asset, capacity_trades_by_asset, modes_by_asset=None, audit_pass=True, portfolio_alloc_tests=None):
    """
    price_series_by_asset: {symbol: [{"ts":..,"price":..},...]}
    trades_by_asset: {symbol: [{"roi":..,"ts":..},...]}
    capacity_trades_by_asset: {symbol: [{"expected":..,"actual":..,"order":{...},"fills":[...],"roi":..},...]}
    modes_by_asset: {symbol: "shadow"|"canary"|"production"}
    portfolio_alloc_tests: list of total allocation levels to test for portfolio capacity (e.g., [0.05,0.1,0.2,0.4])
    """
    packets = []
    for symbol in ASSETS:
        ps = price_series_by_asset.get(symbol, [])
        ts = trades_by_asset.get(symbol, [])
        ct = capacity_trades_by_asset.get(symbol, [])
        regime, direction, vol = label_regime(ps)
        m = compute_metrics_from_trades(ts)
        c = compute_capacity(ct)
        mode = (modes_by_asset or {}).get(symbol, "shadow")
        decision = scaling_decision(mode, m, c, audit_pass=audit_pass)
        packets.append({
            "asset": symbol,
            "tier": TIERS[symbol],
            "regime": regime,
            "direction": round(direction,3),
            "vol": round(vol,4),
            "metrics": m,
            "capacity": c,
            "scaling": decision
        })

    weights = reweight_portfolio(packets)
    portfolio_curves = []
    if portfolio_alloc_tests:
        portfolio_curves = portfolio_capacity_curve(portfolio_alloc_tests, capacity_trades_by_asset, weights["weights"])

    audit = {"ts":_now(), "assets": packets, "portfolio_weights": weights, "portfolio_capacity_curves": portfolio_curves}
    _append_jsonl(AUDIT_LOG, audit)
    return {"assets":packets,"weights":weights,"portfolio_capacity_curves":portfolio_curves,"audit":audit}

# ----------------------------------------------------------------------
# CLI quick run (mock data for 11 assets)
# ----------------------------------------------------------------------
if __name__ == "__main__":
    def mock_prices():
        base = 100 + random.uniform(-10,10)
        return [{"ts":_now()-i*60, "price": base*(1+0.0005*i) + random.uniform(-0.5,0.5)} for i in range(120)]
    def mock_trades(n=80):
        return [{"ts":_now()-random.randint(0,3600), "roi": random.uniform(-0.02,0.03)} for _ in range(n)]
    def mock_capacity_trades(n=30):
        arr=[]
        for _ in range(n):
            exp = 100 + random.uniform(-2,2)
            act = exp*(1+random.uniform(-0.001,0.003))
            order = {"size": random.uniform(0.1,1.5), "ts": _now()}
            fills = [{"size":order["size"]*random.uniform(0.4,0.7),"latency_ms":random.randint(80,220)},
                     {"size":order["size"]*random.uniform(0.3,0.6),"latency_ms":random.randint(120,260)}]
            arr.append({"expected":exp,"actual":act,"order":order,"fills":fills,"roi":random.uniform(-0.02,0.03)})
        return arr

    price_series_by_asset = {a: mock_prices() for a in ASSETS}
    trades_by_asset = {a: mock_trades(68) for a in ASSETS}
    capacity_trades_by_asset = {a: mock_capacity_trades(25) for a in ASSETS}
    modes_by_asset = {a: "shadow" for a in ASSETS}

    summary = multi_asset_cycle(
        price_series_by_asset,
        trades_by_asset,
        capacity_trades_by_asset,
        modes_by_asset,
        portfolio_alloc_tests=[0.05,0.10,0.20,0.40]
    )

    print(json.dumps({
        "weights":summary["weights"],
        "first_asset_packet":summary["assets"][0],
        "portfolio_capacity_curves":summary["portfolio_capacity_curves"]
    }, indent=2))
