#!/usr/bin/env python3
"""
STRATEGIC ADVISOR MODULE
========================
Proactive profitability intelligence - runs hourly analysis of profit leaks
and surfaces actionable insights to improve trading outcomes.

Features:
1. Hourly analysis of recent trades for profitability gaps
2. Fee impact analysis - detect when fees erode too much profit
3. Exit timing analysis - detect early exits leaving money on table
4. Correlation loss analysis - detect correlated positions losing together
5. Prioritized recommendations with expected impact

Usage:
    from src.strategic_advisor import StrategicAdvisor
    
    advisor = StrategicAdvisor()
    insights = advisor.run_hourly_analysis()
    recommendations = advisor.collect_recommendations()

Writes to:
    - feature_store/strategic_advisor_state.json (current state)
    - logs/strategic_advisor_insights.jsonl (insights log)

Author: Trading Bot System
Date: December 2025
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
from collections import defaultdict
from pathlib import Path

from src.data_registry import DataRegistry as DR
from src.file_locks import atomic_json_write, locked_json_read, atomic_json_save

CORRELATION_CLUSTERS = [
    ['ETHUSDT', 'SOLUSDT', 'AVAXUSDT', 'DOTUSDT', 'MATICUSDT'],
    ['BTCUSDT'],
    ['TRXUSDT', 'XRPUSDT'],
    ['ARBUSDT', 'OPUSDT'],
    ['LINKUSDT'],
    ['PEPEUSDT', 'DOGEUSDT'],
    ['ADAUSDT', 'BNBUSDT'],
]

SYMBOL_TO_CLUSTER = {}
for cluster_idx, cluster in enumerate(CORRELATION_CLUSTERS):
    for sym in cluster:
        SYMBOL_TO_CLUSTER[sym] = cluster_idx

PRIORITY_HIGH = "high"
PRIORITY_MEDIUM = "medium"
PRIORITY_LOW = "low"

HOLD_TIME_BUCKETS = {
    "flash": (0, 60),
    "scalp": (60, 300),
    "quick": (300, 900),
    "short": (900, 3600),
    "medium": (3600, 14400),
    "long": (14400, float("inf")),
}


def _now() -> str:
    """Return current UTC timestamp as ISO string."""
    return datetime.utcnow().isoformat() + "Z"


def _log(msg: str):
    """Log message with timestamp."""
    ts = datetime.utcnow().isoformat() + "Z"
    print(f"[{ts}] [STRATEGIC-ADVISOR] {msg}")


def _parse_timestamp(ts_str: str) -> Optional[datetime]:
    """Parse timestamp string to datetime."""
    if not ts_str:
        return None
    try:
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1]
        if "+" in ts_str:
            ts_str = ts_str.split("+")[0]
        elif ts_str.count("-") > 2:
            parts = ts_str.rsplit("-", 1)
            if ":" in parts[-1]:
                ts_str = parts[0]
        return datetime.fromisoformat(ts_str)
    except:
        return None


def _calc_hold_time_seconds(opened_at: str, closed_at: str) -> float:
    """Calculate hold time in seconds."""
    opened = _parse_timestamp(opened_at)
    closed = _parse_timestamp(closed_at)
    if opened and closed:
        return (closed - opened).total_seconds()
    return 0.0


def _classify_hold_time(seconds: float) -> str:
    """Classify hold time into bucket."""
    for bucket, (min_s, max_s) in HOLD_TIME_BUCKETS.items():
        if min_s <= seconds < max_s:
            return bucket
    return "unknown"


def _append_jsonl(path: str, record: dict):
    """Append record to JSONL file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'a') as f:
        f.write(json.dumps(record, default=str) + '\n')


