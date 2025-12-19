# src/scheduler_with_analysis.py
#
# v7.1 Unified Scheduler: Fee audits + Recovery cycle + Nightly digest + Desk-grade analysis harness
# v7.2 Override Audit: Logs active overrides, detects conflicts, auto-expires after digest
# v7.2 Decision Attribution: Counterfactual learning (executed vs blocked) runs after nightly digest
# Purpose:
#   - Run continuous reviews of all logs (executions, signals, learning updates)
#   - Feed results into runtime config for autonomous learning
#   - Produce daily digest with recommendations (enable/disable symbols, size adjustments, latency gates)
#   - Audit and expire manual overrides for governance visibility
#   - Learn dollar impact of trading vs not trading via counterfactuals
#
import time, json, os
from src.desk_grade_analysis_harness import analyze, build_digest
from src.full_integration_blofin_micro_live_and_paper import run_fee_venue_audit, run_recovery_cycle, nightly_learning_digest
from src.override_audit import run_override_audit_cycle
from src.decision_attribution import run_counterfactual_cycle
from src.strategy_auto_tuning import run_strategy_auto_tuning
from src.multi_horizon_attribution import run_multi_horizon_attribution
from src.horizon_weighted_evolution import run_horizon_weighted_evolution
from src.multi_agent_coordinator import run_multi_agent_coordinator
from src.multi_agent_coordinator_vns import run_multi_agent_coordinator_vns
from src.missed_opportunity_probe import run_missed_opportunity_probe
from src.meta_governance_watchdogs import run_meta_governance_watchdogs
from src.digest_extension import build_unified_digest
from src.profit_driven_evolution import run_profit_driven_evolution
from src.upgrade_pack_v7_2_plus import run_full_upgrade_pack_cycle
from src.gate_complexity_monitor import run_gate_complexity_monitor
from src.pipeline_self_heal import nightly_pre_enrichment_self_heal
from src.data_enrichment_layer import run_enrichment_cycle
from src.scenario_replay_auto_tuner import run_scenario_auto_tuner
from src.scenario_slicer_auto_tuner_v2 import run_scenario_slicer_auto_tuner_v2
from src.profit_first_governor import run_profit_first_governor

EXEC_LOG  = "logs/executed_trades.jsonl"
SIG_LOG   = "logs/strategy_signals.jsonl"
OUT_JSON  = "logs/analysis_summary.json"
OUT_TXT   = "logs/analysis_digest.txt"

def _read_jsonl(path, limit=200000):
    rows=[]
    if not os.path.exists(path): return rows
    with open(path,"r") as f:
        for line in f:
            line=line.strip()
            if not line: continue
            try: rows.append(json.loads(line))
            except: continue
    return rows[-limit:]

def run_analysis_cycle():
    exec_rows=_read_jsonl(EXEC_LOG, 200000)
    sig_rows =_read_jsonl(SIG_LOG,  200000)
    summary=analyze(exec_rows, sig_rows)
    digest=build_digest(summary)
    with open(OUT_JSON,"w") as f: json.dump(summary,f,indent=2)
    with open(OUT_TXT,"w") as f: f.write(digest)
    print(digest)
    return summary

def start_unified_scheduler(interval_secs=600):
    """
    Every interval (default 10 min):
      - Run fee audit
      - Run recovery cycle
      - Run override audit (logs active overrides, detects conflicts)
    Nightly (~07:00 UTC):
      - Run data enrichment (join signals + outcomes for replay analysis)
      - Run scenario replay auto-tuner (grid search with strict WR/PnL gates)
      - Run UPGRADE PACK v7.2+ (backtest, regime detect, gate optimizer, sanity scan, WR sentinel)
      - Expire manual overrides (force_unfreeze, manual_override)
      - Run digest
      - Run desk-grade analysis harness
      - Run counterfactual learning (60m standard)
      - Run multi-horizon attribution (5m, 60m, 1d, 1w)
      - Run missed opportunity probe (early-filtered signal counterfactuals)
      - Run horizon-weighted evolution (timeframe-aware parameter tuning)
      - Run gate complexity monitor (detect over-gating, recommend simplification)
      - Run meta-governance watchdogs (hysteresis-based auto-tuning)
      - Run multi-agent coordinator (Alpha/EMA capital allocation + arbitration)
      - Run multi-agent coordinator VNS (volatility-normalized refinement)
      - Run strategy auto-tuning (Alpha/EMA parameters)
      - Build unified nightly digest (consolidated JSON + TXT)
      - Run profit-driven evolution (attribution-weighted calibration)
      - Run profit-first governor (strategy/symbol allocation based on realized profits)
    """
    last_digest_day=None
    while True:
        try:
            run_fee_venue_audit()
            run_recovery_cycle()
            run_override_audit_cycle()
            utc_h=int(time.gmtime().tm_hour)
            utc_d=int(time.gmtime().tm_yday)
            if utc_h==7 and last_digest_day!=utc_d:
                # === PHASE 0: Pipeline Self-Heal (BEFORE enrichment) ===
                nightly_pre_enrichment_self_heal()  # Fix paths, quarantine dead files
                
                # === PHASE 1: Data Preparation ===
                run_enrichment_cycle(lookback_hours=48)  # Join signals + outcomes FIRST
                
                # === PHASE 2: Parameter Optimization ===
                run_scenario_auto_tuner(window_days=14, target_wr=0.40)  # Global grid search
                run_scenario_slicer_auto_tuner_v2(window_days=14, min_wr=0.40, max_slices=300)  # Per-slice optimization with counterfactuals
                
                # === PHASE 3: Performance Acceleration & Learning ===
                run_full_upgrade_pack_cycle()  # v7.2+ Performance Acceleration Pack
                nightly_learning_digest()
                run_analysis_cycle()
                run_counterfactual_cycle(horizon_minutes=60)
                run_multi_horizon_attribution(horizons=(5,60,1440,10080), weighting_mode="profit_max")
                run_missed_opportunity_probe(horizons=(5,60,1440,10080), weighting_mode="profit_max")
                run_horizon_weighted_evolution(mode="profit_max")
                run_gate_complexity_monitor(window_hours=12, max_active_gates=8)
                run_meta_governance_watchdogs()
                run_multi_agent_coordinator()
                run_multi_agent_coordinator_vns()
                run_strategy_auto_tuning()
                build_unified_digest()
                run_profit_driven_evolution()
                
                # === PHASE 4: Profit-First Allocation ===
                run_profit_first_governor()  # Promote/demote based on realized profits
                
                # === PHASE 5: Profitability Trader Persona - Comprehensive Analysis ===
                try:
                    from src.profitability_trader_persona import run_profitability_analysis
                    profitability_analysis = run_profitability_analysis()
                    if profitability_analysis.get("profitability_actions"):
                        critical = [a for a in profitability_analysis["profitability_actions"] if a.get("priority") == "CRITICAL"]
                        if critical:
                            print(f"🚨 [PROFITABILITY] {len(critical)} CRITICAL issues identified - review report")
                except Exception as e:
                    print(f"⚠️ [PROFITABILITY] Trader persona analysis failed: {e}")
                
                last_digest_day=utc_d
        except Exception as e:
            print("Scheduler error:",e)
        time.sleep(interval_secs)

if __name__=="__main__":
    # Start unified scheduler with 10-min cadence
    start_unified_scheduler(interval_secs=600)