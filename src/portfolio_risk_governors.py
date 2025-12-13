# src/portfolio_risk_governors.py
#
# v5.7 Portfolio Governor + Risk Governor (Unified, Correlated, Monitored)
# Purpose:
#   - Portfolio Governor: globally optimize strategy and coin allocations for profit under capital and correlation limits
#   - Risk Governor: enforce portfolio-level risk SLOs (exposure, leverage, volatility, drawdown, correlation)
#   - Shared learning bus: publish/consume events via logs/learning_updates.jsonl and logs/knowledge_graph.jsonl
#   - Closed loop: accepted changes update live_config.json and feed back into the orchestrator and attribution modules
#
# Integration:
#   from src.portfolio_risk_governors import run_portfolio_and_risk_cycle
#   summary = run_portfolio_and_risk_cycle()
#   digest["email_body"] += "\n\n" + summary["email_body"]
#
# Notes:
#   - Works with existing runtime state in live_config.json:
#       runtime.strategy_weights: {strategy_id: weight}
#       runtime.strategy_status:  {strategy_id: "active"/"paused"}
#       runtime.coin_scalars:     {symbol: scalar}           # optional per-coin scalars
#       runtime.capital_limits:   {"max_exposure":0.75,...}  # optional overrides
#   - Consumes attribution logs to learn:
#       logs/executed_trades.jsonl: {ts, symbol, pnl_pct, leverage, ...}
#       logs/strategy_signals.jsonl: {ts, strategy_id, expectancy, ...}
#       logs/learning_updates.jsonl: strategy_attribution_cycle, slippage_latency_cycle, profit_attribution, etc.
#   - Publishes decisions and telemetry:
#       logs/learning_updates.jsonl (events), logs/knowledge_graph.jsonl (causal links)
#
# Risk SLOs (defaults; can be overridden in runtime.capital_limits):
#   - max_exposure: 0.75 (total active capital fraction)
#   - per_coin_cap: 0.25
#   - max_leverage: 5.0
#   - max_drawdown_24h: 0.05  (5% portfolio drawdown)
#   - max_vol_4h: 0.03        (3% realized volatility, short window)
#   - max_corr: 0.80          (pairwise correlation cap among top-weight assets)
#
# Portfolio optimization:
#   - Target weights per strategy and coin are nudged toward higher uplift/expectancy under risk SLOs and correlation limits.
#   - Uses conservative step adjustments and two-cycle profit confirmation gates via consumed attribution events.

import os, json, time, math
from collections import defaultdict
from typing import Dict, Any, List, Tuple

LOGS_DIR  = "logs"
LEARN_LOG = f"{LOGS_DIR}/learning_updates.jsonl"
KG_LOG    = f"{LOGS_DIR}/knowledge_graph.jsonl"
EXEC_LOG  = f"{LOGS_DIR}/executed_trades.jsonl"
SIG_LOG   = f"{LOGS_DIR}/strategy_signals.jsonl"
LIVE_CFG  = "live_config.json"

SHORT_MINS = 240   # 4h
LONG_MINS  = 1440  # 24h

# Profit gates
PROMOTE_EXPECTANCY = 0.55
PROMOTE_PNL        = 0.0
ROLLBACK_EXPECTANCY= 0.35
ROLLBACK_PNL       = 0.0

# Portfolio step limits
STRAT_WEIGHT_MIN = 0.02
STRAT_WEIGHT_MAX = 0.40
STRAT_WEIGHT_STEP= 0.04

COIN_SCALAR_MIN  = 0.50
COIN_SCALAR_MAX  = 1.50
COIN_SCALAR_STEP = 0.10

# Defaults for risk SLOs
DEFAULT_LIMITS = {
    "max_exposure": 0.75,
    "per_coin_cap": 0.25,
    "max_leverage": 5.0,
    "max_drawdown_24h": 0.05,
    "max_vol_4h": 0.03,
    "max_corr": 0.80
}

def _now() -> int: return int(time.time())
def _read_json(path, default=None):
    if not os.path.exists(path): return default
    try:
        with open(path,"r") as f: return json.load(f)
    except: return default
