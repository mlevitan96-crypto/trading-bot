# src/multi_horizon_tuner.py
#
# v5.6 Multi-Horizon Tuner + Review Harness
# Structured learning across timeframes:
# - Daily (hygiene): execution/router micro-policy tweaks
# - 2–3 day rolling (overlay): lead-lag confidence floors, spillover relax, community caps
# - Weekly (strategic): strategy weights, ADX/ATR thresholds, corr sizing bonuses/penalties
#
# Also produces layered digest summaries (1d, 3d, 7d) and can email via GovernanceDigest.

import os, json, time, math, numpy as np
from collections import defaultdict, deque
from datetime import datetime, timedelta

# External modules (already in your codebase)
from src.governance_digest import GovernanceDigest
from src.exploitation_overlays import LeadLagValidator, CommunityRiskManager, PCAOverlay

# Paths and logs
LOGS_DIR = "logs"
DECISION_TRACE_LOG   = f"{LOGS_DIR}/decision_trace.jsonl"
EXECUTED_TRADES_LOG  = f"{LOGS_DIR}/executed_trades.jsonl"
SHADOW_LOG           = f"{LOGS_DIR}/shadow_trades.jsonl"
LEARNING_UPDATES_LOG = f"{LOGS_DIR}/learning_updates.jsonl"
DIGEST_LOG           = f"{LOGS_DIR}/operator_digest.jsonl"
LIVE_CFG_PATH        = "live_config.json"
STATE_PATH           = f"{LOGS_DIR}/multi_horizon_state.json"

os.makedirs(LOGS_DIR, exist_ok=True)

# ---------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------
def _read_jsonl(path, limit=10000):
    rows=[]
    if not os.path.exists(path): return rows
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try: rows.append(json.loads(line))
            except: continue
    return rows[-limit:]

def _write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f: json.dump(obj, f, indent=2)
    os.replace(tmp, path)

def _read_json(path, default=None):
    if not os.path.exists(path): return default
    try:
        with open(path, "r") as f: return json.load(f)
    except:
        return default

def _read_cfg():
    if os.path.exists(LIVE_CFG_PATH):
        try:
            with open(LIVE_CFG_PATH, "r") as f: return json.load(f)
        except:
            pass
    return {}

def _write_cfg(cfg):
    _write_json(LIVE_CFG_PATH, cfg)

# ---------------------------------------------------------------------
# Rolling window utilities
# ---------------------------------------------------------------------
def _within_days(ts, days):
    try:
        return (time.time() - int(ts)) <= days * 86400
    except:
        return False

def _rolling_filter(rows, days):
    return [r for r in rows if _within_days(r.get("ts") or r.get("timestamp") or 0, days)]

def _agg_metrics_trades(trades):
    # Aggregate per (asset, strategy, regime)
    buckets = defaultdict(lambda: {"n":0, "wins":0, "gross_pnl":0.0, "fees":0.0})
    for t in trades:
        key = (t.get("asset") or t.get("symbol"), t.get("strategy"), t.get("regime"))
        pnl = float(t.get("net_pnl_usd", 0.0))
        fees = float(t.get("fees_usd", 0.0))
        buckets[key]["n"] += 1
        buckets[key]["gross_pnl"] += pnl
        buckets[key]["fees"] += fees
        if pnl > 0: buckets[key]["wins"] += 1
    out={}
    for k, b in buckets.items():
        wr = b["wins"] / max(1, b["n"])
        ev = b["gross_pnl"] / max(1, b["n"])
        pf = (b["gross_pnl"] - b["fees"]) / max(1e-6, abs(b["gross_pnl"]) + b["fees"])
        out[k] = {"wr": wr, "pf": pf, "ev": ev, "n": b["n"]}
    return out

