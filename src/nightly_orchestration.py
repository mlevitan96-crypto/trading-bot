# src/nightly_orchestration.py
#
# Nightly Orchestration Cycle
# - Runs multi-asset analysis across all 11 futures
# - Generates per-asset metrics, regimes, and scaling decisions
# - Builds portfolio-level capacity curves
# - Applies portfolio-level scaling policy (promotion/rollback)
# - Runs automated asset reviews for underperformance governance
# - Logs unified audit packets

import os, json, time, random
import sys
# Add project root to path for imports
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.multi_asset_orchestration import multi_asset_cycle, ASSETS
from src.portfolio_scaling_policy import portfolio_scaling_decision, portfolio_scaling_audit
from src.asset_review import run_asset_reviews
from src.auto_correction import run_auto_corrections, apply_adjustments_to_configs
from src.governance_upgrade import run_governance_upgrade
from src.alpha_lab import alpha_lab_cycle
from src.alpha_accelerator import alpha_accelerator_cycle
from src.profit_push_engine import run_profit_push
import json

# v5.6 Exploitation Infrastructure
from src.exploitation_overlays import LeadLagValidator, CommunityRiskManager, PCAOverlay
from src.governance_digest import GovernanceDigest
from src.multi_horizon_tuner import MultiHorizonTuner

# Adaptive Intelligence Learning (learns when to invert vs follow)
from src.adaptive_intelligence_learner import AdaptiveIntelligenceLearner, run_adaptive_analysis

# Hold Time Improvement Monitor (tracks if hold time fixes are working)
from src.hold_time_monitor import print_hold_time_report, analyze_recent_hold_times

# Synchronized ML Training (trains models on entry-time synchronized features)
from src.ml_predictor import run_synchronized_training_pipeline

# Data Enrichment Layer (joins signals with outcomes for learning)
from src.data_enrichment_layer import run_enrichment_cycle

# Comprehensive Learning Evaluation (unified analysis framework)
from src.comprehensive_learning_evaluation import run_comprehensive_evaluation

# Use absolute paths for logs (PROJECT_ROOT already defined above)
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
NIGHTLY_AUDIT_LOG = os.path.join(LOG_DIR,"nightly_orchestration.jsonl")

def _now(): return int(time.time())
def _append_jsonl(path,obj): os.makedirs(os.path.dirname(path),exist_ok=True); open(path,"a").write(json.dumps(obj)+"\n")

def _build_returns_matrix(lookback=100):
    """Build returns matrix from portfolio snapshots for PCA/correlation analysis."""
    import numpy as np
    try:
        portfolio_file = os.path.join(PROJECT_ROOT, "logs", "portfolio.json")
        if not os.path.exists(portfolio_file):
            return np.random.randn(len(ASSETS), lookback) * 0.01
        
        with open(portfolio_file, 'r') as f:
            portfolio_data = json.load(f)
        
        returns_by_asset = {asset: [] for asset in ASSETS}
        recent_snapshots = portfolio_data[-lookback:] if len(portfolio_data) > lookback else portfolio_data
        
        for snapshot in recent_snapshots:
            if 'roi' in snapshot and 'symbol' in snapshot:
                symbol = snapshot['symbol']
                if symbol in returns_by_asset:
                    returns_by_asset[symbol].append(snapshot['roi'])
        
        returns_matrix = []
        for asset in ASSETS:
            asset_returns = returns_by_asset.get(asset, [])
            if len(asset_returns) < lookback:
                asset_returns = asset_returns + [0.0] * (lookback - len(asset_returns))
            returns_matrix.append(asset_returns[:lookback])
        
        return np.array(returns_matrix)
    except Exception as e:
        print(f"⚠️ [v5.6] Failed to build returns matrix: {e}")
        return np.random.randn(len(ASSETS), lookback) * 0.01

def _load_open_positions():
    """Load open positions from position manager."""
    try:
        from src.position_manager import load_positions
        positions_data = load_positions()
        return positions_data.get("open_positions", [])
    except Exception as e:
        print(f"⚠️ [v5.6] Failed to load positions: {e}")
        return []