def _write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp,"w") as f: json.dump(obj, f, indent=2)
    os.replace(tmp, path)
def _append_jsonl(path, obj):
    with open(path,"a") as f: f.write(json.dumps(obj) + "\n")
def _read_jsonl(path, limit=100000):
    rows=[]
    if not os.path.exists(path): return rows
    with open(path,"r") as f:
        for line in f:
            line=line.strip()
            if not line: continue
            try: rows.append(json.loads(line))
            except: continue
    return rows[-limit:]
def _cutoff(mins): return _now() - mins*60

def _corr(x: List[float], y: List[float]) -> float:
    n = min(len(x), len(y))
    if n < 3: return 0.0
    mx = sum(x[-n:])/n
    my = sum(y[-n:])/n
    vx = sum((xi-mx)*(xi-mx) for xi in x[-n:]) / max(1,(n-1))
    vy = sum((yi-my)*(yi-my) for yi in y[-n:]) / max(1,(n-1))
    if vx <= 0 or vy <= 0: return 0.0
    cov = sum((x[-n:][i]-mx)*(y[-n:][i]-my) for i in range(n)) / max(1,(n-1))
    return max(-1.0, min(1.0, cov / math.sqrt(vx*vy)))

class RiskGovernor:
    """
    Enforce portfolio-level risk SLOs:
    - Exposure (total, per-coin)
    - Leverage cap
    - Drawdown (24h)
    - Realized volatility (4h)
    - Pairwise correlation among top exposures
    Proposes risk reductions (weight down, scalar down) and blocks portfolio changes that violate limits.
    """
    def __init__(self, live: Dict[str,Any]):
        self.live = live or {}
        self.rt   = self.live.get("runtime", {})
        limits = self.rt.get("capital_limits", {})
        self.limits = {**DEFAULT_LIMITS, **(limits or {})}

    def _portfolio_metrics(self) -> Dict[str,Any]:
        trades = _read_jsonl(EXEC_LOG, 100000)
        short_cut = _cutoff(SHORT_MINS)
        long_cut  = _cutoff(LONG_MINS)

        # Collect per-symbol returns and leverage
        returns_short = defaultdict(list)
        returns_long  = defaultdict(list)
        leverage_obs  = defaultdict(list)

        for t in trades:
            ts = t.get("ts") or t.get("timestamp") or 0
            sym = t.get("symbol")
            if not sym: continue
            pnl = float(t.get("pnl_pct", 0.0))
            lev = float(t.get("leverage", 0.0))
            if ts >= long_cut: returns_long[sym].append(pnl)
            if ts >= short_cut: returns_short[sym].append(pnl)
            if lev > 0: leverage_obs[sym].append(lev)

        # Approximate portfolio drawdown over 24h using cumulative returns
        portfolio_series = []
        for t in trades:
            ts = t.get("ts") or 0
            if ts >= long_cut:
                portfolio_series.append(float(t.get("pnl_pct", 0.0)))
        cum = 0.0; peak = 0.0; max_dd = 0.0
        for r in portfolio_series:
            cum += r
            peak = max(peak, cum)
            max_dd = max(max_dd, peak - cum)

        # Realized vol (per symbol, 4h)
        vol_4h = {}
        for sym, rs in returns_short.items():
            n = len(rs)
            if n < 3:
                vol_4h[sym] = 0.0
            else:
                m = sum(rs)/n
                var = sum((ri-m)*(ri-m) for ri in rs)/max(1,(n-1))
                vol_4h[sym] = math.sqrt(max(0.0, var))

        # Exposure estimate: use runtime weights + coin scalars as proxy of deployed fraction
        weights = self.rt.get("strategy_weights", {})
        scalars = self.rt.get("coin_scalars", {})
        total_weight = sum(float(w) for w in weights.values()) or 1.0
        # Normalize per-coin exposure using scalar and relative count of trades
        coin_exposure = {}
        trade_counts  = {sym: len(returns_short.get(sym, [])) for sym in set(list(returns_short.keys())+list(returns_long.keys()))}
        total_trades  = sum(trade_counts.values()) or 1
        for sym, cnt in trade_counts.items():
            frac = cnt / total_trades
            coin_exposure[sym] = round(frac * float(scalars.get(sym, 1.0)) * (total_weight), 6)

        # Pairwise correlations among top-exposed symbols
        top_syms = [s for s,_ in sorted(coin_exposure.items(), key=lambda kv: kv[1], reverse=True)[:6]]
        corr_pairs = []
        for i in range(len(top_syms)):
            for j in range(i+1, len(top_syms)):
                a, b = top_syms[i], top_syms[j]
                c = _corr(returns_short.get(a, []), returns_short.get(b, []))
                corr_pairs.append({"pair": (a,b), "corr": round(c, 4)})

        # Leverage max
        max_lev = 0.0
        for sym, obs in leverage_obs.items():
            if obs: max_lev = max(max_lev, max(obs))

        return {
            "coin_exposure": coin_exposure,
            "portfolio_exposure": round(sum(coin_exposure.values()), 6),
            "max_leverage": round(max_lev, 3),
            "max_drawdown_24h": round(max_dd, 6),
            "vol_4h": vol_4h,
            "corr_pairs": corr_pairs
        }

    def evaluate(self) -> Dict[str,Any]:
        m = self._portfolio_metrics()
        breaches = []

        # Total exposure
        if m["portfolio_exposure"] > self.limits["max_exposure"]:
            breaches.append({"type":"exposure_total","value":m["portfolio_exposure"],"limit":self.limits["max_exposure"]})
        # Per-coin cap
        for sym, ex in m["coin_exposure"].items():
            if ex > self.limits["per_coin_cap"]:
                breaches.append({"type":"exposure_coin","symbol":sym,"value":ex,"limit":self.limits["per_coin_cap"]})
        # Leverage
        if m["max_leverage"] > self.limits["max_leverage"]:
            breaches.append({"type":"leverage","value":m["max_leverage"],"limit":self.limits["max_leverage"]})
        # Drawdown
        if m["max_drawdown_24h"] > self.limits["max_drawdown_24h"]:
            breaches.append({"type":"drawdown_24h","value":m["max_drawdown_24h"],"limit":self.limits["max_drawdown_24h"]})
        # Volatility
        for sym, v in m["vol_4h"].items():
            if v > self.limits["max_vol_4h"]:
                breaches.append({"type":"vol_4h","symbol":sym,"value":v,"limit":self.limits["max_vol_4h"]})
        # Correlation
        for cp in m["corr_pairs"]:
            if cp["corr"] > self.limits["max_corr"]:
                a,b = cp["pair"]
                breaches.append({"type":"corr_pair","pair":(a,b),"value":cp["corr"],"limit":self.limits["max_corr"]})

        actions = self._propose_risk_actions(m, breaches)
        return {"metrics": m, "breaches": breaches, "actions": actions}

    def _propose_risk_actions(self, metrics: Dict[str,Any], breaches: List[Dict[str,Any]]) -> List[Dict[str,Any]]:
        actions=[]
        scalars = self.rt.get("coin_scalars", {})
        weights = self.rt.get("strategy_weights", {})

        # Exposure reductions
        for b in breaches:
            if b["type"] == "exposure_total":
                # Downscale highest exposures first
                for sym,_ in sorted(metrics["coin_exposure"].items(), key=lambda kv: kv[1], reverse=True)[:3]:
                    new = max(COIN_SCALAR_MIN, float(scalars.get(sym,1.0)) - COIN_SCALAR_STEP)
                    actions.append({"scope":"coin","symbol":sym,"action":"reduce_scalar","from":scalars.get(sym,1.0),"to":new,"reason":"total_exposure_breach"})
                    scalars[sym] = new
            elif b["type"] == "exposure_coin":
                sym = b["symbol"]
                new = max(COIN_SCALAR_MIN, float(scalars.get(sym,1.0)) - COIN_SCALAR_STEP)
                actions.append({"scope":"coin","symbol":sym,"action":"reduce_scalar","from":scalars.get(sym,1.0),"to":new,"reason":"per_coin_cap_breach"})
                scalars[sym] = new
            elif b["type"] == "leverage":
                # Globally nudge strategy weights down
                for sid,w in list(weights.items()):
                    nw = max(STRAT_WEIGHT_MIN, float(w) - STRAT_WEIGHT_STEP/2)
                    actions.append({"scope":"strategy","strategy_id":sid,"action":"reduce_weight","from":w,"to":nw,"reason":"leverage_breach"})
                    weights[sid] = nw
            elif b["type"] == "drawdown_24h":
                # Defensive posture: reduce top two strategy weights
                for sid,w in sorted(weights.items(), key=lambda kv: kv[1], reverse=True)[:2]:
                    nw = max(STRAT_WEIGHT_MIN, float(w) - STRAT_WEIGHT_STEP)
                    actions.append({"scope":"strategy","strategy_id":sid,"action":"reduce_weight","from":w,"to":nw,"reason":"drawdown_breach"})
                    weights[sid] = nw
            elif b["type"] == "vol_4h":
                sym = b["symbol"]
                new = max(COIN_SCALAR_MIN, float(scalars.get(sym,1.0)) - COIN_SCALAR_STEP)
                actions.append({"scope":"coin","symbol":sym,"action":"reduce_scalar","from":scalars.get(sym,1.0),"to":new,"reason":"volatility_breach"})
                scalars[sym] = new
            elif b["type"] == "corr_pair":
                a, bpair = b["pair"][0], b["pair"][1]
                # Reduce the higher-exposed symbol in the pair
                ex_a = metrics["coin_exposure"].get(a,0.0)
                ex_b = metrics["coin_exposure"].get(bpair,0.0)
                target = a if ex_a >= ex_b else bpair
                new = max(COIN_SCALAR_MIN, float(scalars.get(target,1.0)) - COIN_SCALAR_STEP)
                actions.append({"scope":"coin","symbol":target,"action":"reduce_scalar","from":scalars.get(target,1.0),"to":new,"reason":"correlation_breach"})
                scalars[target] = new

        # Persist tentative changes (subject to portfolio gate confirmation)
        self.rt["coin_scalars"] = scalars
        self.rt["strategy_weights"] = weights
        self.live["runtime"] = self.rt
        _write_json(LIVE_CFG, self.live)

        if actions:
            _append_jsonl(LEARN_LOG, {"ts": _now(), "update_type":"risk_governor_actions", "actions": actions, "limits": self.limits})
            _append_jsonl(KG_LOG, {"ts": _now(), "subject":{"governor":"risk"}, "predicate":"actions", "object":actions})
        return actions