def _agg_confidence_leadlag(digest_rows):
    # Extract latest lead-lag confidences from governance_digest snapshots
    latest = {}
    for d in digest_rows:
        comp = d.get("components",{})
        ll = comp.get("lead_lag",{})
        for pair, rec in ll.items():
            latest[pair] = {"confidence": rec.get("confidence",0.0),
                            "peak_lag": rec.get("peak_lag"),
                            "false_followers": rec.get("false_followers",0)}
    return latest

def _agg_pca_variance(digest_rows):
    # Extract latest PCA variance
    last = None
    for d in digest_rows:
        pca = d.get("components",{}).get("pca",{})
        var = pca.get("variance")
        if var is not None:
            last = float(var)
    return last if last is not None else 0.0

def _shadow_value(shadows):
    # Net value of vetoes by reason: avoided - missed
    value = defaultdict(lambda: {"avoided":0.0, "missed":0.0, "count":0})
    for r in shadows:
        reason = r.get("exec",{}).get("shadow_reason","unknown")
        ev_passed = r.get("inputs",{}).get("ev_passed")
        notional = float(r.get("exec",{}).get("notional_usd", 0.0))
        if ev_passed is False: value[reason]["avoided"] += notional
        elif ev_passed is True: value[reason]["missed"] += notional
        value[reason]["count"] += 1
    for k,v in value.items():
        v["net"] = round(v["avoided"] - v["missed"],2)
    return value

