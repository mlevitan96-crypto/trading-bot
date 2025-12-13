# File: src/elite_system.py
# Purpose: Unified elite module with 7 institutional-grade upgrades for adaptive, self-optimizing trading bots.
# Modules: Auto-tuner, Attribution, Signal Decay, Protective Audit, Execution Health, Risk Allocator, Shadow Mode Runner

import json
from pathlib import Path
from collections import defaultdict, deque
from datetime import datetime
from statistics import mean, pstdev

CONFIG_DIR = Path("configs")
LOGS_DIR = Path("logs")
CONFIG_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

def utc_now() -> str:
    return datetime.utcnow().isoformat()

def load_json(path: Path, fallback=None):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return fallback

def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


class AutoTuner:
    """Adapts ROI and ensemble thresholds per regime using missed opportunity replay and live metrics."""
    CONFIG = CONFIG_DIR / "thresholds.json"
    REPLAY = LOGS_DIR / "missed_replay_report.json"
    METRICS = LOGS_DIR / "live_metrics_summary.json"

    DEFAULTS = {
        "Stable": {"roi": 0.003, "ensemble": 0.60},
        "Volatile": {"roi": 0.004, "ensemble": 0.70},
        "Choppy": {"roi": 0.002, "ensemble": 0.50}
    }
    BOUNDS = {"roi": (0.0005, 0.0100), "ensemble": (0.20, 0.85)}

    def _clamp(self, val: float, key: str) -> float:
        lo, hi = self.BOUNDS[key]
        return max(lo, min(hi, val))

    def propose(self):
        cur = load_json(self.CONFIG, self.DEFAULTS)
        replay = load_json(self.REPLAY, {"false_negatives": 0, "missed_pnl": 0.0})
        live = load_json(self.METRICS, {"Stable": {}, "Volatile": {}, "Choppy": {}})

        out = {}
        for regime, base in cur.items():
            dd = live.get(regime, {}).get("max_drawdown", 0.0)
            wr = live.get(regime, {}).get("winrate", 0.0)

            relax = 0.10 if replay.get("missed_pnl", 0.0) > 0.0 and dd < 0.05 else 0.0
            tighten = 0.0
            if dd > 0.08:
                tighten += 0.10
            if wr < 0.45 and wr > 0:
                tighten += 0.05

            delta = relax - tighten
            new_roi = self._clamp(base["roi"] * (1 - delta), "roi")
            new_ensemble = self._clamp(base["ensemble"] * (1 - delta), "ensemble")

            out[regime] = {
                "roi": round(new_roi, 6),
                "ensemble": round(new_ensemble, 3),
                "notes": {"relax": relax, "tighten": tighten, "drawdown": dd, "winrate": wr, "missed_pnl": replay.get("missed_pnl", 0.0)}
            }
        return out

    def apply(self, dry_run: bool = True):
        updates = self.propose()
        if not dry_run:
            save_json(self.CONFIG, {k: {"roi": v["roi"], "ensemble": v["ensemble"]} for k, v in updates.items()})
        return updates


class Attribution:
    """Logs performance by symbol, strategy, and regime to drive capital reallocation and pruning."""
    OUT = LOGS_DIR / "attribution_summary.json"

    def __init__(self):
        self.store = defaultdict(lambda: {
            "trades": 0, "wins": 0, "losses": 0,
            "roi_samples": [], "gross_pnl": 0.0, "net_pnl": 0.0
        })

    def log(self, symbol: str, strategy: str, regime: str, roi: float, fees: float = 0.0):
        key = f"{symbol}|{strategy}|{regime}"
        s = self.store[key]
        s["trades"] += 1
        s["roi_samples"].append(roi)
        if roi >= 0:
            s["wins"] += 1
        else:
            s["losses"] += 1
        s["gross_pnl"] += roi
        s["net_pnl"] += (roi - fees)

    def persist(self):
        summary = []
        for key, s in self.store.items():
            symbol, strategy, regime = key.split("|")
            trades = s["trades"]
            winrate = round(s["wins"] / trades, 3) if trades > 0 else 0.0
            avg_roi = round(mean(s["roi_samples"]), 6) if s["roi_samples"] else 0.0
            summary.append({
                "symbol": symbol, "strategy": strategy, "regime": regime,
                "trades": trades, "winrate": winrate, "avg_roi": avg_roi,
                "gross_pnl": round(s["gross_pnl"], 6), "net_pnl": round(s["net_pnl"], 6)
            })
        payload = {"timestamp": utc_now(), "summary": sorted(summary, key=lambda x: (x["regime"], x["strategy"], x["symbol"]))}
        save_json(self.OUT, payload)


