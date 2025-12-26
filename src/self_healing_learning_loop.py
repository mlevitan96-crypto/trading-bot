"""
Self-Healing Learning Loop - Component 5
==========================================
Compares shadow vs live trades every 4 hours to identify guard effectiveness
and automatically adjust trading parameters.

Runs as a background daemon, analyzing:
- Which guards are saving money vs costing money
- Which blocked trades would have been profitable
- Which executed trades should have been blocked
- Guard parameter optimization recommendations
"""

import json
import time
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict
from dataclasses import dataclass, asdict

try:
    from src.data_registry import DataRegistry as DR
except ImportError:
    DR = None

LOGS = Path("logs")
FEATURE_STORE = Path("feature_store")
LEARNING_LOOP_STATE = FEATURE_STORE / "self_healing_learning_loop_state.json"
LEARNING_LOOP_LOG = LOGS / "self_healing_learning_loop.jsonl"

# Analysis window: Compare trades from last 4 hours
ANALYSIS_WINDOW_HOURS = 4
ANALYSIS_INTERVAL_SECONDS = 4 * 60 * 60  # Run every 4 hours

# Hyperparameter optimization: Run every 12 hours
HYPERPARAM_OPTIMIZATION_INTERVAL_SECONDS = 12 * 60 * 60  # Run every 12 hours
HYPERPARAM_TRADE_COUNT = 50  # Analyze last 50 trades for threshold tuning


@dataclass
class GuardEffectiveness:
    """Effectiveness metrics for a guard/gate"""
    guard_name: str
    blocks_count: int = 0
    blocks_avoided_losses: float = 0.0  # P&L of blocked trades (negative = saved money)
    blocks_missed_profits: float = 0.0  # P&L of blocked trades (positive = missed profits)
    allows_count: int = 0
    allows_profits: float = 0.0  # P&L of allowed trades
    allows_losses: float = 0.0  # Losses from allowed trades
    net_benefit: float = 0.0  # Net benefit (positive = good, negative = bad)
    effectiveness_score: float = 0.0  # 0-1 score


@dataclass
class LearningLoopResults:
    """Results from a learning loop analysis cycle"""
    timestamp: str
    window_start: str
    window_end: str
    shadow_trades_analyzed: int
    live_trades_analyzed: int
    guard_effectiveness: Dict[str, GuardEffectiveness]
    recommendations: List[Dict[str, Any]]
    total_net_benefit: float