# ---------------------------------------------------------------------
# Multi-horizon tuner
# ---------------------------------------------------------------------
class MultiHorizonTuner:
    def __init__(self, llv: LeadLagValidator, crm: CommunityRiskManager, pca: PCAOverlay,
                 smtp_user=None, smtp_pass=None, email_to=None, smtp_host="smtp.gmail.com", smtp_port=587):
        self.llv = llv
        self.crm = crm
        self.pca = pca
        self.smtp_user = smtp_user
        self.smtp_pass = smtp_pass
        self.email_to = email_to
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.state = _read_json(STATE_PATH, default={
            "last_daily_ts": 0,
            "last_medium_ts": 0,
            "last_weekly_ts": 0
        })

    def _save_state(self):
        _write_json(STATE_PATH, self.state)

    def _now(self): return int(time.time())

    def _days_since(self, ts):
        if not ts: return 999
        return (self._now() - ts) / 86400.0

    def compute_windows(self):
        # Read logs
        trades = _read_jsonl(EXECUTED_TRADES_LOG, 10000)
        shadows = _read_jsonl(SHADOW_LOG, 10000)
        digests = _read_jsonl(DIGEST_LOG, 10000)
        traces = _read_jsonl(DECISION_TRACE_LOG, 10000)

        # Slice windows
        t1d = _agg_metrics_trades(_rolling_filter(trades, 1))
        t3d = _agg_metrics_trades(_rolling_filter(trades, 3))
        t7d = _agg_metrics_trades(_rolling_filter(trades, 7))

        shadow_1d = _shadow_value(_rolling_filter(shadows, 1))
        shadow_3d = _shadow_value(_rolling_filter(shadows, 3))
        shadow_7d = _shadow_value(_rolling_filter(shadows, 7))

        ll_1d = _agg_confidence_leadlag(_rolling_filter(digests, 1))
        ll_3d = _agg_confidence_leadlag(_rolling_filter(digests, 3))
        ll_7d = _agg_confidence_leadlag(_rolling_filter(digests, 7))

        pca_var_1d = _agg_pca_variance(_rolling_filter(digests, 1))
        pca_var_3d = _agg_pca_variance(_rolling_filter(digests, 3))
        pca_var_7d = _agg_pca_variance(_rolling_filter(digests, 7))

        return {
            "trades": {"1d": t1d, "3d": t3d, "7d": t7d},
            "shadows": {"1d": shadow_1d, "3d": shadow_3d, "7d": shadow_7d},
            "lead_lag": {"1d": ll_1d, "3d": ll_3d, "7d": ll_7d},
            "pca_var": {"1d": pca_var_1d, "3d": pca_var_3d, "7d": pca_var_7d}
        }

    # ---------------- Daily hygiene (execution/router only) ----------------
    def apply_daily(self, windows):
        if self._days_since(self.state["last_daily_ts"]) < 0.9:
            return None  # already applied recently
        cfg = _read_cfg()
        if not cfg: cfg = {}

        # Hygiene: adjust router exploration based on stability of costs
        # Use 1d metrics: if EV stable and PF improving, reduce exploration
        # (Assumes router micro-policy uses cfg["router_mode"] and internal stats;
        # we set an exploration scalar here if you choose to consult it.)
        router_explore = float(cfg.get("router_explore", 0.2))
        t1d = windows["trades"]["1d"]
        # compute average EV & PF
        evs = [m["ev"] for m in t1d.values()]
        pfs = [m["pf"] for m in t1d.values()]
        avg_ev = sum(evs)/len(evs) if evs else 0.0
        avg_pf = sum(pfs)/len(pfs) if pfs else 1.0
        if avg_pf > 1.4 and abs(avg_ev) < 0.2:
            router_explore = max(0.05, router_explore - 0.02)
        elif avg_pf < 1.0:
            router_explore = min(0.25, router_explore + 0.02)
        cfg["router_explore"] = round(router_explore, 3)

        # Optional: adjust fee/slippage estimates slightly based on 1d adverse selection signals
        # Keep small, hygiene-level tweaks
        cfg["last_daily_ts"] = self._now()
        _write_cfg(cfg)
        self.state["last_daily_ts"] = self._now()
        self._save_state()
        return {"router_explore": cfg["router_explore"]}

    # ------------- Medium horizon (2–3 day overlay tuning) ---------------
    def apply_medium(self, windows):
        if self._days_since(self.state["last_medium_ts"]) < 2.0:
            return None  # only apply every ~2-3 days
        cfg = _read_cfg()
        if not cfg: cfg = {}

        # Lead-lag: confidence floor tuner based on 3d persistence and false-followers
        ll3 = windows["lead_lag"]["3d"]
        avg_conf = 0.0; n_conf = 0
        false_rate = 0.0; n_false = 0
        for pair, rec in ll3.items():
            c = float(rec.get("confidence",0.0)); avg_conf += c; n_conf += 1
            ff = int(rec.get("false_followers",0)); false_rate += ff; n_false += 1
        avg_conf = (avg_conf / max(1, n_conf)) if n_conf else 0.0
        avg_false = (false_rate / max(1, n_false)) if n_false else 0.0

        lead_cfg = cfg.get("lead_lag", {"enable": True, "confidence_floor": 0.6})
        floor = float(lead_cfg.get("confidence_floor",0.6))
        # Raise floor if false followers moderate/high; lower if high confidence persists
        if avg_false >= 1:
            floor = min(0.85, floor + 0.05)
        elif avg_conf >= 0.75:
            floor = max(0.55, floor - 0.03)
        lead_cfg["confidence_floor"] = round(floor, 2)
        cfg["lead_lag"] = lead_cfg

        # Spillover: relax factor tuning on 3d uplift (use shadow veto net as proxy if available)
        sh3 = windows["shadows"]["3d"]
        # If gate veto ("gate") has high missed value, consider modest relax; if avoided dominates, tighten
        gate_net = sh3.get("gate", {}).get("net", 0.0)
        spill = cfg.get("spillover", {"enable": True, "follower_hurdle_relax": 0.85})
        relax = float(spill.get("follower_hurdle_relax",0.85))
        if gate_net > 100.0:
            relax = min(0.92, relax + 0.02)
        elif gate_net < -100.0:
            relax = max(0.80, relax - 0.02)
        spill["follower_hurdle_relax"] = round(relax, 2)
        cfg["spillover"] = spill

        # Community caps: calibrate max per community based on 3d breaches (using digest communities count if needed)
        # Keep conservative: prefer fewer positions when PCA variance elevated
        pca3 = float(windows["pca_var"]["3d"] or 0.0)
        comm_cfg = cfg.get("community_caps", {"enable": True, "max_per_community": 4})
        max_comm = int(comm_cfg.get("max_per_community",4))
        if pca3 >= 0.55:
            max_comm = max(2, max_comm - 1)
        elif pca3 <= 0.35:
            max_comm = min(5, max_comm + 1)
        comm_cfg["max_per_community"] = max_comm
        cfg["community_caps"] = comm_cfg

        cfg["last_medium_ts"] = self._now()
        _write_cfg(cfg)
        self.state["last_medium_ts"] = self._now()
        self._save_state()
        return {"lead_lag.confidence_floor": lead_cfg["confidence_floor"],
                "spillover.follower_hurdle_relax": spill["follower_hurdle_relax"],
                "community_caps.max_per_community": comm_cfg["max_per_community"]}

    # ------------------- Weekly (strategic calibration) -------------------
    def apply_weekly(self, windows):
        if self._days_since(self.state["last_weekly_ts"]) < 6.0:
            return None  # ~weekly cadence
        cfg = _read_cfg()
        if not cfg: cfg = {}

        # Strategy weights: based on 7d PF/EV, per regime/strategy
        t7 = windows["trades"]["7d"]
        by_regime = defaultdict(lambda: defaultdict(list))
        for (asset, strat, regime), m in t7.items():
            by_regime[regime][strat].append(m)
        new_weights = {"trend":{}, "chop":{}}
        for regime, strat_dict in by_regime.items():
            for strat, arr in strat_dict.items():
                avg_pf = sum(x["pf"] for x in arr)/len(arr)
                avg_ev = sum(x["ev"] for x in arr)/len(arr)
                score = max(0.01, 0.6*avg_pf + 0.4*max(-0.5, avg_ev))
                new_weights[regime][strat] = round(0.2 + 1.3*(score / max(score,1e-6)), 2)

        cfg["strategy_weights"] = new_weights

        # Thresholds: ADX min for trend strategies based on 7d PF
        trend_perf = [m for (a,s,r),m in t7.items() if s in ("Trend-Conservative","Breakout-Aggressive")]
        current_adx = int(cfg.get("min_adx_for_trend",25))
        if trend_perf:
            avg_pf = sum(x["pf"] for x in trend_perf)/len(trend_perf)
            if avg_pf < 1.0: current_adx = min(40, current_adx+3)
            elif avg_pf > 1.6: current_adx = max(20, current_adx-3)
        cfg["min_adx_for_trend"] = current_adx

        # Corr sizing: adjust independence bonus / cluster penalty based on 7d PF and PCA dominance
        pca7 = float(windows["pca_var"]["7d"] or 0.0)
        sizing = cfg.get("sizing", {"independence_bonus": 0.25, "cluster_penalty": 0.30})
        indep = float(sizing.get("independence_bonus",0.25))
        clpen = float(sizing.get("cluster_penalty",0.30))
        if pca7 >= 0.55:
            # reduce independence bonus and increase cluster penalty to discourage concentration
            indep = max(0.10, indep - 0.05)
            clpen = min(0.45, clpen + 0.05)
        elif pca7 <= 0.35:
            indep = min(0.35, indep + 0.03)
            clpen = max(0.25, clpen - 0.03)
        sizing["independence_bonus"] = round(indep,2)
        sizing["cluster_penalty"] = round(clpen,2)
        cfg["sizing"] = sizing

        cfg["last_weekly_ts"] = self._now()
        _write_cfg(cfg)
        self.state["last_weekly_ts"] = self._now()
        self._save_state()
        return {"strategy_weights": new_weights,
                "min_adx_for_trend": current_adx,
                "sizing.independence_bonus": sizing["independence_bonus"],
                "sizing.cluster_penalty": sizing["cluster_penalty"]}

    # ----------------- Layered digest summary (1d/3d/7d) -----------------
    def layered_digest(self, windows):
        # Build a compact layered summary
        def _fmt_metrics(mdict):
            out=[]
            # Show top 5 by count
            pairs = sorted(mdict.items(), key=lambda kv: kv[1]["n"], reverse=True)[:5]
            for (asset,strat,reg), m in pairs:
                out.append(f"{asset}/{strat}/{reg}: WR={m['wr']:.2f}, PF={m['pf']:.2f}, EV={m['ev']:.2f}, n={m['n']}")
            return out or ["(no data)"]

        summary = {
            "ts": int(time.time()),
            "layered": {
                "1d": {
                    "trades": _fmt_metrics(windows["trades"]["1d"]),
                    "shadow_top": sorted(((k,v["net"]) for k,v in windows["shadows"]["1d"].items()), key=lambda kv: kv[1], reverse=True)[:5],
                    "pca_var": windows["pca_var"]["1d"]
                },
                "3d": {
                    "trades": _fmt_metrics(windows["trades"]["3d"]),
                    "shadow_top": sorted(((k,v["net"]) for k,v in windows["shadows"]["3d"].items()), key=lambda kv: kv[1], reverse=True)[:5],
                    "pca_var": windows["pca_var"]["3d"]
                },
                "7d": {
                    "trades": _fmt_metrics(windows["trades"]["7d"]),
                    "shadow_top": sorted(((k,v["net"]) for k,v in windows["shadows"]["7d"].items()), key=lambda kv: kv[1], reverse=True)[:5],
                    "pca_var": windows["pca_var"]["7d"]
                }
            }
        }
        # Log a compact review line
        with open(LEARNING_UPDATES_LOG, "a") as f:
            f.write(json.dumps({"ts": summary["ts"], "multi_horizon_summary": summary["layered"]}) + "\n")
        return summary

    # ----------------- Orchestrator: run all cadences -----------------
    def run(self, positions_snapshot=None, returns_matrix=None):
        windows = self.compute_windows()
        daily_res   = self.apply_daily(windows)
        medium_res  = self.apply_medium(windows)
        weekly_res  = self.apply_weekly(windows)
        summary     = self.layered_digest(windows)

        # Email disabled - was triggering on every horizon tuner run
        # Now only sends via nightly_email_report_v2 during overnight review
        # Previously: gd.snapshot() would email correlation digest every time

        return {"daily": daily_res, "medium": medium_res, "weekly": weekly_res, "summary": summary}