class FuturesAttribution:
    """
    Tracks futures performance separately from spot with leverage, funding fees, and margin metrics.
    Enables independent analysis of leveraged trading performance.
    """
    OUT = LOGS_DIR / "futures_attribution_summary.json"

    def __init__(self):
        self.store = defaultdict(lambda: {
            "trades": 0, "wins": 0, "losses": 0,
            "roi_samples": [], "leverage_samples": [],
            "gross_pnl": 0.0, "net_pnl": 0.0,
            "trading_fees": 0.0, "funding_fees": 0.0,
            "total_margin_used": 0.0, "total_notional": 0.0
        })

    def log(self, symbol: str, strategy: str, regime: str, roi: float, leverage: float, 
            trading_fees: float = 0.0, funding_fees: float = 0.0, margin: float = 0.0):
        """
        Log a futures trade with leverage-specific metrics.
        
        Args:
            symbol: Trading symbol
            strategy: Strategy name (may include leverage like "Trend-5x")
            regime: Market regime
            roi: Net ROI on margin (after leverage and ALL fees - trading + funding)
            leverage: Leverage multiplier used
            trading_fees: Trading fees as ROI impact (for breakout tracking only)
            funding_fees: Funding fees as ROI impact (for breakout tracking only)
            margin: Margin collateral used
        
        CRITICAL: roi parameter is ALREADY net of all fees. Do not subtract fees again.
        """
        key = f"{symbol}|{strategy}|{regime}"
        s = self.store[key]
        s["trades"] += 1
        s["roi_samples"].append(roi)
        s["leverage_samples"].append(leverage)
        
        if roi >= 0:
            s["wins"] += 1
        else:
            s["losses"] += 1
        
        # Note: roi is already net of fees, so gross_pnl and net_pnl are the same
        # We keep both fields for backward compatibility with dashboard expectations
        s["gross_pnl"] += roi  # Same as net_pnl (roi is already net)
        s["net_pnl"] += roi     # Already net of all fees
        s["trading_fees"] += trading_fees  # Track fee breakdown separately
        s["funding_fees"] += funding_fees   # Track fee breakdown separately
        s["total_margin_used"] += margin
        s["total_notional"] += (margin * leverage)

    def persist(self):
        summary = []
        for key, s in self.store.items():
            symbol, strategy, regime = key.split("|")
            trades = s["trades"]
            winrate = round(s["wins"] / trades, 3) if trades > 0 else 0.0
            avg_roi = round(mean(s["roi_samples"]), 6) if s["roi_samples"] else 0.0
            avg_leverage = round(mean(s["leverage_samples"]), 2) if s["leverage_samples"] else 0.0
            
            summary.append({
                "symbol": symbol,
                "strategy": strategy,
                "regime": regime,
                "trades": trades,
                "winrate": winrate,
                "avg_roi": avg_roi,
                "avg_leverage": avg_leverage,
                "gross_pnl": round(s["gross_pnl"], 6),
                "net_pnl": round(s["net_pnl"], 6),
                "trading_fees": round(s["trading_fees"], 6),
                "funding_fees": round(s["funding_fees"], 6),
                "total_margin": round(s["total_margin_used"], 2),
                "total_notional": round(s["total_notional"], 2)
            })
        
        payload = {
            "timestamp": utc_now(),
            "summary": sorted(summary, key=lambda x: (x["regime"], x["strategy"], x["symbol"]))
        }
        save_json(self.OUT, payload)