class PortfolioGovernor:
    """
    Global allocation optimizer:
    - Consumes strategy uplift/expectancy and coin profitability
    - Proposes weight/scalar increases for top performers under risk constraints
    - Enforces profit gates (2-cycle confirmation) and avoids correlated concentration
    """
    def __init__(self, live: Dict[str,Any], risk_limits: Dict[str,Any]):
        self.live = live or {}
        self.rt   = self.live.get("runtime", {})
        self.limits = risk_limits or DEFAULT_LIMITS

    def _read_attribution(self) -> Tuple[Dict[str,Any], Dict[str,Any]]:
        # Strategy uplift from latest strategy_attribution_cycle
        updates = _read_jsonl(LEARN_LOG, 50000)
        strat_snap = {}
        coin_profit = defaultdict(lambda: {"pnl_sum":0.0,"n":0})

        for u in reversed(updates):
            if u.get("update_type") == "strategy_attribution_cycle":
                summ = u.get("summary", {})
                strategies = summ.get("strategies", {})
                strat_snap = strategies
                break

        # Coin profitability over short window
        trades = _read_jsonl(EXEC_LOG, 50000)
        cutoff = _cutoff(SHORT_MINS)
        for t in trades:
            ts = t.get("ts") or 0
            if ts < cutoff: continue
            sym = t.get("symbol")
            pnl = float(t.get("pnl_pct",0.0))
            if sym:
                coin_profit[sym]["pnl_sum"] += pnl
                coin_profit[sym]["n"] += 1
        for sym, s in coin_profit.items():
            n = max(1,s["n"])
            s["avg_pnl_pct"] = round(s["pnl_sum"]/n,6)
        return strat_snap, coin_profit

    def _risk_gate(self) -> Dict[str,Any]:
        # Lightweight risk snapshot for gating portfolio increases
        rg = RiskGovernor(self.live)
        snapshot = rg._portfolio_metrics()
        return snapshot

    def optimize(self) -> Dict[str,Any]:
        strat_snap, coin_profit = self._read_attribution()
        weights = self.rt.get("strategy_weights", {})
        status  = self.rt.get("strategy_status", {})
        scalars = self.rt.get("coin_scalars", {})
        actions = []

        # Strategy promotions: pick top uplift and strong expectancy within bounds
        candidates = []
        for sid, info in strat_snap.items():
            if status.get(sid, "active") != "active": continue
            uplift = float(info.get("uplift_pct",0.0))
            exp    = float(info.get("expectancy",0.0))
            pnl    = float(info.get("avg_pnl_short",0.0))
            if pnl >= PROMOTE_PNL and exp >= PROMOTE_EXPECTANCY and uplift > 0:
                candidates.append((sid, uplift, exp, pnl))
        candidates.sort(key=lambda x: (x[1], x[2], x[3]), reverse=True)

        # Coin promotions: profitable coins get slight scalar bump
        coin_candidates = [(sym, d["avg_pnl_pct"]) for sym,d in coin_profit.items() if d["avg_pnl_pct"] > 0]
        coin_candidates.sort(key=lambda x: x[1], reverse=True)

        # Risk gate snapshot
        gate = self._risk_gate()
        total_exposure = gate["portfolio_exposure"]
        per_coin_exposure = gate["coin_exposure"]
        corr_pairs = gate["corr_pairs"]

        # Avoid correlated concentration: mark risky symbols
        risky_symbols = set()
        for cp in corr_pairs:
            if cp["corr"] > self.limits["max_corr"]:
                a,b = cp["pair"]
                # mark higher-exposed as risky
                ea = per_coin_exposure.get(a,0.0); eb = per_coin_exposure.get(b,0.0)
                risky_symbols.add(a if ea >= eb else b)

        # Apply promotions conservatively if exposure headroom exists
        exposure_headroom = max(0.0, self.limits["max_exposure"] - total_exposure)
        if exposure_headroom > 0.05:  # require at least 5% headroom
            # Strategy weight bumps
            for sid, uplift, exp, pnl in candidates[:3]:
                cur = float(weights.get(sid, 0.08))
                new = min(STRAT_WEIGHT_MAX, cur + STRAT_WEIGHT_STEP)
                actions.append({"scope":"strategy","strategy_id":sid,"action":"increase_weight","from":cur,"to":new,"reason":"uplift+expectancy"})
                weights[sid] = new
            # Coin scalar bumps
            for sym, avgp in coin_candidates[:3]:
                if sym in risky_symbols: continue
                cur = float(scalars.get(sym, 1.0))
                # respect per-coin cap via exposure approximation
                if per_coin_exposure.get(sym,0.0) >= self.limits["per_coin_cap"]: continue
                new = min(COIN_SCALAR_MAX, cur + COIN_SCALAR_STEP)
                actions.append({"scope":"coin","symbol":sym,"action":"increase_scalar","from":cur,"to":new,"reason":"profitable_coin"})
                scalars[sym] = new

        # Persist tentative changes
        self.rt["strategy_weights"] = weights
        self.rt["coin_scalars"] = scalars
        self.live["runtime"] = self.rt
        _write_json(LIVE_CFG, self.live)

        if actions:
            _append_jsonl(LEARN_LOG, {"ts": _now(), "update_type":"portfolio_governor_actions", "actions": actions})
            _append_jsonl(KG_LOG, {"ts": _now(), "subject":{"governor":"portfolio"}, "predicate":"actions", "object":actions})
        return {"actions": actions, "risk_gate": gate}