# ---------------------------------------------------------------------
# Example usage (run manually or from your nightly pipeline)
# ---------------------------------------------------------------------
if __name__ == "__main__":
    # Initialize infrastructure components
    llv = LeadLagValidator()
    crm = CommunityRiskManager()
    pca = PCAOverlay()

    # Example: seed some validator state
    llv.update("BTCUSDT", "ETHUSDT", {1:0.72, 4:0.65})
    llv.update("BTCUSDT", "SOLUSDT", {4:0.58, 12:0.40})

    # Fake portfolio snapshot and returns matrix for PCA
    positions = [{"symbol": "BTCUSDT", "side": "long", "size_usd": 200000},
                 {"symbol": "ETHUSDT", "side": "long", "size_usd": 150000}]
    returns_matrix = np.random.randn(100, 4)

    tuner = MultiHorizonTuner(
        llv, crm, pca,
        smtp_user=os.getenv("SMTP_USER"),
        smtp_pass=os.getenv("SMTP_PASS"),
        email_to=os.getenv("REPORT_TO_EMAIL"),
        smtp_host=os.getenv("SMTP_HOST","smtp.gmail.com"),
        smtp_port=int(os.getenv("SMTP_PORT","587"))
    )
    res = tuner.run(positions_snapshot=positions, returns_matrix=returns_matrix)
    print("Multi-horizon update results:", json.dumps(res, indent=2))