class SignalDecayTracker:
    """Tracks signal strength over a window to find optimal entry timing and avoid stale signals."""
    OUT = LOGS_DIR / "signal_decay.json"

    def __init__(self, window: int = 10):
        self.window = window
        self.tracks = {}

    def update(self, symbol: str, strategy: str, strength: float):
        key = f"{symbol}|{strategy}"
        if key not in self.tracks:
            self.tracks[key] = deque(maxlen=self.window)
        self.tracks[key].append({"t": utc_now(), "s": strength})

    def persist(self):
        tracks_out = {}
        for key, q in self.tracks.items():
            strengths = [p["s"] for p in q]
            if not strengths:
                continue
            tracks_out[key] = {
                "initial": strengths[0],
                "latest": strengths[-1],
                "mean": round(mean(strengths), 6),
                "std": round(pstdev(strengths) if len(strengths) > 1 else 0.0, 6),
                "decay": round(strengths[-1] - strengths[0], 6)
            }
        save_json(self.OUT, {"timestamp": utc_now(), "tracks": tracks_out})


class ProtectiveAudit:
    """Quantifies cost/benefit of risk-off logic by comparing blocked vs hypothetical outcomes."""
    OUT = LOGS_DIR / "protective_mode_audit.json"

    def __init__(self):
        self.records = []

    def log(self, symbol: str, strategy: str, regime: str, reason: str, roi: float = None):
        self.records.append({
            "symbol": symbol, "strategy": strategy, "regime": regime,
            "reason": reason, "roi": roi, "timestamp": utc_now()
        })

    def persist(self):
        total = len(self.records)
        missed_pnl = sum(r["roi"] for r in self.records if r.get("roi") is not None and r["roi"] > 0)
        avoided_dd = sum(-r["roi"] for r in self.records if r.get("roi") is not None and r["roi"] < 0)
        by_reason = defaultdict(int)
        for r in self.records:
            by_reason[r["reason"]] += 1
        payload = {
            "timestamp": utc_now(),
            "total_blocks": total,
            "blocked_reasons": dict(by_reason),
            "missed_pnl_estimate": round(missed_pnl, 6),
            "avoided_drawdown_estimate": round(avoided_dd, 6)
        }
        save_json(self.OUT, payload)