# ----------------------------------------------------------------------
# Nightly Orchestration Cycle
# ----------------------------------------------------------------------
def nightly_cycle(price_series_by_asset, trades_by_asset, capacity_trades_by_asset, modes_by_asset, portfolio_alloc_tests, signal_attribution_by_asset=None, per_trade_logs_by_asset=None, sentiment_feed=None, per_asset_performance=None, corr_matrix=None):
    """
    Runs full orchestration + portfolio scaling + asset governance reviews + auto-correction + governance upgrade.
    
    Args:
        signal_attribution_by_asset: Optional dict mapping asset -> list of signal performance data
            e.g., {"BTCUSDT": [{"signal":"Momentum","impact":0.002,"pnl":0.01,"wr":0.58}, ...]}
        per_trade_logs_by_asset: Optional dict mapping asset -> list of detailed trade logs with signals/features
        sentiment_feed: Optional list of sentiment data dicts
        per_asset_performance: Optional dict mapping asset -> performance metrics for canary evaluation
        corr_matrix: Optional correlation matrix for portfolio reweighting
    """
    # Step 0: Data Enrichment (join signals with outcomes for learning)
    enrichment_audit = None
    try:
        enrichment_audit = run_enrichment_cycle(lookback_hours=48)
        print(f"✅ [Nightly] Data Enrichment complete - {enrichment_audit.get('enriched_count', 0)} records")
    except Exception as e:
        print(f"⚠️  [Nightly] Data Enrichment failed (non-fatal): {e}")
        enrichment_audit = {"error": str(e), "ts": _now()}

    # Step 1: Multi-asset orchestration
    summary = multi_asset_cycle(
        price_series_by_asset,
        trades_by_asset,
        capacity_trades_by_asset,
        modes_by_asset,
        portfolio_alloc_tests=portfolio_alloc_tests
    )

    # Step 2: Automated asset reviews (governance for underperformance)
    asset_reviews = run_asset_reviews(summary, signal_attribution_by_asset=signal_attribution_by_asset)

    # Step 3: Auto-correction for flagged assets (learning loop closure)
    auto_corrections = None
    if per_trade_logs_by_asset is not None and asset_reviews.get("reviews"):
        auto_corrections = run_auto_corrections(
            summary, 
            asset_reviews, 
            per_trade_logs_by_asset or {}, 
            sentiment_feed or []
        )
        if auto_corrections["adjustments"]:
            apply_adjustments_to_configs(auto_corrections["adjustments"])

    # Step 4: Governance upgrade (canary A/B, drift monitors, correlation-aware reweighting)
    governance_audit = None
    if auto_corrections:
        governance_audit = run_governance_upgrade(
            multi_asset_summary=summary,
            reviews_output=asset_reviews,
            per_asset_performance=per_asset_performance,
            sentiment_series=sentiment_feed,
            corr_matrix=corr_matrix
        )

    # Step 4.5: Alpha Lab (champion selection, bandit optimization, anomaly detection)
    STRAT_OVERRIDES_PATH = os.path.join(PROJECT_ROOT, "configs", "strategy_overrides.json")
    alpha_lab_audit = None
    if governance_audit and per_trade_logs_by_asset:
        try:
            with open(STRAT_OVERRIDES_PATH, "r") as f:
                strat_overrides = json.load(f)
        except:
            strat_overrides = {"assets": {}}
        try:
            alpha_lab_audit = alpha_lab_cycle(
                multi_asset_summary=summary,
                per_trade_logs_by_asset=per_trade_logs_by_asset,
                auto_correction_overrides=strat_overrides,
                governance_audit=governance_audit,
                sentiment_feed=sentiment_feed
            )
            print(f"✅ [Nightly] Alpha Lab complete")
        except Exception as e:
            print(f"⚠️  [Nightly] Alpha Lab failed (non-fatal): {e}")
            alpha_lab_audit = {"error": str(e), "ts": _now()}

    # Step 4.75: Alpha Accelerator (aggressive meta-research, cross-asset learning, fast promotions)
    alpha_accelerator_audit = None
    if alpha_lab_audit and per_trade_logs_by_asset:
        try:
            with open(STRAT_OVERRIDES_PATH, "r") as f:
                strat_overrides = json.load(f)
        except:
            strat_overrides = {"assets": {}}
        try:
            alpha_accelerator_audit = alpha_accelerator_cycle(
                multi_asset_summary=summary,
                governance_audit=governance_audit,
                per_trade_logs_by_asset=per_trade_logs_by_asset,
                auto_correction_overrides=strat_overrides
            )
            print(f"✅ [Nightly] Alpha Accelerator complete")
        except Exception as e:
            print(f"⚠️  [Nightly] Alpha Accelerator failed (non-fatal): {e}")
            alpha_accelerator_audit = {"error": str(e), "ts": _now()}

    # Step 4.875: Profit Push Engine (exploration intensity, auto-pruning, rolling objectives)
    profit_push_audit = None
    if alpha_accelerator_audit and per_trade_logs_by_asset:
        ACCEL_OVERRIDES_PATH = os.path.join(PROJECT_ROOT, "configs", "accelerator_overrides.json")
        try:
            with open(ACCEL_OVERRIDES_PATH, "r") as f:
                accel_overrides = json.load(f)
        except:
            accel_overrides = {"assets": {}}
        try:
            profit_push_audit = run_profit_push(
                multi_asset_summary=summary,
                per_trade_logs_by_asset=per_trade_logs_by_asset,
                governance_audit=governance_audit,
                accelerator_overrides=accel_overrides,
                registry=None,
                anomalies_by_asset={}
            )
            print(f"✅ [Nightly] Profit Push complete")
        except Exception as e:
            print(f"⚠️  [Nightly] Profit Push failed (non-fatal): {e}")
            profit_push_audit = {"error": str(e), "ts": _now()}

    # Step 4.9: Adaptive Intelligence Learning (learns when to invert vs follow signals)
    adaptive_intel_audit = None
    try:
        adaptive_intel_audit = run_adaptive_analysis()
        print(f"✅ [Nightly] Adaptive Intelligence Learning complete")
        print(f"   - Total decisions analyzed: {adaptive_intel_audit.get('total_decisions', 0)}")
        print(f"   - Adaptation rules updated: {len(adaptive_intel_audit.get('adaptation_rules', {}).get('symbol_overrides', {}))}")
    except Exception as e:
        print(f"⚠️  [Nightly] Adaptive Intelligence Learning failed (non-fatal): {e}")
        adaptive_intel_audit = {"error": str(e), "ts": _now()}

    # Step 4.92: Hold Time Improvement Monitor (tracks if hold time fixes are working)
    hold_time_audit = None
    try:
        hold_time_audit = print_hold_time_report()
        print(f"✅ [Nightly] Hold Time Monitor complete")
        if hold_time_audit and not hold_time_audit.get("error"):
            avg = hold_time_audit.get("avg_hold_minutes", 0)
            target = hold_time_audit.get("target_avg_hold_min", 15)
            if avg < target:
                print(f"   ⚠️ ALERT: Avg hold {avg}min < target {target}min - timing fixes may need adjustment")
            else:
                print(f"   ✅ SUCCESS: Avg hold {avg}min meets target")
    except Exception as e:
        print(f"⚠️  [Nightly] Hold Time Monitor failed (non-fatal): {e}")
        hold_time_audit = {"error": str(e), "ts": _now()}

    # Step 4.95: v5.6 Exploitation Infrastructure (Lead-Lag, Community Risk, PCA, Digest, Tuner)
    v56_audit = None
    try:
        llv = LeadLagValidator()
        crm = CommunityRiskManager()
        pca = PCAOverlay()
        
        if corr_matrix:
            for leader in ASSETS[:3]:
                for follower in ASSETS[3:6]:
                    if leader != follower and corr_matrix.get(leader, {}).get(follower, 0) > 0.6:
                        lag_signals = {1: corr_matrix[leader][follower], 4: corr_matrix[leader][follower] * 0.9}
                        llv.update(leader, follower, lag_signals)
        
        positions = _load_open_positions()
        returns_matrix = _build_returns_matrix(lookback=100)
        
        digest_result = None
        try:
            # Correlation digest emails disabled (not providing actionable insights)
            gd = GovernanceDigest(
                llv, crm, pca,
                smtp_user=os.getenv("SMTP_USER"),
                smtp_pass=os.getenv("SMTP_PASS"),
                email_to=None,  # Disabled - correlation metrics not actionable
                smtp_host=os.getenv("SMTP_HOST", "smtp.gmail.com"),
                smtp_port=int(os.getenv("SMTP_PORT", "587"))
            )
            digest_result = gd.snapshot(positions, returns_matrix)
            print(f"✅ [v5.6] Governance digest complete: {digest_result['ts']}")
        except Exception as e:
            print(f"⚠️ [v5.6] Governance digest failed (non-fatal): {e}")
            digest_result = {"error": str(e), "ts": _now()}
        
        tuner_result = None
        try:
            # Multi-horizon tuner emails also disabled (same correlation data)
            tuner = MultiHorizonTuner(
                llv, crm, pca,
                smtp_user=os.getenv("SMTP_USER"),
                smtp_pass=os.getenv("SMTP_PASS"),
                email_to=None,  # Disabled - correlation metrics not actionable
                smtp_host=os.getenv("SMTP_HOST", "smtp.gmail.com"),
                smtp_port=int(os.getenv("SMTP_PORT", "587"))
            )
            tuner_result = tuner.run(positions_snapshot=positions, returns_matrix=returns_matrix)
            print(f"✅ [v5.6] Multi-horizon tuner complete: daily={tuner_result.get('daily',{})}, medium={tuner_result.get('medium',{})}, weekly={tuner_result.get('weekly',{})}")
        except Exception as e:
            print(f"⚠️ [v5.6] Multi-horizon tuner failed (non-fatal): {e}")
            tuner_result = {"error": str(e)}
        
        v56_audit = {
            "ts": _now(),
            "digest": digest_result,
            "tuner": tuner_result,
            "positions_count": len(positions),
            "returns_shape": returns_matrix.shape if hasattr(returns_matrix, 'shape') else None
        }
        print(f"✅ [v5.6] Exploitation infrastructure complete")
        
    except Exception as e:
        print(f"⚠️ [v5.6] Exploitation infrastructure failed (non-fatal): {e}")
        v56_audit = {"error": str(e), "ts": _now()}

    # Step 4.97: Meta-Research Desk (experiment generation, expectancy scoring, canary trades, knowledge graph)
    meta_research_audit = None
    try:
        from src.meta_research_desk import MetaResearchDesk
        mrd = MetaResearchDesk()
        meta_research_audit = mrd.run_cycle()
        print(f"✅ [Meta-Research] Cycle complete: {len(meta_research_audit.get('actions', []))} actions, expectancy={meta_research_audit.get('expectancy_score', 0)}")
        if meta_research_audit.get('borderline_candidates'):
            print(f"   Borderline candidates: {len(meta_research_audit.get('borderline_candidates', []))} across {len(meta_research_audit.get('coins', []))} coins")
    except Exception as e:
        print(f"⚠️ [Meta-Research] Failed (non-fatal): {e}")
        meta_research_audit = {"error": str(e), "ts": _now()}

    # Step 4.98: Synchronized ML Training (trains models on entry-time features)
    ml_training_audit = None
    try:
        ml_training_audit = run_synchronized_training_pipeline()
        models_trained = ml_training_audit.get('models_trained', 0)
        promotable = ml_training_audit.get('promotable_models', 0)
        status = ml_training_audit.get('status', 'complete')
        
        if status == 'insufficient_data':
            print(f"⏳ [ML-Training] Collecting synchronized features ({ml_training_audit.get('total_samples', 0)} samples)")
        else:
            print(f"✅ [ML-Training] Synchronized training complete")
            print(f"   Models trained: {models_trained}")
            print(f"   Promotable (>55% accuracy): {promotable}")
            
            if promotable > 0:
                results = ml_training_audit.get('results', {})
                for symbol, data in results.items():
                    if data.get('is_promotable'):
                        print(f"   📈 {symbol}: {data['cv_accuracy']:.1f}% accuracy (ready for live)")
    except Exception as e:
        print(f"⚠️ [ML-Training] Failed (non-fatal): {e}")
        ml_training_audit = {"error": str(e), "ts": _now()}

    # Step 5: Portfolio-level scaling decision
    portfolio_curves = summary["portfolio_capacity_curves"]
    current_mode = "shadow"  # global portfolio mode (could be tracked persistently)
    decision = portfolio_scaling_decision(current_mode, portfolio_curves, audit_pass=True)

    # Step 6: Audit packet
    audit = portfolio_scaling_audit({"portfolio":"11 assets","tested_allocations":portfolio_alloc_tests}, decision)

    # Step 6: Counterfactual Analysis (analyze trades we didn't take)
    counterfactual_analysis = None
    try:
        from src.counterfactual_analyzer import get_counterfactual_summary
        counterfactual_analysis = get_counterfactual_summary(lookback_hours=168)
        print(f"✅ [Nightly] Counterfactual analysis complete")
        print(f"   Missed opportunities: {counterfactual_analysis['false_negatives']['total_counterfactuals']}")
        print(f"   Would-have-won rate: {counterfactual_analysis['false_negatives']['missed_win_rate']*100:.1f}%")
    except Exception as e:
        print(f"⚠️  [Nightly] Counterfactual analysis failed (non-fatal): {e}")
        counterfactual_analysis = {"error": str(e)}

    # Step 6.5: Comprehensive Learning Evaluation (unified analysis framework)
    comprehensive_eval = None
    try:
        comprehensive_eval = run_comprehensive_evaluation(hours=24, deep_dive=False)
        print(f"✅ [Nightly] Comprehensive Learning Evaluation complete")
        print(f"   Total trades: {comprehensive_eval.get('executed_trades', {}).get('total_trades', 0)}")
        print(f"   Recommendations: {len(comprehensive_eval.get('recommendations', []))}")
        print(f"   Report saved to: reports/comprehensive_evaluation_*.md")
    except Exception as e:
        print(f"⚠️  [Nightly] Comprehensive Learning Evaluation failed (non-fatal): {e}")
        comprehensive_eval = {"error": str(e), "ts": _now()}

    packet = {
        "ts": _now(),
        "multi_asset_summary": summary,
        "asset_reviews": asset_reviews,
        "auto_corrections": auto_corrections,
        "governance_upgrade": governance_audit,
        "alpha_lab": alpha_lab_audit,
        "alpha_accelerator": alpha_accelerator_audit,
        "profit_push": profit_push_audit,
        "v56_exploitation": v56_audit,
        "meta_research": meta_research_audit,
        "ml_training": ml_training_audit,
        "counterfactual_analysis": counterfactual_analysis,
        "comprehensive_learning": comprehensive_eval,
        "portfolio_scaling_decision": decision,
        "audit": audit
    }
    _append_jsonl(NIGHTLY_AUDIT_LOG, packet)
    
    # Step 7: Send comprehensive nightly email report (HTML with executive summary, PnL, per-coin updates)
    try:
        from src.nightly_email_report_v2 import send_nightly_email_report_v2
        send_nightly_email_report_v2()
        print("✅ [Nightly] Comprehensive HTML email report sent")
    except Exception as e:
        print(f"⚠️  [Nightly] Email report failed (non-fatal): {e}")
    
    return packet