class SelfHealingLearningLoop:
    """
    Self-healing learning loop that compares shadow vs live trades.
    """
    
    def __init__(self):
        self.running = False
        self.thread = None
        self.last_analysis_ts = 0
        self.last_hyperparam_optimization_ts = 0
        self._lock = threading.RLock()
        
        # Ensure directories exist
        LOGS.mkdir(parents=True, exist_ok=True)
        FEATURE_STORE.mkdir(parents=True, exist_ok=True)
    
    def start(self):
        """Start the learning loop daemon"""
        if self.running:
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        print("🔄 [SELF-HEALING] Learning loop started (4-hour intervals)")
    
    def stop(self):
        """Stop the learning loop daemon"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        print("🔄 [SELF-HEALING] Learning loop stopped")
    
    def _run_loop(self):
        """Main loop: run analysis every 4 hours"""
        while self.running:
            try:
                now = time.time()
                time_since_last = now - self.last_analysis_ts
                
                if time_since_last >= ANALYSIS_INTERVAL_SECONDS:
                    print(f"🔄 [SELF-HEALING] Starting learning loop analysis...")
                    results = self.analyze_shadow_vs_live()
                    self._save_results(results)
                    self.last_analysis_ts = now
                    print(f"✅ [SELF-HEALING] Analysis complete: {results.total_net_benefit:.2f} net benefit")
                    
                    # [BIG ALPHA PHASE 5] Analyze Slippage Audit and auto-update FeeAwareGate thresholds
                    try:
                        print(f"🔄 [SELF-HEALING] Analyzing Slippage Audit...")
                        self._analyze_slippage_and_update_fee_gates()
                    except Exception as e:
                        print(f"⚠️ [SLIPPAGE-AUDIT] Error during slippage analysis: {e}")
                        import traceback
                        traceback.print_exc()
                    
                    # [FINAL ALPHA] Time-Regime Optimizer - Analyze shadow trades and optimize golden hours
                    try:
                        print(f"🔄 [SELF-HEALING] Running Time-Regime Optimization...")
                        from src.time_regime_optimizer import get_time_regime_optimizer
                        optimizer = get_time_regime_optimizer()
                        opt_result = optimizer.optimize_golden_hours()
                        if opt_result.get("success") and opt_result.get("new_windows"):
                            print(f"✅ [TIME-REGIME] Optimized golden hours: Added {len(opt_result['new_windows'])} windows")
                    except Exception as e:
                        print(f"⚠️ [TIME-REGIME] Error during time-regime optimization: {e}")
                        import traceback
                        traceback.print_exc()
                    
                    # [FINAL ALPHA] Execution Post-Mortem Tuning - Adjust marketable limit offset based on fill failure rate
                    try:
                        print(f"🔄 [SELF-HEALING] Analyzing fill failure rate for execution tuning...")
                        from src.trade_execution import analyze_fill_failure_rate, get_marketable_limit_offset_bps, MARKETABLE_LIMIT_OFFSET_BPS, MARKETABLE_LIMIT_OFFSET_BPS_MAX
                        from pathlib import Path
                        from src.infrastructure.path_registry import PathRegistry
                        import json
                        
                        fill_analysis = analyze_fill_failure_rate(hours=24)
                        if not fill_analysis.get("error") and fill_analysis.get("should_increase_offset"):
                            current_offset = get_marketable_limit_offset_bps()
                            if current_offset < MARKETABLE_LIMIT_OFFSET_BPS_MAX:
                                # Increase offset to 0.12% (12 bps)
                                config_path = Path(PathRegistry.get_path("feature_store", "trade_execution_config.json"))
                                config_path.parent.mkdir(parents=True, exist_ok=True)
                                
                                config = {}
                                if config_path.exists():
                                    with open(config_path, 'r') as f:
                                        config = json.load(f)
                                
                                config["marketable_limit_offset_bps"] = MARKETABLE_LIMIT_OFFSET_BPS_MAX
                                config["last_updated"] = datetime.utcnow().isoformat() + "Z"
                                config["reason"] = f"Fill failure rate {fill_analysis.get('estimated_failure_rate_pct', 0):.1f}% > 20% during TRUE TREND"
                                
                                with open(config_path, 'w') as f:
                                    json.dump(config, f, indent=2)
                                
                                print(f"✅ [EXECUTION-TUNING] Increased marketable limit offset to {MARKETABLE_LIMIT_OFFSET_BPS_MAX} bps (0.12%) due to high fill failure rate")
                        elif not fill_analysis.get("error") and fill_analysis.get("estimated_failure_rate_pct", 0) < 10.0:
                            # If failure rate is low, consider reducing offset back to default
                            current_offset = get_marketable_limit_offset_bps()
                            if current_offset > MARKETABLE_LIMIT_OFFSET_BPS:
                                config_path = Path(PathRegistry.get_path("feature_store", "trade_execution_config.json"))
                                if config_path.exists():
                                    # Only reduce if it's been increased before
                                    with open(config_path, 'r') as f:
                                        config = json.load(f)
                                    if config.get("marketable_limit_offset_bps", MARKETABLE_LIMIT_OFFSET_BPS) > MARKETABLE_LIMIT_OFFSET_BPS:
                                        config["marketable_limit_offset_bps"] = MARKETABLE_LIMIT_OFFSET_BPS
                                        config["last_updated"] = datetime.utcnow().isoformat() + "Z"
                                        config["reason"] = f"Fill failure rate {fill_analysis.get('estimated_failure_rate_pct', 0):.1f}% < 10% - reducing to default"
                                        
                                        with open(config_path, 'w') as f:
                                            json.dump(config, f, indent=2)
                                        
                                        print(f"✅ [EXECUTION-TUNING] Reduced marketable limit offset back to {MARKETABLE_LIMIT_OFFSET_BPS} bps (0.05%) - fill failure rate improved")
                    except Exception as e:
                        print(f"⚠️ [EXECUTION-TUNING] Error during fill failure analysis: {e}")
                        import traceback
                        traceback.print_exc()
                    
                    # [BIG ALPHA] Also evaluate symbol probation (Component 6)
                    try:
                        from src.symbol_probation_state_machine import get_probation_machine
                        probation_machine = get_probation_machine()
                        probation_machine.evaluate_all_symbols()
                    except Exception as e:
                        print(f"⚠️ [PROBATION] Error during evaluation: {e}")
                    
                    # [FINAL ALPHA PHASE 7] Hard Max Drawdown Guard (Kill-Switch)
                    # If portfolio loses >5% in 24h, force-close all positions and hard-block entries for 12h
                    try:
                        print(f"🔄 [SELF-HEALING] Checking portfolio Max Drawdown...")
                        self._check_max_drawdown_kill_switch()
                    except Exception as e:
                        print(f"⚠️ [MAX-DRAWDOWN-GUARD] Error during drawdown check: {e}")
                        import traceback
                        traceback.print_exc()
                
                # [BIG ALPHA PHASE 4] Hyperparameter Optimization (every 12 hours)
                time_since_last_hyperparam = now - self.last_hyperparam_optimization_ts
                if time_since_last_hyperparam >= HYPERPARAM_OPTIMIZATION_INTERVAL_SECONDS:
                    print(f"🔄 [HYPERPARAM-OPT] Starting Whale CVD threshold optimization...")
                    try:
                        self._optimize_whale_cvd_threshold()
                        self.last_hyperparam_optimization_ts = now
                    except Exception as e:
                        print(f"⚠️ [HYPERPARAM-OPT] Error during threshold optimization: {e}")
                        import traceback
                        traceback.print_exc()
                
                # Sleep until next interval (use the shorter of the two intervals)
                next_analysis = ANALYSIS_INTERVAL_SECONDS - time_since_last
                next_hyperparam = HYPERPARAM_OPTIMIZATION_INTERVAL_SECONDS - time_since_last_hyperparam
                sleep_time = min(next_analysis, next_hyperparam, 300)  # Check every 5 minutes max
                if sleep_time > 0:
                    time.sleep(sleep_time)
            except Exception as e:
                print(f"⚠️ [SELF-HEALING] Error in learning loop: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(300)  # Wait 5 minutes before retry
    
    def analyze_shadow_vs_live(self) -> LearningLoopResults:
        """
        Compare shadow trades vs live trades from the last 4 hours.
        
        Returns:
            LearningLoopResults with guard effectiveness and recommendations
        """
        window_end = datetime.utcnow()
        window_start = window_end - timedelta(hours=ANALYSIS_WINDOW_HOURS)
        
        # Load shadow trade outcomes
        shadow_trades = self._load_shadow_trades(window_start, window_end)
        
        # Load live trades (closed positions)
        live_trades = self._load_live_trades(window_start, window_end)
        
        # Analyze guard effectiveness
        guard_effectiveness = self._analyze_guard_effectiveness(shadow_trades, live_trades)
        
        # Generate recommendations
        recommendations = self._generate_recommendations(guard_effectiveness)
        
        # Calculate total net benefit
        total_net_benefit = sum(g.net_benefit for g in guard_effectiveness.values())
        
        return LearningLoopResults(
            timestamp=window_end.isoformat(),
            window_start=window_start.isoformat(),
            window_end=window_end.isoformat(),
            shadow_trades_analyzed=len(shadow_trades),
            live_trades_analyzed=len(live_trades),
            guard_effectiveness={k: asdict(v) for k, v in guard_effectiveness.items()},
            recommendations=recommendations,
            total_net_benefit=total_net_benefit
        )
    
    def _load_shadow_trades(self, window_start: datetime, window_end: datetime) -> List[Dict]:
        """Load shadow trade outcomes from the analysis window"""
        shadow_trades = []
        
        shadow_log_path = LOGS / "shadow_trade_outcomes.jsonl"
        if not shadow_log_path.exists():
            return shadow_trades
        
        try:
            with open(shadow_log_path, "r") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        trade = json.loads(line)
                        trade_ts = datetime.fromisoformat(trade.get("timestamp", "").replace("Z", "+00:00"))
                        
                        if window_start <= trade_ts <= window_end:
                            shadow_trades.append(trade)
                    except (json.JSONDecodeError, ValueError, KeyError):
                        continue
        except Exception as e:
            print(f"⚠️ [SELF-HEALING] Error loading shadow trades: {e}")
        
        return shadow_trades
    
    def _load_live_trades(self, window_start: datetime, window_end: datetime) -> List[Dict]:
        """Load live (closed) trades from the analysis window"""
        live_trades = []
        
        try:
            # Load from positions_futures.json
            positions_path = Path("logs/positions_futures.json")
            if DR:
                positions_path = Path(DR.get_path("positions_futures"))
            
            if not positions_path.exists():
                return live_trades
            
            with open(positions_path, "r") as f:
                positions = json.load(f)
            
            closed_positions = positions.get("closed_positions", [])
            
            for pos in closed_positions:
                try:
                    # Parse closed timestamp
                    closed_at = pos.get("closed_at") or pos.get("opened_at")
                    if not closed_at:
                        continue
                    
                    # Handle different timestamp formats
                    if isinstance(closed_at, str):
                        try:
                            trade_ts = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
                        except ValueError:
                            # Try parsing as epoch
                            if "." in closed_at:
                                trade_ts = datetime.fromtimestamp(float(closed_at))
                            else:
                                continue
                    elif isinstance(closed_at, (int, float)):
                        trade_ts = datetime.fromtimestamp(closed_at)
                    else:
                        continue
                    
                    if window_start <= trade_ts <= window_end:
                        live_trades.append(pos)
                except (ValueError, KeyError, TypeError):
                    continue
        except Exception as e:
            print(f"⚠️ [SELF-HEALING] Error loading live trades: {e}")
        
        return live_trades
    
    def _analyze_guard_effectiveness(
        self, 
        shadow_trades: List[Dict], 
        live_trades: List[Dict]
    ) -> Dict[str, GuardEffectiveness]:
        """
        Analyze guard effectiveness by comparing shadow vs live trades.
        
        For each guard:
        - Count how many trades it blocked
        - Calculate P&L of blocked trades (from shadow outcomes)
        - Count how many trades it allowed
        - Calculate P&L of allowed trades (from live outcomes)
        - Calculate net benefit
        """
        guard_stats = defaultdict(lambda: GuardEffectiveness(guard_name=""))
        
        # Process shadow trades (blocked trades)
        for shadow_trade in shadow_trades:
            blocker = shadow_trade.get("blocker_component") or shadow_trade.get("original_decision") or shadow_trade.get("reason") or shadow_trade.get("event", "unknown")
            if blocker == "APPROVED":
                continue  # Skip approved shadow trades
            
            # [BIG ALPHA PHASE 2 & 3] Map Macro Guard events to guard names
            guard_name_map = {
                "LIQ_WALL_CONFLICT": "Liquidation Wall Guard",
                "LONG_TRAP_DETECTED": "Long Trap Guard",
                "WHALE_CONFLICT": "Whale CVD Guard",
                "TAKER_AGGRESSION_BLOCK": "Taker Aggression Guard",
                "WALL_RESISTANCE_BLOCK": "Orderbook Wall Guard"
            }
            
            guard_name = guard_name_map.get(blocker, blocker.replace("BLOCKED_", "").replace("_", " ").title())
            if not guard_stats[guard_name].guard_name:
                guard_stats[guard_name].guard_name = guard_name
            
            guard_stats[guard_name].blocks_count += 1
            
            # Get P&L from shadow outcome
            pnl = shadow_trade.get("final_pnl_usd", 0.0) or shadow_trade.get("pnl", 0.0) or 0.0
            
            if pnl < 0:
                guard_stats[guard_name].blocks_avoided_losses += abs(pnl)  # Saved money
            else:
                guard_stats[guard_name].blocks_missed_profits += pnl  # Missed profits
        
        # Process live trades (allowed trades)
        for live_trade in live_trades:
            # Extract guard information from trade metadata
            # Check if trade mentions which guards passed
            guard_info = live_trade.get("gate_attribution", {})
            guards_passed = []
            
            # Infer guards from gate_attribution
            if guard_info.get("intel_reason"):
                guards_passed.append("intelligence_gate")
            if guard_info.get("streak_reason"):
                guards_passed.append("streak_filter")
            if guard_info.get("regime_reason"):
                guards_passed.append("regime_filter")
            if guard_info.get("fee_reason"):
                guards_passed.append("fee_gate")
            if guard_info.get("roi_reason"):
                guards_passed.append("roi_gate")
            
            if not guards_passed:
                guards_passed = ["all_guards_passed"]  # Default if unknown
            
            # Get P&L
            pnl = live_trade.get("pnl", 0.0) or live_trade.get("net_pnl", 0.0) or live_trade.get("profit_usd", 0.0) or 0.0
            
            for guard_name in guards_passed:
                guard_name_display = guard_name.replace("_", " ").title()
                if not guard_stats[guard_name_display].guard_name:
                    guard_stats[guard_name_display].guard_name = guard_name_display
                
                guard_stats[guard_name_display].allows_count += 1
                
                if pnl > 0:
                    guard_stats[guard_name_display].allows_profits += pnl
                else:
                    guard_stats[guard_name_display].allows_losses += abs(pnl)
        
        # Calculate net benefit and effectiveness scores
        for guard_name, stats in guard_stats.items():
            # Net benefit = avoided losses + profits from allows - missed profits - losses from allows
            stats.net_benefit = (
                stats.blocks_avoided_losses + 
                stats.allows_profits - 
                stats.blocks_missed_profits - 
                stats.allows_losses
            )
            
            # Effectiveness score: higher is better (0-1 scale)
            total_impact = abs(stats.net_benefit)
            if total_impact > 0:
                # Normalize to 0-1, with positive net benefit = high score
                stats.effectiveness_score = min(1.0, max(0.0, 0.5 + (stats.net_benefit / (total_impact * 2))))
            else:
                stats.effectiveness_score = 0.5  # Neutral
        
        return dict(guard_stats)
    
    def _generate_recommendations(
        self, 
        guard_effectiveness: Dict[str, GuardEffectiveness]
    ) -> List[Dict[str, Any]]:
        """Generate recommendations based on guard effectiveness"""
        recommendations = []
        
        # [BIG ALPHA PHASE 3] Analyze Max Pain Magnet target hits
        try:
            from src.position_manager import load_futures_positions
            positions_data = load_futures_positions()
            closed_trades = positions_data.get("closed_positions", [])
            
            # Analyze TRUE TREND trades with Max Pain targets
            max_pain_hits = 0
            max_pain_total = 0
            max_pain_aligned_pnl = 0.0
            max_pain_missed_pnl = 0.0
            
            for trade in closed_trades[-100:]:  # Last 100 trades
                max_pain_at_entry = trade.get("max_pain_at_entry", 0)
                entry_price = trade.get("entry_price", 0)
                exit_price = trade.get("exit_price", trade.get("close_price", 0))
                pnl = trade.get("pnl", trade.get("net_pnl", 0)) or 0
                is_true_trend = trade.get("is_true_trend", False)
                
                if max_pain_at_entry > 0 and entry_price > 0 and exit_price > 0 and is_true_trend:
                    max_pain_total += 1
                    # Check if price hit Max Pain (within 0.5% tolerance)
                    direction = trade.get("direction", "LONG")
                    if direction == "LONG":
                        hit_max_pain = exit_price >= max_pain_at_entry * 0.995  # Within 0.5% below
                    else:
                        hit_max_pain = exit_price <= max_pain_at_entry * 1.005  # Within 0.5% above
                    
                    if hit_max_pain:
                        max_pain_hits += 1
                        max_pain_aligned_pnl += pnl
                    else:
                        max_pain_missed_pnl += pnl
            
            if max_pain_total > 0:
                hit_rate = max_pain_hits / max_pain_total
                if hit_rate > 0.6:  # 60%+ hit rate = increase conviction
                    recommendations.append({
                        "type": "increase_conviction",
                        "feature": "max_pain_magnet",
                        "reason": f"Max Pain target hit rate {hit_rate:.1%} ({max_pain_hits}/{max_pain_total}) - Magnet effect confirmed",
                        "suggestion": "Increase conviction multiplier for Magnet-aligned trades",
                        "severity": "low",
                        "stats": {
                            "hit_rate": hit_rate,
                            "aligned_pnl": max_pain_aligned_pnl,
                            "missed_pnl": max_pain_missed_pnl
                        }
                    })
        except Exception as e:
            print(f"⚠️ [SELF-HEALING] Error analyzing Max Pain targets: {e}")
        
        for guard_name, stats in guard_effectiveness.items():
            # If guard has negative net benefit, suggest review
            if stats.net_benefit < -10.0:  # Threshold: -$10
                recommendations.append({
                    "type": "review_guard",
                    "guard": guard_name,
                    "reason": f"Negative net benefit: ${stats.net_benefit:.2f}",
                    "suggestion": "Consider adjusting parameters or disabling",
                    "severity": "high" if stats.net_benefit < -50.0 else "medium"
                })
            
            # If guard is blocking too many profitable trades
            if stats.blocks_missed_profits > 50.0 and stats.blocks_count > 5:
                recommendations.append({
                    "type": "loosen_guard",
                    "guard": guard_name,
                    "reason": f"Missing ${stats.blocks_missed_profits:.2f} in profits from {stats.blocks_count} blocked trades",
                    "suggestion": "Consider relaxing guard thresholds",
                    "severity": "medium"
                })
            
            # If guard is allowing too many losing trades
            if stats.allows_losses > 50.0 and stats.allows_count > 5:
                recommendations.append({
                    "type": "tighten_guard",
                    "guard": guard_name,
                    "reason": f"Allowing ${stats.allows_losses:.2f} in losses from {stats.allows_count} trades",
                    "suggestion": "Consider tightening guard thresholds",
                    "severity": "medium"
                })
        
        return recommendations
    
    def _save_results(self, results: LearningLoopResults):
        """Save analysis results to log and state file"""
        try:
            # Append to JSONL log
            with open(LEARNING_LOOP_LOG, "a") as f:
                f.write(json.dumps(asdict(results)) + "\n")
            
            # Update state file (latest analysis)
            state = {
                "last_analysis_ts": time.time(),
                "last_analysis": asdict(results)
            }
            with open(LEARNING_LOOP_STATE, "w") as f:
                json.dump(state, f, indent=2)
            
            # Log key findings
            print(f"📊 [SELF-HEALING] Analysis Summary:")
            print(f"   Shadow trades: {results.shadow_trades_analyzed}")
            print(f"   Live trades: {results.live_trades_analyzed}")
            print(f"   Total net benefit: ${results.total_net_benefit:.2f}")
            print(f"   Recommendations: {len(results.recommendations)}")
            
            for rec in results.recommendations:
                print(f"   💡 {rec['type']}: {rec['guard']} - {rec['reason']}")
        
        except Exception as e:
            print(f"⚠️ [SELF-HEALING] Error saving results: {e}")
    
    def _optimize_whale_cvd_threshold(self):
        """
        [BIG ALPHA PHASE 4] Hyperparameter Optimizer for Whale CVD Threshold.
        
        Analyzes last 50 trades and simulates what-if P&L if threshold was tightened or loosened.
        Automatically adjusts WHALE_INTENT_FILTER threshold based on Shadow P&L.
        """
        try:
            from src.intent_intelligence_guards import get_whale_cvd_intent, save_whale_cvd_threshold, load_whale_cvd_threshold
            from src.position_manager import load_futures_positions
            
            # Get last N closed trades
            positions_data = load_futures_positions()
            closed_trades = positions_data.get("closed_positions", [])
            recent_trades = closed_trades[-HYPERPARAM_TRADE_COUNT:]
            
            if len(recent_trades) < 10:  # Need at least 10 trades for meaningful optimization
                print(f"⚠️ [HYPERPARAM-OPT] Insufficient trades ({len(recent_trades)} < 10) for threshold optimization")
                return
            
            # Current threshold
            current_threshold = load_whale_cvd_threshold()
            
            # Test different thresholds: -20%, -10%, 0%, +10%, +20%
            test_thresholds = [
                current_threshold * 0.8,  # -20% (tighter - blocks more)
                current_threshold * 0.9,  # -10%
                current_threshold,        # Current
                current_threshold * 1.1,  # +10% (looser - blocks less)
                current_threshold * 1.2   # +20%
            ]
            
            best_threshold = current_threshold
            best_pnl = float('-inf')
            threshold_results = []
            
            print(f"🔍 [HYPERPARAM-OPT] Testing {len(test_thresholds)} threshold values on {len(recent_trades)} trades...")
            
            for test_threshold in test_thresholds:
                simulated_pnl = 0.0
                blocked_count = 0
                allowed_count = 0
                
                # Simulate what-if for each trade
                for trade in recent_trades:
                    symbol = trade.get("symbol", "")
                    direction = trade.get("direction", trade.get("side", ""))
                    pnl = trade.get("pnl", trade.get("net_pnl", 0)) or 0
                    
                    if not symbol or not direction:
                        continue
                    
                    # Check if trade would have been blocked with this threshold
                    try:
                        whale_data = get_whale_cvd_intent(symbol, test_threshold)
                        whale_direction = whale_data.get("whale_cvd_direction", "NEUTRAL")
                        
                        # Check divergence
                        would_block = False
                        if direction == "LONG" and whale_direction == "SHORT":
                            would_block = True
                        elif direction == "SHORT" and whale_direction == "LONG":
                            would_block = True
                        
                        if would_block:
                            blocked_count += 1
                            # Use shadow P&L if available, otherwise use actual P&L (conservative)
                            simulated_pnl += 0  # Blocked = no P&L (could use shadow P&L here)
                        else:
                            allowed_count += 1
                            simulated_pnl += pnl
                    except Exception:
                        # If we can't check, assume trade would be allowed (conservative)
                        allowed_count += 1
                        simulated_pnl += pnl
                
                threshold_results.append({
                    "threshold": test_threshold,
                    "simulated_pnl": simulated_pnl,
                    "blocked_count": blocked_count,
                    "allowed_count": allowed_count
                })
                
                if simulated_pnl > best_pnl:
                    best_pnl = simulated_pnl
                    best_threshold = test_threshold
            
            # Only update if improvement is significant (>$50)
            improvement = best_pnl - threshold_results[2]["simulated_pnl"]  # Compare to current threshold result
            
            if improvement > 50.0 and best_threshold != current_threshold:
                print(f"✅ [HYPERPARAM-OPT] Optimal threshold: ${best_threshold:,.0f} (improvement: ${improvement:.2f})")
                save_whale_cvd_threshold(best_threshold)
            else:
                print(f"ℹ️ [HYPERPARAM-OPT] Current threshold optimal (${current_threshold:,.0f}, improvement: ${improvement:.2f})")
            
            # Log optimization results
            opt_log = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "trades_analyzed": len(recent_trades),
                "current_threshold": current_threshold,
                "best_threshold": best_threshold,
                "improvement": improvement,
                "threshold_results": threshold_results
            }
            
            opt_log_path = LOGS / "whale_cvd_threshold_optimization.jsonl"
            with open(opt_log_path, "a") as f:
                f.write(json.dumps(opt_log) + "\n")
                
        except Exception as e:
            print(f"⚠️ [HYPERPARAM-OPT] Error optimizing Whale CVD threshold: {e}")
            import traceback
            traceback.print_exc()
    
    def _analyze_slippage_and_update_fee_gates(self):
        """
        [BIG ALPHA PHASE 5] Analyze Slippage Audit and auto-update FeeAwareGate thresholds.
        
        Every 4 hours, analyze slippage from executed_trades.jsonl.
        If slippage on a symbol exceeds 5bps, automatically update FeeAwareGate threshold
        in configs/trading_config.json for that symbol to prevent "negative dollar wins".
        """
        try:
            from src.trade_execution import EXECUTED_TRADES_LOG
            import json
            from pathlib import Path
            
            # Load all recent executions and group by symbol
            cutoff_ts = time.time() - (24 * 3600)  # Last 24 hours
            symbol_slippages = defaultdict(list)
            
            if not EXECUTED_TRADES_LOG.exists():
                print(f"   [SLIPPAGE-AUDIT] No execution log found: {EXECUTED_TRADES_LOG}")
                return
            
            # Read all executions and group by symbol
            with open(EXECUTED_TRADES_LOG, "r") as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        if entry.get("ts", 0) >= cutoff_ts:
                            symbol = entry.get("symbol")
                            slippage_bps = entry.get("slippage_bps")
                            if symbol and slippage_bps is not None:
                                symbol_slippages[symbol].append(abs(slippage_bps))  # Use absolute slippage
                    except:
                        continue
            
            if not symbol_slippages:
                print(f"   [SLIPPAGE-AUDIT] No recent execution data found")
                return
            
            # Load trading_config.json
            config_path = Path("configs/trading_config.json")
            if not config_path.exists():
                print(f"   [SLIPPAGE-AUDIT] Config file not found: {config_path}")
                return
            
            with open(config_path, 'r') as f:
                trading_config = json.load(f)
            
            # Ensure per_symbol_fee_gates exists
            if "per_symbol_fee_gates" not in trading_config:
                trading_config["per_symbol_fee_gates"] = {}
            
            # Check each symbol's slippage and update thresholds
            updates_made = False
            for symbol, slippages in symbol_slippages.items():
                if not slippages:
                    continue
                
                avg_slippage = sum(slippages) / len(slippages)
                exceeding_5bps_count = sum(1 for s in slippages if s > 5.0)
                exceeding_5bps_pct = (exceeding_5bps_count / len(slippages)) * 100
                
                # If average slippage > 5bps OR >20% of trades exceed 5bps, tighten threshold
                if avg_slippage > 5.0 or exceeding_5bps_pct > 20.0:
                    # Get current threshold for this symbol (default: 1.2 = MIN_BUFFER_MULTIPLIER)
                    symbol_config = trading_config["per_symbol_fee_gates"].get(symbol, {})
                    current_multiplier = symbol_config.get("min_buffer_multiplier", 1.2)
                    
                    # Increase multiplier by 0.1 (tightens threshold by ~8%)
                    new_multiplier = min(2.0, current_multiplier + 0.1)  # Cap at 2.0
                    
                    if new_multiplier != current_multiplier:
                        trading_config["per_symbol_fee_gates"][symbol] = {
                            "min_buffer_multiplier": new_multiplier,
                            "last_updated": datetime.utcnow().isoformat(),
                            "update_reason": f"Slippage audit: avg={avg_slippage:.2f}bps, exceeding_5bps={exceeding_5bps_pct:.1f}%",
                            "avg_slippage_bps": avg_slippage,
                            "trade_count": len(slippages)
                        }
                        updates_made = True
                        print(f"   ⚠️ [SLIPPAGE-AUDIT] {symbol}: Avg slippage {avg_slippage:.2f}bps > 5bps - Tightening threshold: {current_multiplier:.2f} → {new_multiplier:.2f}")
                else:
                    # If slippage is good, we can gradually relax (but not below 1.2)
                    symbol_config = trading_config["per_symbol_fee_gates"].get(symbol, {})
                    current_multiplier = symbol_config.get("min_buffer_multiplier", 1.2)
                    
                    # Only relax if it was previously tightened (above 1.2)
                    if current_multiplier > 1.2 and avg_slippage < 3.0 and exceeding_5bps_pct < 10.0:
                        new_multiplier = max(1.2, current_multiplier - 0.05)  # Gradually relax
                        if new_multiplier != current_multiplier:
                            trading_config["per_symbol_fee_gates"][symbol] = {
                                "min_buffer_multiplier": new_multiplier,
                                "last_updated": datetime.utcnow().isoformat(),
                                "update_reason": f"Slippage improved: avg={avg_slippage:.2f}bps < 3bps - Relaxing threshold",
                                "avg_slippage_bps": avg_slippage,
                                "trade_count": len(slippages)
                            }
                            updates_made = True
                            print(f"   ✅ [SLIPPAGE-AUDIT] {symbol}: Slippage improved ({avg_slippage:.2f}bps) - Relaxing threshold: {current_multiplier:.2f} → {new_multiplier:.2f}")
            
            # Save updated config if changes were made
            if updates_made:
                # Atomic write
                tmp_path = config_path.with_suffix('.tmp')
                with open(tmp_path, 'w') as f:
                    json.dump(trading_config, f, indent=2)
                tmp_path.replace(config_path)
                print(f"   ✅ [SLIPPAGE-AUDIT] Updated FeeAwareGate thresholds for {len([s for s in symbol_slippages.keys() if s in trading_config['per_symbol_fee_gates']])} symbol(s)")
            else:
                print(f"   ✅ [SLIPPAGE-AUDIT] All symbols within acceptable slippage range (no updates needed)")
                
        except Exception as e:
            print(f"   ⚠️ [SLIPPAGE-AUDIT] Error in slippage analysis: {e}")
            import traceback
            traceback.print_exc()
    
    def _check_max_drawdown_kill_switch(self):
        """
        [FINAL ALPHA PHASE 7] Hard Max Drawdown Guard (Kill-Switch)
        Monitor Portfolio-Level Drawdown (MDD). If portfolio loses >5% in 24h,
        Force-Close all positions and Hard-Block all new entries for 12 hours.
        """
        MAX_DRAWDOWN_THRESHOLD = 0.05  # 5% drawdown threshold
        BLOCK_DURATION_HOURS = 12  # Block new entries for 12 hours
        
        try:
            from src.data_registry import DataRegistry as DR
            
            # Calculate 24-hour portfolio drawdown
            positions_data = DR.read_json(DR.POSITIONS_FUTURES)
            if not positions_data:
                return
            
            closed_positions = positions_data.get("closed_positions", [])
            if not closed_positions:
                return
            
            # Calculate starting capital (from wallet balance calculation)
            STARTING_CAPITAL = 10000.0
            
            # Get portfolio value 24 hours ago and now
            cutoff_time = datetime.utcnow() - timedelta(hours=24)
            
            # Calculate cumulative P&L from all closed positions
            total_pnl_now = 0.0
            total_pnl_24h_ago = 0.0
            
            for pos in closed_positions:
                pnl = float(pos.get("pnl", pos.get("net_pnl", pos.get("realized_pnl", 0))) or 0)
                total_pnl_now += pnl
                
                # Check if closed before 24h ago
                closed_at = pos.get("closed_at")
                if closed_at:
                    try:
                        if isinstance(closed_at, str):
                            closed_dt = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
                        else:
                            closed_dt = datetime.fromtimestamp(closed_at)
                        
                        if closed_dt < cutoff_time:
                            total_pnl_24h_ago += pnl
                    except:
                        pass
            
            # Calculate portfolio values
            portfolio_value_now = STARTING_CAPITAL + total_pnl_now
            portfolio_value_24h_ago = STARTING_CAPITAL + total_pnl_24h_ago
            
            # Calculate drawdown over 24h
            if portfolio_value_24h_ago > 0:
                drawdown_pct = (portfolio_value_24h_ago - portfolio_value_now) / portfolio_value_24h_ago
            else:
                drawdown_pct = 0.0
            
            # Check if drawdown exceeds threshold
            if drawdown_pct > MAX_DRAWDOWN_THRESHOLD:
                print(f"🚨 [MAX-DRAWDOWN-GUARD] CRITICAL: Portfolio drawdown {drawdown_pct*100:.2f}% > {MAX_DRAWDOWN_THRESHOLD*100:.2f}% threshold")
                print(f"   Portfolio 24h ago: ${portfolio_value_24h_ago:,.2f}, Now: ${portfolio_value_now:,.2f}")
                
                # Check if kill switch was already triggered recently (within block duration)
                kill_switch_state_path = FEATURE_STORE / "max_drawdown_kill_switch_state.json"
                kill_switch_state = {}
                
                if kill_switch_state_path.exists():
                    try:
                        with open(kill_switch_state_path, 'r') as f:
                            kill_switch_state = json.load(f)
                    except:
                        pass
                
                last_trigger_time = kill_switch_state.get("last_triggered")
                if last_trigger_time:
                    try:
                        last_trigger_dt = datetime.fromisoformat(last_trigger_time.replace("Z", "+00:00"))
                        hours_since_trigger = (datetime.utcnow() - last_trigger_dt).total_seconds() / 3600
                        
                        if hours_since_trigger < BLOCK_DURATION_HOURS:
                            # Still in block period
                            remaining_hours = BLOCK_DURATION_HOURS - hours_since_trigger
                            print(f"   ℹ️  Kill switch already active (triggered {hours_since_trigger:.1f}h ago, {remaining_hours:.1f}h remaining)")
                            return
                    except:
                        pass
                
                # Trigger kill switch: Force-close all positions
                print(f"🛑 [MAX-DRAWDOWN-GUARD] Triggering KILL SWITCH: Force-closing all positions...")
                
                try:
                    from src.position_manager import get_open_futures_positions, close_futures_position
                    from src.blofin_futures_client import BlofinFuturesClient
                    
                    open_positions = get_open_futures_positions()
                    if open_positions:
                        client = BlofinFuturesClient()
                        closed_count = 0
                        
                        for pos in open_positions:
                            symbol = pos.get("symbol")
                            strategy = pos.get("strategy", "unknown")
                            direction = pos.get("direction", "LONG")
                            
                            try:
                                # Get current market price
                                mark_price = client.get_mark_price(symbol)
                                
                                # Force close (bypass hold time)
                                success = close_futures_position(
                                    symbol=symbol,
                                    strategy=strategy,
                                    direction=direction,
                                    exit_price=mark_price,
                                    reason="MAX_DRAWDOWN_KILL_SWITCH",
                                    funding_fees=0,
                                    force_close=True
                                )
                                
                                if success:
                                    closed_count += 1
                                    print(f"   ✅ Force-closed {symbol} {direction} @ ${mark_price:.2f}")
                            except Exception as e:
                                print(f"   ❌ Failed to close {symbol}: {e}")
                        
                        print(f"   ✅ [KILL-SWITCH] Force-closed {closed_count}/{len(open_positions)} positions")
                    else:
                        print(f"   ℹ️  No open positions to close")
                except Exception as e:
                    print(f"   ❌ [KILL-SWITCH] Error force-closing positions: {e}")
                    import traceback
                    traceback.print_exc()
                
                # Save kill switch state (block new entries for 12 hours)
                kill_switch_state = {
                    "last_triggered": datetime.utcnow().isoformat() + "Z",
                    "drawdown_pct": drawdown_pct,
                    "portfolio_value_before": portfolio_value_24h_ago,
                    "portfolio_value_now": portfolio_value_now,
                    "blocked_until": (datetime.utcnow() + timedelta(hours=BLOCK_DURATION_HOURS)).isoformat() + "Z",
                    "positions_closed": len(open_positions) if 'open_positions' in locals() else 0
                }
                
                kill_switch_state_path.parent.mkdir(parents=True, exist_ok=True)
                with open(kill_switch_state_path, 'w') as f:
                    json.dump(kill_switch_state, f, indent=2)
                
                print(f"   🚫 [KILL-SWITCH] New entries BLOCKED for {BLOCK_DURATION_HOURS} hours (until {kill_switch_state['blocked_until']})")
                
                # Log to signal_bus
                try:
                    from src.signal_bus import get_signal_bus
                    signal_bus = get_signal_bus()
                    signal_bus.emit_signal({
                        "event": "MAX_DRAWDOWN_KILL_SWITCH",
                        "drawdown_pct": drawdown_pct,
                        "portfolio_value_before": portfolio_value_24h_ago,
                        "portfolio_value_now": portfolio_value_now,
                        "blocked_until": kill_switch_state["blocked_until"],
                        "positions_closed": kill_switch_state["positions_closed"]
                    }, source="self_healing_learning_loop")
                except Exception as e:
                    print(f"   ⚠️ Failed to log kill switch to signal_bus: {e}")
            else:
                # Drawdown is acceptable, check if we can clear any existing block
                kill_switch_state_path = FEATURE_STORE / "max_drawdown_kill_switch_state.json"
                if kill_switch_state_path.exists():
                    try:
                        with open(kill_switch_state_path, 'r') as f:
                            kill_switch_state = json.load(f)
                        
                        blocked_until = kill_switch_state.get("blocked_until")
                        if blocked_until:
                            blocked_until_dt = datetime.fromisoformat(blocked_until.replace("Z", "+00:00"))
                            if datetime.utcnow() > blocked_until_dt:
                                # Block period expired, clear it
                                kill_switch_state["blocked_until"] = None
                                kill_switch_state["block_cleared_at"] = datetime.utcnow().isoformat() + "Z"
                                with open(kill_switch_state_path, 'w') as f:
                                    json.dump(kill_switch_state, f, indent=2)
                                print(f"   ✅ [MAX-DRAWDOWN-GUARD] Block period expired - entries are now allowed again")
                    except:
                        pass
                
                # Log current drawdown (for dashboard)
                print(f"   ℹ️  [MAX-DRAWDOWN-GUARD] Portfolio drawdown: {drawdown_pct*100:.2f}% (threshold: {MAX_DRAWDOWN_THRESHOLD*100:.2f}%)")
                
        except Exception as e:
            print(f"   ⚠️ [MAX-DRAWDOWN-GUARD] Error in drawdown check: {e}")
            import traceback
            traceback.print_exc()
    
    def is_kill_switch_active(self) -> bool:
        """
        Check if kill switch is currently active (blocking new entries).
        
        Returns:
            True if entries are blocked, False otherwise
        """
        try:
            kill_switch_state_path = FEATURE_STORE / "max_drawdown_kill_switch_state.json"
            if not kill_switch_state_path.exists():
                return False
            
            with open(kill_switch_state_path, 'r') as f:
                kill_switch_state = json.load(f)
            
            blocked_until = kill_switch_state.get("blocked_until")
            if not blocked_until:
                return False
            
            blocked_until_dt = datetime.fromisoformat(blocked_until.replace("Z", "+00:00"))
            return datetime.utcnow() < blocked_until_dt
            
        except:
            return False


# Singleton instance
_learning_loop_instance = None


def get_learning_loop() -> SelfHealingLearningLoop:
    """Get singleton instance of learning loop"""
    global _learning_loop_instance
    if _learning_loop_instance is None:
        _learning_loop_instance = SelfHealingLearningLoop()
    return _learning_loop_instance


def start_learning_loop():
    """Start the learning loop daemon (called from main bot cycle)"""
    loop = get_learning_loop()
    loop.start()


def stop_learning_loop():
    """Stop the learning loop daemon"""
    loop = get_learning_loop()
    loop.stop()

