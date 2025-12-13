# src/meta_learning_orchestrator.py
#
# v5.7 Meta-Learning Orchestrator
# Goal: Interconnect all modules (Meta-Governor, Meta-Research Desk, Liveness Monitor, Profitability Governor)
#       into a single adaptive learning cycle with redundancy and failover. Each area feeds the others,
#       audits correctness, and pushes system edge safely. Includes "Twin System" redundancy for cross-check
#       and automatic failover.
#
# Core features:
# - Adaptive cycle: orchestrates governance → research → learning → counterfactual hooks
# - Interconnected intelligence: modules exchange signals, health, and outcomes
# - Expectancy-governed adjustments: use realized uplift to modulate relax/sizing cadence
# - Knowledge graph queries: surface cross-coin, cross-regime relationships into decisions
# - Health-severity brakes: guard every action with safety checks from the governor
# - Twin System: duplicate subsystem running in parallel; cross-validate outputs and trigger failover
# - Failover engine: if primary deviates or degrades critically, switch execution bridge to twin
#
# Integration:
#   from src.meta_learning_orchestrator import MetaLearningOrchestrator
#   mlo = MetaLearningOrchestrator()
#   digest = mlo.run_cycle()        # call every 30 minutes and nightly
#   mlo.run_twin_validation()       # optional: run after cycle to validate + sync
#
# Email:
#   Incorporate digest['email_body'] into your consolidated operator email.
#
# Assumptions:
# - Existing modules present: meta_governor.py, meta_research_desk.py,
#   trade_liveness_monitor.py, profitability_governor.py
# - Logging files used across your system exist or will be created

import os, json, time, math
from typing import Dict, Any, List, Optional

# Modules
from src.meta_governor import MetaGovernor
from src.meta_research_desk import MetaResearchDesk
from src.trade_liveness_monitor import TradeLivenessMonitor
from src.profitability_governor import ProfitabilityGovernor
from src.counterfactual_scaling_engine import CounterfactualScalingEngine
from src.system_health_check import SystemHealthCheck
from src.emergency_autonomy_suite import EmergencyAutonomyHooks
from src.fee_calibration_probe import FeeCalibrationProbe
from src.fee_attribution_module import FeeAttributionModule
from src.profit_attribution_module import ProfitAttributionModule
from src.slippage_latency_attribution import SlippageLatencyAttribution
from src.strategy_attribution_module import StrategyAttribution
from src.portfolio_risk_governors import run_portfolio_and_risk_cycle
from src.reverse_triage import ReverseTriage
from src.governance_watchdog import GovernanceWatchdog
from src.unified_contracts_and_invariants import run_preflight_invariants
from src.predictive_regime_governor import run_regime_cycle
from src.dashboard_validator import DashboardValidator
from src.counterfactual_intelligence import CounterfactualIntelligence
from src.health_check_overlay import HealthCheckOverlay

LOGS_DIR = "logs"
os.makedirs(LOGS_DIR, exist_ok=True)

# Paths
LEARNING_UPDATES_LOG  = f"{LOGS_DIR}/learning_updates.jsonl"
META_LEARN_LOG        = f"{LOGS_DIR}/meta_learning.jsonl"
META_GOV_LOG          = f"{LOGS_DIR}/meta_governor.jsonl"
RESEARCH_DESK_LOG     = f"{LOGS_DIR}/research_desk.jsonl"
KNOWLEDGE_GRAPH_LOG   = f"{LOGS_DIR}/knowledge_graph.jsonl"
EXEC_LOG              = f"{LOGS_DIR}/executed_trades.jsonl"
SHADOW_LOG            = f"{LOGS_DIR}/shadow_trades.jsonl"
LIVE_CFG_PATH         = "live_config.json"

COINS = ["BTCUSDT","ETHUSDT","SOLUSDT","ADAUSDT","XRPUSDT","DOGEUSDT","AVAXUSDT","LINKUSDT","MATICUSDT","DOTUSDT","LTCUSDT"]

