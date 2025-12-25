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
                    
                    # [BIG ALPHA] Also evaluate symbol probation (Component 6)
                    try:
                        from src.symbol_probation_state_machine import get_probation_machine
                        probation_machine = get_probation_machine()
                        probation_machine.evaluate_all_symbols()
                    except Exception as e:
                        print(f"⚠️ [PROBATION] Error during evaluation: {e}")
                else:
                    # Sleep until next interval
                    sleep_time = ANALYSIS_INTERVAL_SECONDS - time_since_last
                    time.sleep(min(sleep_time, 300))  # Check every 5 minutes max
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
            
            # [BIG ALPHA PHASE 2] Map Macro Guard events to guard names
            guard_name_map = {
                "LIQ_WALL_CONFLICT": "Liquidation Wall Guard",
                "LONG_TRAP_DETECTED": "Long Trap Guard",
                "WHALE_CONFLICT": "Whale CVD Guard"
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