class StrategicAdvisor:
    """
    Strategic Advisor for proactive profitability intelligence.
    
    Analyzes recent trades to identify:
    - Fee erosion (when fees eat too much of gross profit)
    - Early exits (leaving unrealized profit on table)
    - Correlation losses (multiple positions in same cluster losing)
    - Win rate and P&L trends
    
    Generates prioritized recommendations for improving profitability.
    """
    
    def __init__(self):
        self.state: Dict[str, Any] = {}
        self.trades: List[Dict] = []
        self.recommendations: List[Dict] = []
        self.insights: Dict[str, Any] = {}
        self._load_data()
    
    def _load_data(self):
        """Load state and trade data."""
        self.state = locked_json_read(DR.STRATEGIC_ADVISOR_STATE, default={})
        
        positions_data = locked_json_read(DR.POSITIONS_FUTURES, default={})
        self.trades = positions_data.get("closed_positions", [])
        
        _log(f"Loaded {len(self.trades)} closed trades from positions_futures.json")
        
        if not self.state:
            self.state = {
                "created_at": _now(),
                "last_run": None,
                "runs_count": 0,
                "total_recommendations": 0,
                "metrics_history": [],
            }
    
    def _save_state(self):
        """Save state atomically."""
        atomic_json_save(DR.STRATEGIC_ADVISOR_STATE, self.state)
    
    def _log_insight(self, insight: Dict):
        """Append insight to insights log."""
        insight["logged_at"] = _now()
        _append_jsonl(DR.STRATEGIC_ADVISOR_LOG, insight)
    
    def load_learned_policies(self) -> Dict[str, Any]:
        """
        Load and incorporate learned policies from profitability acceleration modules.
        
        Reads from:
        - feature_store/fee_gate_learning.json
        - feature_store/hold_time_policy.json
        - feature_store/edge_sizer_calibration.json
        - feature_store/correlation_throttle_policy.json
        
        Returns:
            Dict with policy data and drift alerts
        """
        policies = {
            "fee_gate": {},
            "hold_time": {},
            "edge_sizer": {},
            "correlation": {},
            "drift_alerts": [],
            "loaded_at": _now(),
        }
        
        fee_gate_path = "feature_store/fee_gate_learning.json"
        if os.path.exists(fee_gate_path):
            try:
                with open(fee_gate_path, 'r') as f:
                    policies["fee_gate"] = json.load(f)
            except:
                pass
        
        hold_time_path = "feature_store/hold_time_policy.json"
        if os.path.exists(hold_time_path):
            try:
                with open(hold_time_path, 'r') as f:
                    policies["hold_time"] = json.load(f)
            except:
                pass
        
        edge_sizer_path = "feature_store/edge_sizer_calibration.json"
        if os.path.exists(edge_sizer_path):
            try:
                with open(edge_sizer_path, 'r') as f:
                    policies["edge_sizer"] = json.load(f)
            except:
                pass
        
        corr_path = "feature_store/correlation_throttle_policy.json"
        if os.path.exists(corr_path):
            try:
                with open(corr_path, 'r') as f:
                    policies["correlation"] = json.load(f)
            except:
                pass
        
        drift_alerts = self._detect_policy_drift(policies)
        policies["drift_alerts"] = drift_alerts
        
        if drift_alerts:
            _log(f"Policy drift detected: {len(drift_alerts)} alerts")
            for alert in drift_alerts:
                _log(f"  - {alert['policy']}: {alert['message']}")
        
        return policies
    
    def _detect_policy_drift(self, policies: Dict) -> List[Dict]:
        """
        Detect significant changes in learned policies that warrant attention.
        
        Args:
            policies: Current policy data from load_learned_policies()
            
        Returns:
            List of drift alert dictionaries
        """
        alerts = []
        
        previous_policies = self.state.get("last_policies", {})
        
        if policies.get("fee_gate") and previous_policies.get("fee_gate"):
            old_threshold = previous_policies["fee_gate"].get("threshold", 0.17)
            new_threshold = policies["fee_gate"].get("threshold", 0.17)
            
            if abs(new_threshold - old_threshold) >= 0.02:
                direction = "tightened" if new_threshold > old_threshold else "loosened"
                alerts.append({
                    "policy": "fee_gate",
                    "type": "threshold_drift",
                    "severity": "medium",
                    "old_value": old_threshold,
                    "new_value": new_threshold,
                    "message": f"Fee gate threshold {direction}: {old_threshold:.4f} -> {new_threshold:.4f}",
                    "detected_at": _now(),
                })
        
        if policies.get("hold_time") and previous_policies.get("hold_time"):
            old_holds = previous_policies["hold_time"].get("symbol_hold_times", {})
            new_holds = policies["hold_time"].get("symbol_hold_times", {})
            
            changed_symbols = []
            for symbol in set(old_holds.keys()) | set(new_holds.keys()):
                old_val = old_holds.get(symbol, 300)
                new_val = new_holds.get(symbol, 300)
                if abs(new_val - old_val) >= 60:
                    changed_symbols.append(symbol)
            
            if len(changed_symbols) >= 3:
                alerts.append({
                    "policy": "hold_time",
                    "type": "multiple_symbol_drift",
                    "severity": "high" if len(changed_symbols) >= 5 else "medium",
                    "symbols_changed": changed_symbols,
                    "message": f"Hold time policy changed for {len(changed_symbols)} symbols",
                    "detected_at": _now(),
                })
        
        if policies.get("edge_sizer") and previous_policies.get("edge_sizer"):
            old_mults = previous_policies["edge_sizer"].get("multipliers", {})
            new_mults = policies["edge_sizer"].get("multipliers", {})
            
            significant_changes = []
            for grade in ["A", "B", "C", "D", "F"]:
                old_val = old_mults.get(grade, 1.0)
                new_val = new_mults.get(grade, 1.0)
                if abs(new_val - old_val) >= 0.15:
                    significant_changes.append({
                        "grade": grade,
                        "old": old_val,
                        "new": new_val,
                    })
            
            if significant_changes:
                alerts.append({
                    "policy": "edge_sizer",
                    "type": "grade_multiplier_drift",
                    "severity": "medium",
                    "changes": significant_changes,
                    "message": f"Edge sizer multipliers changed for grades: {[c['grade'] for c in significant_changes]}",
                    "detected_at": _now(),
                })
        
        if policies.get("correlation") and previous_policies.get("correlation"):
            old_thresh = previous_policies["correlation"].get("high_corr_threshold", 0.7)
            new_thresh = policies["correlation"].get("high_corr_threshold", 0.7)
            
            if abs(new_thresh - old_thresh) >= 0.05:
                direction = "tightened" if new_thresh < old_thresh else "loosened"
                alerts.append({
                    "policy": "correlation",
                    "type": "threshold_drift",
                    "severity": "high" if abs(new_thresh - old_thresh) >= 0.1 else "medium",
                    "old_value": old_thresh,
                    "new_value": new_thresh,
                    "message": f"Correlation threshold {direction}: {old_thresh:.3f} -> {new_thresh:.3f}",
                    "detected_at": _now(),
                })
        
        return alerts
    
    def incorporate_learned_policies(self) -> Dict[str, Any]:
        """
        Load learned policies and incorporate them into recommendations.
        
        This method:
        1. Loads current learned policies from all profitability modules
        2. Detects drift from previous policy state
        3. Generates recommendations based on policy changes
        4. Stores current policies for future drift detection
        
        Returns:
            Dict with policies, drift alerts, and generated recommendations
        """
        policies = self.load_learned_policies()
        
        policy_recommendations = []
        
        for alert in policies.get("drift_alerts", []):
            if alert["severity"] == "high":
                priority = PRIORITY_HIGH
            elif alert["severity"] == "medium":
                priority = PRIORITY_MEDIUM
            else:
                priority = PRIORITY_LOW
            
            if alert["policy"] == "fee_gate":
                rec = {
                    "priority": priority,
                    "category": "fee_optimization",
                    "issue": f"Fee gate threshold has drifted",
                    "action": f"Review fee gate settings - threshold moved from {alert.get('old_value', '?')} to {alert.get('new_value', '?')}",
                    "expected_impact": "Affects trade entry filtering",
                    "source": "policy_drift",
                    "generated_at": _now(),
                }
                policy_recommendations.append(rec)
            
            elif alert["policy"] == "hold_time":
                rec = {
                    "priority": priority,
                    "category": "hold_time_optimization",
                    "issue": f"Hold time policies changed for multiple symbols",
                    "action": f"Review hold time settings for: {', '.join(alert.get('symbols_changed', [])[:5])}",
                    "expected_impact": "Affects minimum hold duration before exits",
                    "source": "policy_drift",
                    "generated_at": _now(),
                }
                policy_recommendations.append(rec)
            
            elif alert["policy"] == "edge_sizer":
                rec = {
                    "priority": priority,
                    "category": "position_sizing",
                    "issue": "Edge sizer multipliers recalibrated",
                    "action": "Review signal grade multipliers - performance patterns may have shifted",
                    "expected_impact": "Affects position sizing based on signal quality",
                    "source": "policy_drift",
                    "generated_at": _now(),
                }
                policy_recommendations.append(rec)
            
            elif alert["policy"] == "correlation":
                rec = {
                    "priority": priority,
                    "category": "risk_management",
                    "issue": "Correlation throttle threshold adjusted",
                    "action": f"Review correlation settings - threshold moved from {alert.get('old_value', '?')} to {alert.get('new_value', '?')}",
                    "expected_impact": "Affects how many correlated positions can be open",
                    "source": "policy_drift",
                    "generated_at": _now(),
                }
                policy_recommendations.append(rec)
        
        self.state["last_policies"] = {
            "fee_gate": policies.get("fee_gate", {}),
            "hold_time": policies.get("hold_time", {}),
            "edge_sizer": policies.get("edge_sizer", {}),
            "correlation": policies.get("correlation", {}),
            "stored_at": _now(),
        }
        
        return {
            "policies": policies,
            "drift_alerts": policies.get("drift_alerts", []),
            "recommendations": policy_recommendations,
        }
    
    def run_hourly_analysis(self) -> Dict[str, Any]:
        """
        Main analysis method - runs hourly profitability gap analysis.
        
        Returns:
            Dict with analysis results and recommendations
        """
        _log("Starting hourly analysis...")
        
        now = datetime.utcnow()
        cutoff_24h = now - timedelta(hours=24)
        cutoff_1h = now - timedelta(hours=1)
        
        recent_trades = []
        for t in self.trades:
            closed_at = _parse_timestamp(t.get("closed_at", ""))
            if closed_at and closed_at >= cutoff_24h:
                recent_trades.append(t)
        
        _log(f"Analyzing {len(recent_trades)} trades from last 24 hours")
        
        metrics = self._calculate_metrics(recent_trades)
        
        fee_analysis = self._analyze_fee_impact(recent_trades)
        exit_analysis = self._analyze_exit_timing(recent_trades)
        correlation_analysis = self._analyze_correlation_losses(recent_trades)
        
        self.recommendations = self._generate_recommendations(
            metrics, fee_analysis, exit_analysis, correlation_analysis
        )
        
        policy_result = self.incorporate_learned_policies()
        policy_drift_recs = policy_result.get("recommendations", [])
        self.recommendations = policy_drift_recs + self.recommendations
        
        self.insights = {
            "run_at": _now(),
            "trades_analyzed": len(recent_trades),
            "metrics": metrics,
            "fee_analysis": fee_analysis,
            "exit_analysis": exit_analysis,
            "correlation_analysis": correlation_analysis,
            "policy_drift_alerts": policy_result.get("drift_alerts", []),
            "recommendations_count": len(self.recommendations),
            "top_recommendations": self.recommendations[:5] if self.recommendations else [],
        }
        
        self._log_insight(self.insights)
        
        self.state["last_run"] = _now()
        self.state["runs_count"] = self.state.get("runs_count", 0) + 1
        self.state["total_recommendations"] = self.state.get("total_recommendations", 0) + len(self.recommendations)
        self.state["latest_metrics"] = metrics
        self.state["latest_recommendations"] = self.recommendations[:10]
        
        if "metrics_history" not in self.state:
            self.state["metrics_history"] = []
        self.state["metrics_history"].append({
            "timestamp": _now(),
            "metrics": metrics,
        })
        self.state["metrics_history"] = self.state["metrics_history"][-48:]
        
        self._save_state()
        
        _log(f"Analysis complete: {len(self.recommendations)} recommendations generated")
        
        return self.insights
    
    def _calculate_metrics(self, trades: List[Dict]) -> Dict[str, Any]:
        """
        Calculate key performance metrics from trades.
        
        Returns:
            Dict with win_rate, avg_pnl, total_pnl, fee_impact, hold_time_distribution
        """
        if not trades:
            return {
                "win_rate": 0.0,
                "total_trades": 0,
                "winners": 0,
                "losers": 0,
                "avg_pnl": 0.0,
                "total_pnl": 0.0,
                "total_fees": 0.0,
                "fee_impact_pct": 0.0,
                "avg_hold_time_seconds": 0.0,
                "hold_time_distribution": {},
            }
        
        winners = 0
        losers = 0
        total_pnl = 0.0
        total_fees = 0.0
        total_gross = 0.0
        hold_times = []
        hold_time_dist = defaultdict(int)
        
        for t in trades:
            pnl = t.get("pnl", t.get("net_pnl", 0)) or 0
            fees = t.get("trading_fees", 0) or 0
            gross = t.get("gross_pnl", pnl + fees) or 0
            
            total_pnl += pnl
            total_fees += fees
            total_gross += gross
            
            if pnl > 0:
                winners += 1
            else:
                losers += 1
            
            opened_at = t.get("opened_at", "")
            closed_at = t.get("closed_at", "")
            hold_sec = _calc_hold_time_seconds(opened_at, closed_at)
            if hold_sec > 0:
                hold_times.append(hold_sec)
                bucket = _classify_hold_time(hold_sec)
                hold_time_dist[bucket] += 1
        
        total = winners + losers
        win_rate = (winners / total * 100) if total > 0 else 0.0
        avg_pnl = total_pnl / total if total > 0 else 0.0
        avg_hold = sum(hold_times) / len(hold_times) if hold_times else 0.0
        
        fee_impact_pct = 0.0
        if total_gross != 0:
            fee_impact_pct = (total_fees / abs(total_gross)) * 100
        
        return {
            "win_rate": round(win_rate, 2),
            "total_trades": total,
            "winners": winners,
            "losers": losers,
            "avg_pnl": round(avg_pnl, 4),
            "total_pnl": round(total_pnl, 4),
            "total_gross_pnl": round(total_gross, 4),
            "total_fees": round(total_fees, 4),
            "fee_impact_pct": round(fee_impact_pct, 2),
            "avg_hold_time_seconds": round(avg_hold, 2),
            "hold_time_distribution": dict(hold_time_dist),
        }
    
    def _analyze_fee_impact(self, trades: List[Dict]) -> Dict[str, Any]:
        """
        Analyze fee erosion - trades where fees eat significant portion of profit.
        
        Returns:
            Dict with fee analysis including worst offenders
        """
        if not trades:
            return {
                "trades_analyzed": 0,
                "fee_eroded_trades": 0,
                "total_fee_erosion": 0.0,
                "avg_fee_pct": 0.0,
                "worst_offenders": [],
            }
        
        fee_eroded = []
        total_fee_erosion = 0.0
        fee_pcts = []
        
        for t in trades:
            gross = t.get("gross_pnl", 0) or 0
            fees = t.get("trading_fees", 0) or 0
            net = t.get("pnl", t.get("net_pnl", 0)) or 0
            symbol = t.get("symbol", "UNKNOWN")
            
            if gross > 0 and fees > 0:
                fee_pct = (fees / gross) * 100
                fee_pcts.append(fee_pct)
                
                if fee_pct > 50:
                    erosion = fees - (gross * 0.3)
                    if erosion > 0:
                        total_fee_erosion += erosion
                        fee_eroded.append({
                            "symbol": symbol,
                            "gross_pnl": round(gross, 4),
                            "fees": round(fees, 4),
                            "net_pnl": round(net, 4),
                            "fee_pct": round(fee_pct, 2),
                            "erosion": round(erosion, 4),
                            "closed_at": t.get("closed_at", ""),
                        })
            elif gross <= 0 and fees > 0:
                fee_pcts.append(100.0)
        
        fee_eroded_sorted = sorted(fee_eroded, key=lambda x: x["erosion"], reverse=True)
        
        return {
            "trades_analyzed": len(trades),
            "fee_eroded_trades": len(fee_eroded),
            "total_fee_erosion": round(total_fee_erosion, 4),
            "avg_fee_pct": round(sum(fee_pcts) / len(fee_pcts), 2) if fee_pcts else 0.0,
            "worst_offenders": fee_eroded_sorted[:5],
        }
    
    def _analyze_exit_timing(self, trades: List[Dict]) -> Dict[str, Any]:
        """
        Analyze exit timing - detect early exits and premature closures.
        
        Returns:
            Dict with exit timing analysis
        """
        if not trades:
            return {
                "trades_analyzed": 0,
                "early_exits": 0,
                "forced_exits": 0,
                "signal_reversal_exits": 0,
                "by_close_reason": {},
                "avg_hold_by_outcome": {},
            }
        
        close_reasons = defaultdict(int)
        early_exits = []
        outcome_hold_times = {"winners": [], "losers": []}
        
        for t in trades:
            reason = t.get("close_reason", "unknown")
            close_reasons[reason] += 1
            
            pnl = t.get("pnl", t.get("net_pnl", 0)) or 0
            opened_at = t.get("opened_at", "")
            closed_at = t.get("closed_at", "")
            hold_sec = _calc_hold_time_seconds(opened_at, closed_at)
            
            if pnl > 0:
                outcome_hold_times["winners"].append(hold_sec)
            else:
                outcome_hold_times["losers"].append(hold_sec)
            
            if reason in ["risk_cap_asset_exposure", "risk_cap_symbol", "correlation_cap"]:
                early_exits.append({
                    "symbol": t.get("symbol", "UNKNOWN"),
                    "reason": reason,
                    "pnl": round(pnl, 4),
                    "hold_time_sec": round(hold_sec, 2),
                    "closed_at": closed_at,
                })
        
        forced_count = sum(
            close_reasons.get(r, 0) 
            for r in ["risk_cap_asset_exposure", "risk_cap_symbol", "stop_loss", "kill_switch"]
        )
        signal_reverse = close_reasons.get("ladder_signal_reverse", 0) + close_reasons.get("signal_reverse", 0)
        
        avg_hold_by_outcome = {}
        for outcome, times in outcome_hold_times.items():
            if times:
                avg_hold_by_outcome[outcome] = round(sum(times) / len(times), 2)
        
        return {
            "trades_analyzed": len(trades),
            "early_exits": len(early_exits),
            "forced_exits": forced_count,
            "signal_reversal_exits": signal_reverse,
            "by_close_reason": dict(close_reasons),
            "avg_hold_by_outcome": avg_hold_by_outcome,
            "early_exit_samples": early_exits[:5],
        }
    
    def _analyze_correlation_losses(self, trades: List[Dict]) -> Dict[str, Any]:
        """
        Analyze correlation losses - trades in same cluster losing together.
        
        Returns:
            Dict with correlation loss analysis
        """
        if not trades:
            return {
                "trades_analyzed": 0,
                "correlated_loss_events": 0,
                "total_correlated_losses": 0.0,
                "cluster_performance": {},
                "correlated_loss_samples": [],
            }
        
        trades_by_time = defaultdict(list)
        for t in trades:
            closed_at = t.get("closed_at", "")
            closed_dt = _parse_timestamp(closed_at)
            if closed_dt:
                time_bucket = closed_dt.replace(minute=0, second=0, microsecond=0)
                trades_by_time[time_bucket].append(t)
        
        correlated_losses = []
        total_corr_loss = 0.0
        cluster_pnl = defaultdict(lambda: {"pnl": 0.0, "trades": 0, "winners": 0})
        
        for t in trades:
            symbol = t.get("symbol", "UNKNOWN")
            pnl = t.get("pnl", t.get("net_pnl", 0)) or 0
            cluster_idx = SYMBOL_TO_CLUSTER.get(symbol, -1)
            
            if cluster_idx >= 0:
                cluster_pnl[cluster_idx]["pnl"] += pnl
                cluster_pnl[cluster_idx]["trades"] += 1
                if pnl > 0:
                    cluster_pnl[cluster_idx]["winners"] += 1
        
        for time_bucket, bucket_trades in trades_by_time.items():
            if len(bucket_trades) < 2:
                continue
            
            cluster_bucket = defaultdict(list)
            for t in bucket_trades:
                symbol = t.get("symbol", "UNKNOWN")
                cluster_idx = SYMBOL_TO_CLUSTER.get(symbol, -1)
                if cluster_idx >= 0:
                    cluster_bucket[cluster_idx].append(t)
            
            for cluster_idx, ctrades in cluster_bucket.items():
                if len(ctrades) < 2:
                    continue
                
                cluster_pnls = [t.get("pnl", t.get("net_pnl", 0)) or 0 for t in ctrades]
                losers = sum(1 for p in cluster_pnls if p < 0)
                
                if losers >= 2:
                    cluster_loss = sum(p for p in cluster_pnls if p < 0)
                    total_corr_loss += abs(cluster_loss)
                    
                    cluster_symbols = [CORRELATION_CLUSTERS[cluster_idx]] if cluster_idx < len(CORRELATION_CLUSTERS) else []
                    correlated_losses.append({
                        "time_bucket": str(time_bucket),
                        "cluster": cluster_symbols[0] if cluster_symbols else [],
                        "losing_trades": losers,
                        "total_loss": round(cluster_loss, 4),
                        "symbols": [t.get("symbol") for t in ctrades],
                    })
        
        cluster_perf = {}
        for cluster_idx, data in cluster_pnl.items():
            if cluster_idx < len(CORRELATION_CLUSTERS):
                cluster_name = ",".join(CORRELATION_CLUSTERS[cluster_idx][:2]) + "..."
                wr = (data["winners"] / data["trades"] * 100) if data["trades"] > 0 else 0
                cluster_perf[cluster_name] = {
                    "total_pnl": round(data["pnl"], 4),
                    "trades": data["trades"],
                    "win_rate": round(wr, 2),
                }
        
        return {
            "trades_analyzed": len(trades),
            "correlated_loss_events": len(correlated_losses),
            "total_correlated_losses": round(total_corr_loss, 4),
            "cluster_performance": cluster_perf,
            "correlated_loss_samples": correlated_losses[:5],
        }
    
    def _generate_recommendations(
        self,
        metrics: Dict[str, Any],
        fee_analysis: Dict[str, Any],
        exit_analysis: Dict[str, Any],
        correlation_analysis: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Generate prioritized recommendations based on analysis.
        
        Returns:
            List of recommendations sorted by priority and expected impact
        """
        recommendations = []
        
        fee_pct = fee_analysis.get("avg_fee_pct", 0)
        fee_eroded = fee_analysis.get("fee_eroded_trades", 0)
        fee_erosion = fee_analysis.get("total_fee_erosion", 0)
        
        if fee_pct > 40:
            recommendations.append({
                "id": "fee_erosion_high",
                "type": "fee_optimization",
                "priority": PRIORITY_HIGH,
                "issue": f"High fee erosion: {fee_pct:.1f}% of gross profit consumed by fees",
                "action": "Increase minimum expected move threshold before entry",
                "expected_impact": f"Save ~${fee_erosion:.2f} in fee leakage",
                "config_suggestion": {
                    "min_expected_move_vs_fee": 2.5,
                    "fee_gate_enabled": True,
                },
            })
        elif fee_pct > 25:
            recommendations.append({
                "id": "fee_erosion_medium",
                "type": "fee_optimization",
                "priority": PRIORITY_MEDIUM,
                "issue": f"Moderate fee impact: {fee_pct:.1f}% of gross profit",
                "action": "Consider larger position sizes or fewer trades",
                "expected_impact": "Improve net P&L by ~15-20%",
            })
        
        early_exits = exit_analysis.get("early_exits", 0)
        forced_exits = exit_analysis.get("forced_exits", 0)
        total_trades = exit_analysis.get("trades_analyzed", 1)
        
        if total_trades > 0 and forced_exits / total_trades > 0.3:
            recommendations.append({
                "id": "forced_exits_high",
                "type": "risk_management",
                "priority": PRIORITY_HIGH,
                "issue": f"High forced exit rate: {forced_exits}/{total_trades} trades ({forced_exits/total_trades*100:.0f}%)",
                "action": "Reduce position sizes or widen risk caps",
                "expected_impact": "Allow trades to reach target exits",
                "config_suggestion": {
                    "reduce_initial_size_pct": 20,
                    "increase_asset_cap_pct": 10,
                },
            })
        
        avg_hold_winners = exit_analysis.get("avg_hold_by_outcome", {}).get("winners", 0)
        avg_hold_losers = exit_analysis.get("avg_hold_by_outcome", {}).get("losers", 0)
        
        if avg_hold_winners > 0 and avg_hold_losers > 0:
            if avg_hold_losers > avg_hold_winners * 1.5:
                recommendations.append({
                    "id": "hold_time_asymmetry",
                    "type": "exit_timing",
                    "priority": PRIORITY_HIGH,
                    "issue": f"Holding losers too long: losers avg {avg_hold_losers:.0f}s vs winners {avg_hold_winners:.0f}s",
                    "action": "Implement tighter stop-losses for losing positions",
                    "expected_impact": "Reduce average loss size",
                })
        
        corr_losses = correlation_analysis.get("total_correlated_losses", 0)
        corr_events = correlation_analysis.get("correlated_loss_events", 0)
        
        if corr_events >= 3 and corr_losses > 10:
            recommendations.append({
                "id": "correlation_exposure",
                "type": "portfolio_risk",
                "priority": PRIORITY_HIGH,
                "issue": f"Correlated losses: {corr_events} events totaling ${corr_losses:.2f}",
                "action": "Enable correlation throttling to limit cluster exposure",
                "expected_impact": f"Avoid ~${corr_losses*0.5:.2f} in simultaneous losses",
                "config_suggestion": {
                    "correlation_throttle_enabled": True,
                    "max_cluster_exposure_pct": 30,
                },
            })
        
        cluster_perf = correlation_analysis.get("cluster_performance", {})
        for cluster_name, perf in cluster_perf.items():
            if perf["trades"] >= 5 and perf["total_pnl"] < -20:
                recommendations.append({
                    "id": f"weak_cluster_{cluster_name[:10]}",
                    "type": "asset_selection",
                    "priority": PRIORITY_MEDIUM,
                    "issue": f"Cluster underperforming: {cluster_name} has P&L ${perf['total_pnl']:.2f}",
                    "action": f"Consider reducing exposure to correlated assets in this cluster",
                    "expected_impact": "Avoid further losses in weak cluster",
                })
        
        win_rate = metrics.get("win_rate", 50)
        avg_pnl = metrics.get("avg_pnl", 0)
        
        if win_rate < 45 and metrics.get("total_trades", 0) >= 10:
            recommendations.append({
                "id": "low_win_rate",
                "type": "signal_quality",
                "priority": PRIORITY_HIGH,
                "issue": f"Low win rate: {win_rate:.1f}% (need >50% for profitability)",
                "action": "Tighten entry criteria and signal confirmation requirements",
                "expected_impact": "Improve trade selection quality",
            })
        
        if avg_pnl < -1.0 and metrics.get("total_trades", 0) >= 10:
            recommendations.append({
                "id": "negative_expectancy",
                "type": "strategy_review",
                "priority": PRIORITY_HIGH,
                "issue": f"Negative expectancy: avg P&L ${avg_pnl:.2f} per trade",
                "action": "Review and adjust entry/exit criteria, consider pause",
                "expected_impact": "Stop ongoing losses",
            })
        
        hold_dist = metrics.get("hold_time_distribution", {})
        flash_trades = hold_dist.get("flash", 0) + hold_dist.get("scalp", 0)
        total = sum(hold_dist.values()) if hold_dist else 1
        
        if total > 0 and flash_trades / total > 0.5:
            recommendations.append({
                "id": "too_fast_exits",
                "type": "exit_timing",
                "priority": PRIORITY_MEDIUM,
                "issue": f"Most trades exit too fast: {flash_trades}/{total} under 5 minutes",
                "action": "Implement minimum hold time or increase R/R targets",
                "expected_impact": "Capture more of the move before exiting",
            })
        
        priority_order = {PRIORITY_HIGH: 0, PRIORITY_MEDIUM: 1, PRIORITY_LOW: 2}
        recommendations.sort(key=lambda x: priority_order.get(x["priority"], 99))
        
        return recommendations
    
    def collect_recommendations(self) -> List[Dict[str, Any]]:
        """
        Return current recommendations.
        
        Returns:
            List of prioritized recommendations
        """
        if not self.recommendations:
            if self.state.get("latest_recommendations"):
                return self.state["latest_recommendations"]
            self.run_hourly_analysis()
        
        return self.recommendations
    
    def get_latest_insights(self) -> Dict[str, Any]:
        """
        Get latest insights for dashboard display.
        
        Returns:
            Dict with latest analysis results
        """
        if not self.insights:
            if self.state.get("latest_metrics"):
                return {
                    "metrics": self.state["latest_metrics"],
                    "recommendations_count": len(self.state.get("latest_recommendations", [])),
                    "top_recommendations": self.state.get("latest_recommendations", [])[:3],
                    "last_run": self.state.get("last_run"),
                    "runs_count": self.state.get("runs_count", 0),
                }
            self.run_hourly_analysis()
        
        return {
            "metrics": self.insights.get("metrics", {}),
            "fee_analysis": self.insights.get("fee_analysis", {}),
            "exit_analysis": self.insights.get("exit_analysis", {}),
            "correlation_analysis": self.insights.get("correlation_analysis", {}),
            "recommendations_count": self.insights.get("recommendations_count", 0),
            "top_recommendations": self.insights.get("top_recommendations", []),
            "last_run": self.state.get("last_run"),
            "runs_count": self.state.get("runs_count", 0),
        }


def run_strategic_advisor() -> Dict[str, Any]:
    """Convenience function to run strategic advisor analysis."""
    advisor = StrategicAdvisor()
    return advisor.run_hourly_analysis()


if __name__ == "__main__":
    _log("Running Strategic Advisor...")
    advisor = StrategicAdvisor()
    insights = advisor.run_hourly_analysis()
    
    print("\n" + "=" * 60)
    print("STRATEGIC ADVISOR INSIGHTS")
    print("=" * 60)
    
    metrics = insights.get("metrics", {})
    print(f"\n📊 METRICS (last 24h):")
    print(f"   Trades: {metrics.get('total_trades', 0)}")
    print(f"   Win Rate: {metrics.get('win_rate', 0):.1f}%")
    print(f"   Total P&L: ${metrics.get('total_pnl', 0):.2f}")
    print(f"   Avg P&L: ${metrics.get('avg_pnl', 0):.2f}")
    print(f"   Fee Impact: {metrics.get('fee_impact_pct', 0):.1f}%")
    
    fee = insights.get("fee_analysis", {})
    print(f"\n💸 FEE ANALYSIS:")
    print(f"   Fee-Eroded Trades: {fee.get('fee_eroded_trades', 0)}")
    print(f"   Total Fee Erosion: ${fee.get('total_fee_erosion', 0):.2f}")
    
    exit_info = insights.get("exit_analysis", {})
    print(f"\n🚪 EXIT TIMING:")
    print(f"   Forced Exits: {exit_info.get('forced_exits', 0)}")
    print(f"   Signal Reversals: {exit_info.get('signal_reversal_exits', 0)}")
    
    corr = insights.get("correlation_analysis", {})
    print(f"\n🔗 CORRELATION:")
    print(f"   Correlated Loss Events: {corr.get('correlated_loss_events', 0)}")
    print(f"   Total Correlated Losses: ${corr.get('total_correlated_losses', 0):.2f}")
    
    recs = advisor.collect_recommendations()
    print(f"\n📋 RECOMMENDATIONS ({len(recs)} total):")
    for i, rec in enumerate(recs[:5], 1):
        print(f"   {i}. [{rec['priority'].upper()}] {rec['issue']}")
        print(f"      Action: {rec['action']}")
    
    print("\n" + "=" * 60)