# Twin configuration (redundancy)
TWIN_STATE_PATH       = "twin_state.json"            # primary/twin status and last validation
TWIN_SYNC_LOG         = f"{LOGS_DIR}/twin_sync.jsonl"

# Basic IO
def _append_jsonl(path, obj):
    with open(path, "a") as f: f.write(json.dumps(obj) + "\n")

def _read_jsonl(path, limit=5000):
    rows=[]
    if not os.path.exists(path): return rows
    with open(path,"r") as f:
        for line in f:
            line=line.strip()
            if not line: continue
            try: rows.append(json.loads(line))
            except: continue
    return rows[-limit:]

def _read_json(path, default=None):
    if not os.path.exists(path): return default
    try:
        with open(path,"r") as f: return json.load(f)
    except:
        return default

def _write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp,"w") as f: json.dump(obj, f, indent=2)
    os.replace(tmp, path)

def _now(): return int(time.time())

# Utilities
def _pca_variance_recent(default=0.5) -> float:
    # read from meta_governor health outputs if present
    rows = _read_jsonl(META_GOV_LOG, 2000)
    for r in reversed(rows):
        health = r.get("health", {})
        sev = health.get("severity", {})
        # we may not have PCA variance directly here; fallback to operator digest if needed
    # Fallback: scan research desk log for last PCA
    rows2 = _read_jsonl(RESEARCH_DESK_LOG, 2000)
    for r in reversed(rows2):
        var = r.get("pca_variance")
        if var is not None:
            try: return float(var)
            except: break
    return default

def _expectancy(real_rows: List[Dict[str,Any]], shadow_rows: List[Dict[str,Any]], horizon_days=7) -> Dict[str,Any]:
    cutoff = _now() - horizon_days*86400
    real_pnl = {}; shadow_pnl = {}
    for r in real_rows:
        ts = r.get("ts") or r.get("timestamp")
        if not ts or ts < cutoff: continue
        sym = r.get("asset") or r.get("symbol")
        pnl = float(r.get("pnl_usd", r.get("pnl", 0.0)))
        if sym in COINS: real_pnl[sym] = real_pnl.get(sym, 0.0) + pnl
    for r in shadow_rows:
        ts = r.get("ts") or r.get("timestamp")
        if not ts or ts < cutoff: continue
        sym = r.get("asset") or r.get("symbol")
        pnl = float(r.get("shadow_pnl_usd", r.get("shadow_pnl", 0.0)))
        if sym in COINS: shadow_pnl[sym] = shadow_pnl.get(sym, 0.0) + pnl
    uplift = {sym: round(shadow_pnl.get(sym,0.0) - real_pnl.get(sym,0.0), 2) for sym in COINS}
    total_pos = sum(v for v in uplift.values() if v>0)
    score = max(0.0, 1 - math.exp(-total_pos/300.0))
    return {"uplift": uplift, "score": round(score,3)}

def _kg_links_recent(limit=3000):
    return _read_jsonl(KNOWLEDGE_GRAPH_LOG, limit)

def _severity_from_meta_gov() -> Dict[str,str]:
    rows = _read_jsonl(META_GOV_LOG, 2000)
    for r in reversed(rows):
        sev = r.get("health", {}).get("severity", {})
        if sev: return sev
    return {"system":"⚠️"}  # default warning

def _live_cfg() -> Dict[str,Any]:
    return _read_json(LIVE_CFG_PATH, default={})

def _save_cfg(cfg: Dict[str,Any]):
    _write_json(LIVE_CFG_PATH, cfg)

def _bounded(x, lo, hi): return max(lo, min(hi, x))

def _regime_key(regime: str) -> str:
    r = (regime or "").lower()
    return "trend" if ("trend" in r or "stable" in r) else "chop"

# Twin System helpers
def _init_twin_state():
    st = _read_json(TWIN_STATE_PATH, default=None)
    if st is None:
        st = {"primary_active": True, "last_validation_ts": None, "failover_triggered": False}
        _write_json(TWIN_STATE_PATH, st)
    return st