class ExecutionHealth:
    """Detects slippage anomalies, partial fills, and tick misalignment."""
    OUT = LOGS_DIR / "execution_health.json"

    def __init__(self, warn: float = 0.004, crit: float = 0.010):
        self.events = []
        self.warn = warn
        self.crit = crit

    def log(self, symbol: str, intended: float, filled: float, qty: float, tick: float = None, partial: bool = False):
        slip = (filled - intended) / max(intended, 1e-9)
        issues = []
        if abs(slip) >= self.crit:
            issues.append("slippage_critical")
        elif abs(slip) >= self.warn:
            issues.append("slippage_warning")
        if tick is not None:
            floored = (filled // tick) * tick
            if abs(floored - filled) > 1e-12:
                issues.append("tick_misalignment")
        if partial:
            issues.append("partial_fill")
        self.events.append({
            "timestamp": utc_now(),
            "symbol": symbol,
            "intended_price": round(intended, 8),
            "filled_price": round(filled, 8),
            "qty": qty,
            "slippage": round(slip, 8),
            "issues": issues
        })

    def persist(self):
        avg_slip = mean([e["slippage"] for e in self.events]) if self.events else 0.0
        counts = defaultdict(int)
        for e in self.events:
            for i in e["issues"]:
                counts[i] += 1
        payload = {
            "timestamp": utc_now(),
            "avg_slippage": round(avg_slip, 8),
            "issue_counts": dict(counts),
            "events": self.events[-100:]
        }
        save_json(self.OUT, payload)


class RiskAllocator:
    """Assigns budgets by symbol/strategy based on volatility, Sharpe-like metrics, and guardrails."""
    OUT = CONFIG_DIR / "risk_budgets.json"

    def __init__(self, base: float = 1000.0, max_mult: float = 3.0):
        self.base = base
        self.max_mult = max_mult

    def propose(self, attrib_summary: list, vol_snapshot: dict):
        budgets = {}
        for row in attrib_summary:
            key = f"{row['symbol']}|{row['strategy']}"
            wr = max(0.0, row.get("winrate", 0.0))
            roi = row.get("avg_roi", 0.0)
            pnl = row.get("net_pnl", 0.0)
            trades = max(1, row.get("trades", 1))

            performance_score = max(0.0, wr - 0.5) + max(0.0, roi) + max(0.0, pnl / trades)
            vol = vol_snapshot.get(row["symbol"], {}).get("vol", 0.5)
            vol_scale = max(0.3, 1.0 - vol)

            multiplier = min(self.max_mult, 1.0 + performance_score)
            budgets[key] = round(self.base * multiplier * vol_scale, 2)

        return {"timestamp": utc_now(), "budgets": budgets}

    def persist(self, proposal: dict):
        save_json(self.OUT, proposal)


class ShadowRunner:
    """Experimental sandbox for testing new configurations non-invasively."""
    OUT = LOGS_DIR / "shadow_mode_results.json"

    def __init__(self):
        self.experiments = []

    def run(self, name: str, config: dict, metrics: dict):
        """
        Run a shadow experiment with experimental config and observed metrics.
        
        Args:
            name: Experiment identifier (e.g., "EnsembleWeights_v2")
            config: Experimental parameters (e.g., {"sentiment": 0.4, "momentum": 0.35})
            metrics: Observed results (e.g., {"winrate": 0.51, "avg_roi": 0.0031})
        """
        self.experiments.append({
            "timestamp": utc_now(),
            "name": name,
            "config": config,
            "metrics": metrics
        })

    def persist(self):
        save_json(self.OUT, {"timestamp": utc_now(), "experiments": self.experiments})


def integration_example():
    """Example integration showing all 7 modules."""
    # 1) Auto-tune thresholds
    tuner = AutoTuner()
    proposed = tuner.apply(dry_run=True)
    save_json(LOGS_DIR / "auto_tuner_proposed.json", proposed)

    # 2) Attribution logging
    attribution = Attribution()
    attribution.log("TRXUSDT", "Breakout-Aggressive", "Stable", roi=0.0042, fees=0.0001)
    attribution.log("AVAXUSDT", "Trend-Conservative", "Stable", roi=-0.0015, fees=0.0001)
    attribution.persist()

    # 3) Signal decay tracking
    decay = SignalDecayTracker(window=12)
    for strength in [0.62, 0.60, 0.58, 0.63, 0.59]:
        decay.update("ETHUSDT", "Sentiment-Fusion", strength)
    decay.persist()

    # 4) Protective mode audit
    p_audit = ProtectiveAudit()
    p_audit.log("SOLUSDT", "Breakout-Aggressive", "Stable", reason="protective_mode", roi=0.003)
    p_audit.log("DOTUSDT", "Trend-Conservative", "Stable", reason="protective_mode", roi=-0.002)
    p_audit.persist()

    # 5) Execution health monitoring
    exec_health = ExecutionHealth(warn=0.004, crit=0.010)
    exec_health.log("BTCUSDT", intended=68000.0, filled=68010.0, qty=0.01, tick=0.10, partial=False)
    exec_health.log("TRXUSDT", intended=0.1198, filled=0.1204, qty=1000, tick=0.0001, partial=True)
    exec_health.persist()

    # 6) Risk budget allocation
    attrib_summary = load_json(Attribution.OUT, {"summary": []}).get("summary", [])
    vol_snapshot = {"TRXUSDT": {"vol": 0.35}, "AVAXUSDT": {"vol": 0.55}, "ETHUSDT": {"vol": 0.40}}
    allocator = RiskAllocator(base=1500.0, max_mult=2.5)
    proposal = allocator.propose(attrib_summary, vol_snapshot)
    allocator.persist(proposal)

    # 7) Shadow mode experiments
    shadow = ShadowRunner()
    shadow.run("EnsembleWeights_v2", config={"sentiment": 0.4, "momentum": 0.35, "volume": 0.25},
               metrics={"winrate": 0.51, "avg_roi": 0.0031, "drawdown": 0.046})
    shadow.persist()


if __name__ == "__main__":
    integration_example()