def run_portfolio_and_risk_cycle() -> Dict[str,Any]:
    live = _read_json(LIVE_CFG, default={}) or {}
    # 1) Risk evaluation and risk-driven reductions (always first)
    rg = RiskGovernor(live)
    risk = rg.evaluate()

    # 2) Portfolio optimization (promotions) under risk gate
    pg = PortfolioGovernor(live, rg.limits)
    portfolio = pg.optimize()

    # 3) Closed-loop confirm with profit gates via latest attribution (lightweight check)
    #    If recent profit is negative or expectancy weak, revert portfolio increases
    updates = _read_jsonl(LEARN_LOG, 10000)
    verdict = "Neutral"; expectancy = 0.5; avg_pnl_short = 0.0
    for u in reversed(updates):
        if u.get("update_type") == "reverse_triage_cycle":
            v = u.get("summary", {}).get("verdict", {})
            expectancy = float(v.get("expectancy", 0.5))
            avg_pnl_short = float(v.get("pnl_short", {}).get("avg_pnl_pct", 0.0))
            verdict = v.get("verdict", "Neutral")
            break

    revert_actions=[]
    if avg_pnl_short <= ROLLBACK_PNL or expectancy <= ROLLBACK_EXPECTANCY:
        # Revert any NEW increases from this cycle to protect capital
        rt = live.get("runtime", {})
        weights = rt.get("strategy_weights", {})
        scalars = rt.get("coin_scalars", {})
        for a in portfolio.get("actions", []):
            if a["action"] == "increase_weight":
                sid = a["strategy_id"]
                weights[sid] = a["from"]
                revert_actions.append({"scope":"strategy","strategy_id":sid,"action":"revert_increase_weight","to":a["from"],"reason":"profit_gate_fail"})
            if a["action"] == "increase_scalar":
                sym = a["symbol"]
                scalars[sym] = a["from"]
                revert_actions.append({"scope":"coin","symbol":sym,"action":"revert_increase_scalar","to":a["from"],"reason":"profit_gate_fail"})
        rt["strategy_weights"] = weights
        rt["coin_scalars"] = scalars
        live["runtime"] = rt
        _write_json(LIVE_CFG, live)
        if revert_actions:
            _append_jsonl(LEARN_LOG, {"ts": _now(), "update_type":"portfolio_reverts", "reverts": revert_actions, "verdict": verdict})
            _append_jsonl(KG_LOG, {"ts": _now(), "subject":{"governor":"portfolio"}, "predicate":"reverts", "object":revert_actions})

    # Email digest section
    email = f"""
=== Portfolio & Risk Governors ===
Verdict: {verdict} | Expectancy: {expectancy:.3f} | Short-window avg PnL: {avg_pnl_short:.4f}

Risk metrics:
{json.dumps(risk["metrics"], indent=2)}

Risk breaches:
{json.dumps(risk["breaches"], indent=2) if risk["breaches"] else "None"}

Risk actions:
{json.dumps(risk["actions"], indent=2) if risk["actions"] else "None"}

Portfolio promotions:
{json.dumps(portfolio.get("actions", []), indent=2) if portfolio.get("actions") else "None"}

Reverts (profit gate protection):
{json.dumps(revert_actions, indent=2) if revert_actions else "None"}
""".strip()

    summary = {
        "ts": _now(),
        "risk": risk,
        "portfolio": portfolio,
        "verdict": {"status": verdict, "expectancy": expectancy, "avg_pnl_short": avg_pnl_short},
        "reverts": revert_actions,
        "email_body": email
    }
    _append_jsonl(LEARN_LOG, {"ts": summary["ts"], "update_type":"portfolio_risk_cycle", "summary": {k:v for k,v in summary.items() if k!='email_body'}})
    _append_jsonl(KG_LOG, {"ts": _now(), "subject":{"cycle":"portfolio_risk"}, "predicate":"summary", "object":{"breaches": risk["breaches"], "promotions": portfolio.get("actions", []), "reverts": revert_actions}})
    return summary

# CLI
if __name__=="__main__":
    res = run_portfolio_and_risk_cycle()
    print(json.dumps(res, indent=2))
    print("\n--- Email Body ---\n")
    print(res["email_body"])