# ----------------------------------------------------------------------
# CLI quick run (mock data)
# ----------------------------------------------------------------------
if __name__=="__main__":
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

    # Mock signal attribution for testing
    signal_attrib = {
        "ETHUSDT": [
            {"signal":"Momentum","impact":-0.0012,"pnl":-0.006,"wr":0.42},
            {"signal":"OFI","impact":0.0003,"pnl":0.002,"wr":0.55},
            {"signal":"Sentiment","impact":-0.0005,"pnl":-0.002,"wr":0.48}
        ]
    }
    
    # Mock per-trade logs for auto-correction testing
    per_trade_logs = {
        "ETHUSDT": [
            {"ts":_now()-1000,"roi":-0.01,"expected":100,"actual":100.15,
             "order":{"size":1.0},"fills":[{"size":0.6,"latency_ms":120},{"size":0.4,"latency_ms":200}],
             "signals":{"Momentum":0.3,"OFI":0.2,"MeanReversion":0.1},
             "features":{"sentiment":-0.2,"vol":0.018,"chop":0.3}},
            {"ts":_now()-800,"roi":0.012,"expected":99.8,"actual":99.81,
             "order":{"size":0.8},"fills":[{"size":0.5,"latency_ms":90},{"size":0.3,"latency_ms":140}],
             "signals":{"Momentum":0.25,"OFI":0.15,"MeanReversion":0.05},
             "features":{"sentiment":0.1,"vol":0.012,"chop":0.2}}
        ]
    }
    
    # Mock sentiment feed
    sentiment_feed = [
        {"ts":_now()-1200,"asset":"ALL","score":-0.05},
        {"ts":_now()-900,"asset":"ETHUSDT","score":-0.2},
        {"ts":_now()-400,"asset":"ALL","score":0.1}
    ]
    
    # Mock per-asset performance for canary evaluation
    per_asset_performance = {
        "BTCUSDT": {"expectancy": 0.0015, "win_rate": 0.63, "profit_factor": 1.7, "capacity_ok": True},
        "ETHUSDT": {"expectancy": 0.0012, "win_rate": 0.62, "profit_factor": 1.65, "capacity_ok": True},
        "AVAXUSDT": {"expectancy": -0.0003, "win_rate": 0.51, "profit_factor": 1.22, "capacity_ok": True},
        "TRXUSDT": {"expectancy": -0.0002, "win_rate": 0.48, "profit_factor": 1.15, "capacity_ok": False},
        "BNBUSDT": {"expectancy": 0.0001, "win_rate": 0.55, "profit_factor": 1.28, "capacity_ok": True}
    }
    
    # Mock correlation matrix
    import random
    corr_matrix = {}
    for s in ASSETS:
        corr_matrix[s] = {}
        for t in ASSETS:
            corr_matrix[s][t] = 1.0 if s==t else random.uniform(-0.2, 0.8)

    packet = nightly_cycle(
        price_series_by_asset,
        trades_by_asset,
        capacity_trades_by_asset,
        modes_by_asset,
        portfolio_alloc_tests=[0.05,0.10,0.20,0.40],
        signal_attribution_by_asset=signal_attrib,
        per_trade_logs_by_asset=per_trade_logs,
        sentiment_feed=sentiment_feed,
        per_asset_performance=per_asset_performance,
        corr_matrix=corr_matrix
    )

    result = {
        "portfolio_scaling_decision": packet["portfolio_scaling_decision"],
        "weights": packet["multi_asset_summary"]["weights"],
        "asset_reviews_summary": packet["asset_reviews"]["summary"]
    }
    
    if packet.get("auto_corrections"):
        result["auto_corrections_summary"] = packet["auto_corrections"]["summary"]
    
    if packet.get("governance_upgrade"):
        result["governance_summary"] = {
            "promoted_assets": packet["governance_upgrade"]["summary"]["promoted_assets"],
            "rolled_back_assets": packet["governance_upgrade"]["summary"]["rolled_back_assets"],
            "kpis": packet["governance_upgrade"]["summary"]["kpis"]
        }
    
    print(json.dumps(result, indent=2))