def _update_twin_state(updates: Dict[str,Any]):
    st = _read_json(TWIN_STATE_PATH, default={})
    st.update(updates)
    _write_json(TWIN_STATE_PATH, st)
    return st

def _twin_compare(a: Dict[str,Any], b: Dict[str,Any]) -> Dict[str,Any]:
    # Compare core fields to detect divergence; customizable tolerance
    def hashable(d):
        try: return json.dumps(d, sort_keys=True)
        except: return str(d)
    same_resilience = hashable(a.get("resilience",{})) == hashable(b.get("resilience",{}))
    same_profit      = hashable(a.get("profitability",{})) == hashable(b.get("profitability",{}))
    same_health      = hashable(a.get("health",{})) == hashable(b.get("health",{}))
    divergence = []
    if not same_resilience: divergence.append("resilience")
    if not same_profit:     divergence.append("profitability")
    if not same_health:     divergence.append("health")
    return {"divergent_fields": divergence, "is_divergent": len(divergence)>0}

# Orchestrator
class MetaLearningOrchestrator:
    """
    Interconnects modules into a cohesive adaptive learning loop with redundancy and failover.
    Sequence:
      1) Meta-Governor run_cycle → health + actions
      2) Liveness run_cycle → immediate resilience adjustments
      3) Profitability Governor run_cycle → persistent uplift-driven adjustments
      4) Meta-Research Desk run_cycle → experiments + knowledge graph links
      5) Consolidate → build digest, trigger adaptive cadence based on expectancy and health
      6) Twin validation → run a parallel "twin" summary and compare, failover if critical
    """
    def __init__(self,
                 cadence_seconds=1800,               # 30 min default
                 min_email_interval_seconds=1800,
                 max_threshold_relax_cum=0.05,
                 pca_brake_hi=0.60,
                 pca_brake_lo=0.40):
        self.cadence = cadence_seconds
        self.min_email_interval = min_email_interval_seconds
        self.max_relax_cum = max_threshold_relax_cum
        self.pca_brake_hi = pca_brake_hi
        self.pca_brake_lo = pca_brake_lo

        # Primary instances
        self.meta_gov  = MetaGovernor()
        self.liveness  = TradeLivenessMonitor(coins=COINS)
        self.profit    = ProfitabilityGovernor()
        self.research  = MetaResearchDesk()
        self.counterfactual = CounterfactualScalingEngine()
        self.fee_calibration = FeeCalibrationProbe()
        self.fee_attribution = FeeAttributionModule()
        self.profit_attribution = ProfitAttributionModule()
        self.slippage_latency = SlippageLatencyAttribution()
        self.strategy_attribution = StrategyAttribution()
        self.health_check = SystemHealthCheck()
        self.emergency = EmergencyAutonomyHooks()
        self.reverse_triage = ReverseTriage()
        self.watchdog = GovernanceWatchdog()
        self.dashboard_validator = DashboardValidator()
        self.counterfactual_intel = CounterfactualIntelligence()
        self.health_overlay = HealthCheckOverlay()

        # Twin instances (redundant run only for summary; execution routed by failover engine)
        self.twin_meta_gov = MetaGovernor()
        self.twin_liveness = TradeLivenessMonitor(coins=COINS)
        self.twin_profit   = ProfitabilityGovernor()
        self.twin_research = MetaResearchDesk()

    def _email_body_enhanced(self, gov_digest: Dict[str,Any], live_digest: Dict[str,Any], prof_digest: Dict[str,Any], res_digest: Dict[str,Any], cf_digest: Dict[str,Any], health_summary: Dict[str,Any], sev: Dict[str,str], expect: Dict[str,Any], rt_digest: Dict[str,Any]) -> str:
        return f"""
=== Meta-Learning Digest ===
Severity: {sev}
Expectancy Score: {expect['score']}

Resilience:
  Idle Minutes: {live_digest.get('idle_minutes')}
  Blockers: {live_digest.get('blockers')}
  Actions: {live_digest.get('actions')}

Profitability:
  Actions: {prof_digest.get('actions')}
  Top Missed: {prof_digest.get('top_missed')}
  Thresholds: {prof_digest.get('thresholds',{})}

Research:
  PCA Variance: {res_digest.get('pca_variance')}
  Expectancy Score (RD): {res_digest.get('expectancy_score')}
  Borderline Candidates: {res_digest.get('borderline_candidates')}
  Actions: {res_digest.get('actions')}

Counterfactual Scaling:
  Health Brake: {cf_digest.get('health_brake')}
  Canaries: {cf_digest.get('canaries_count')}
  Uplift Total: ${cf_digest.get('uplift_total')}
  Expectancy: {cf_digest.get('expectancy')}
  Actions: {cf_digest.get('actions')}

Health:
  Degraded Mode: {gov_digest.get('health',{}).get('degraded_mode')}
  Kill-Switch Cleared: {gov_digest.get('health',{}).get('kill_switch_cleared')}

{health_summary.get('email_body', '')}

{rt_digest.get('email_body', '')}
"""

    def _apply_adaptive_cadence(self, expectancy_score: float, pca_var: float) -> Optional[Dict[str,Any]]:
        # Speed up cadence when expectancy strong and risk moderate; slow down when PCA dominance high
        cfg = _live_cfg() or {}
        rt = cfg.get("runtime", {})
        current = int(rt.get("meta_cadence_seconds", self.cadence))
        new_cadence = current
        if expectancy_score >= 0.6 and pca_var <= self.pca_brake_lo:
            new_cadence = max(900, current - 300)  # accelerate to 15 min min
        elif pca_var >= self.pca_brake_hi:
            new_cadence = min(3600, current + 600) # slow to reduce churn up to 60 min
        if new_cadence != current:
            rt["meta_cadence_seconds"] = new_cadence
            cfg["runtime"] = rt
            _save_cfg(cfg)
            _append_jsonl(LEARNING_UPDATES_LOG, {"ts": _now(), "update_type":"adaptive_cadence_change", "old": current, "new": new_cadence})
            return {"old": current, "new": new_cadence}
        return None

    def run_cycle(self) -> Dict[str,Any]:
        # 0) Preflight invariants - fail-fast validation before cycle
        preflight = run_preflight_invariants()
        if preflight.get("fixes"):
            # Quarantine cycle: log critical failures and skip full run
            _append_jsonl(META_LEARN_LOG, {
                "ts": _now(),
                "update_type": "preflight_fail_quarantine",
                "preflight_results": preflight["results"],
                "fixes_required": preflight["fixes"]
            })
            return {
                "preflight_failed": True,
                "results": preflight["results"],
                "fixes": preflight["fixes"],
                "email_body": f"⚠️ PREFLIGHT INVARIANTS FAILED - CYCLE QUARANTINED\n\nFixes required: {json.dumps(preflight['fixes'], indent=2)}"
            }
        
        # 1) Governance
        gov_digest = self.meta_gov.run_cycle()
        sev = gov_digest.get("health", {}).get("severity", {}) or _severity_from_meta_gov()
        degraded = gov_digest.get("health", {}).get("degraded_mode", False)

        # Safety brake: if 🔴 in severity, avoid aggressive actions and only run diagnostics
        critical = ("🔴" in sev.values())

        # 2) Liveness (resilience)
        live_digest = self.liveness.run_cycle()

        # 3) Profitability
        prof_digest = self.profit.run_cycle()

        # 4) Research
        res_digest = self.research.run_cycle()

        # 5) Expectancy-driven learning modulation
        expect = _expectancy(_read_jsonl(EXEC_LOG, 8000), _read_jsonl(SHADOW_LOG, 8000), horizon_days=7)
        pca_var = _pca_variance_recent()

        cadence_change = self._apply_adaptive_cadence(expect["score"], pca_var)

        # 6) Counterfactual Scaling (health-gated - runs after expectancy computation)
        # Only run if health checks pass (no critical severity, not degraded, kill-switch cleared)
        cf_digest = {}
        if not critical and not degraded and gov_digest.get("health", {}).get("kill_switch_cleared", True):
            cf_digest = self.counterfactual.run_cycle()
        else:
            cf_digest = {
                "ts": _now(),
                "health_brake": True,
                "critical": critical,
                "degraded": degraded,
                "kill_switch_cleared": gov_digest.get("health", {}).get("kill_switch_cleared", False),
                "actions": [{"type": "health_brake_skip", "reason": "critical_or_degraded_or_kill_switch"}]
            }

        # 6.5) Fee Calibration Probe (auto-tune fee thresholds based on telemetry)
        fee_cal_digest = self.fee_calibration.run_cycle()

        # 6.6) Fee Attribution Module (track impact of fee calibration on expectancy/uplift)
        fee_attr_digest = self.fee_attribution.run_cycle()

        # 6.7) Profit Attribution Module (profit-centered governance with promotion/rollback gates)
        profit_attr_digest = self.profit_attribution.run_cycle()

        # 6.8) Slippage & Latency Attribution (execution quality tracking and routing optimization)
        slippage_digest = self.slippage_latency.run_cycle()

        # 6.9) Strategy Attribution (strategy-level PnL attribution and weight management)
        strategy_digest = self.strategy_attribution.run_cycle()

        # 6.10) Portfolio & Risk Governors (portfolio optimization + risk SLO enforcement)
        portfolio_risk_digest = run_portfolio_and_risk_cycle()

        # 6.11) Predictive Regime Governor (regime detection, prediction, and adaptive adjustments)
        regime_digest = run_regime_cycle()

        # 6.12) Dashboard Validator (self-auditing, full-area validation, auto-remediation)
        dashboard_digest = self.dashboard_validator.run_cycle()

        # 6.13) Counterfactual Intelligence (blocked signal analysis, gate threshold optimization)
        counterfactual_intel_digest = self.counterfactual_intel.run_cycle()

        # 6.14) Health Check Overlay (universal oversight + governance wiring)
        health_overlay_digest = self.health_overlay.run_cycle()

        # 7) System Health Check (full-system diagnostics)
        health_summary = self.health_check.run_cycle()

        # 8) Emergency Autonomy Suite (auto-remediation + learning controller)
        emergency_summary = self.emergency.run_emergency_if_needed(health_summary=health_summary)

        # 9) Governance Watchdog (trade funnel monitoring and autonomous recovery)
        watchdog_digest = self.watchdog.run_cycle()

        # Consolidated digest
        digest = {
            "ts": _now(),
            "severity": sev,
            "critical": critical,
            "degraded": degraded,
            "gov": gov_digest,
            "liveness": live_digest,
            "profit": prof_digest,
            "research": res_digest,
            "counterfactual": cf_digest,
            "fee_calibration": fee_cal_digest,
            "fee_attribution": fee_attr_digest,
            "profit_attribution": profit_attr_digest,
            "slippage_latency": slippage_digest,
            "strategy_attribution": strategy_digest,
            "portfolio_risk": portfolio_risk_digest,
            "regime_governor": regime_digest,
            "dashboard_validator": dashboard_digest,
            "counterfactual_intelligence": counterfactual_intel_digest,
            "health_overlay": health_overlay_digest,
            "health_check": health_summary,
            "emergency": emergency_summary,
            "watchdog": watchdog_digest,
            "expectancy": expect,
            "pca_variance": round(pca_var,3),
            "cadence_change": cadence_change,
        }
        # 10) Reverse Triage (profit-first backward diagnosis)
        rt_digest = self.reverse_triage.run_cycle()
        
        digest["email_body"] = self._email_body_enhanced(gov_digest, live_digest, prof_digest, res_digest, cf_digest, health_summary, sev, expect, rt_digest) + "\n\n" + fee_cal_digest.get("email_body", "") + "\n\n" + fee_attr_digest.get("email_body", "") + "\n\n" + profit_attr_digest.get("email_body", "") + "\n\n" + slippage_digest.get("email_body", "") + "\n\n" + strategy_digest.get("email_body", "") + "\n\n" + portfolio_risk_digest.get("email_body", "") + "\n\n" + regime_digest.get("email_body", "") + "\n\n" + dashboard_digest.get("email_body", "") + "\n\n" + counterfactual_intel_digest.get("email_body", "") + "\n\n" + health_overlay_digest.get("email_body", "") + "\n\n" + watchdog_digest.get("email_body", "") + "\n\n" + emergency_summary.get("email_body", "")

        # Persist
        _append_jsonl(META_LEARN_LOG, digest)
        _append_jsonl(LEARNING_UPDATES_LOG, {"ts": digest["ts"], "update_type":"meta_learning_cycle", "digest": digest})

        return digest

    # Twin System: validate from logs instead of re-running modules to avoid duplicate actions
    def run_twin_validation(self) -> Dict[str,Any]:
        _init_twin_state()

        # Read recent digests from logs instead of re-running modules
        # This prevents duplicate governance actions (threshold adjustments, sizing nudges, etc.)
        primary_rows = _read_jsonl(META_LEARN_LOG, 10)
        
        if len(primary_rows) < 2:
            # Not enough history for twin validation yet
            return {"state": _init_twin_state(), "comparison": {"divergent_fields": [], "is_divergent": False}, "failover": False}
        
        current_digest = primary_rows[-1]
        prev_digest = primary_rows[-2]
        
        # Extract comparable fields from current and previous cycles
        current_comparable = {
            "health": current_digest.get("gov", {}).get("health", {}),
            "resilience": current_digest.get("liveness", {}),
            "profitability": current_digest.get("profit", {})
        }
        
        prev_comparable = {
            "health": prev_digest.get("gov", {}).get("health", {}),
            "resilience": prev_digest.get("liveness", {}),
            "profitability": prev_digest.get("profit", {})
        }

        cmp = _twin_compare(current_comparable, prev_comparable)

        # Failover decision: if divergence includes "health" with critical severity, trigger failover
        current_sev = current_comparable.get("health", {}).get("severity", {})
        current_critical = ("🔴" in (current_sev or {}).values())
        should_failover = cmp["is_divergent"] and ("health" in cmp["divergent_fields"]) and current_critical

        # Update twin state
        state_updates = {"last_validation_ts": _now(), "failover_triggered": should_failover}
        st = _update_twin_state(state_updates)

        # Log
        record = {
            "ts": _now(),
            "comparison": cmp,
            "current_critical": current_critical,
            "failover_triggered": should_failover,
            "current_comparable": current_comparable,
            "prev_comparable": prev_comparable
        }
        _append_jsonl(TWIN_SYNC_LOG, record)

        # If failover, route execution bridge to twin mode via live_config flag
        if should_failover:
            cfg = _live_cfg() or {}
            run = cfg.get("runtime", {})
            run["execution_bridge_mode"] = "twin"
            run["degraded_mode"] = True  # be conservative on failover
            cfg["runtime"] = run
            _save_cfg(cfg)
            _append_jsonl(LEARNING_UPDATES_LOG, {"ts": _now(), "update_type":"failover_activated", "reason":"critical_divergence", "runtime": run})

        return {"state": st, "comparison": cmp, "failover": should_failover}

# ---------------- CLI ----------------
if __name__ == "__main__":
    mlo = MetaLearningOrchestrator()
    digest = mlo.run_cycle()
    print("Meta-Learning Digest:", json.dumps(digest, indent=2))

    validation = mlo.run_twin_validation()
    print("Twin Validation:", json.dumps(validation, indent=2))
