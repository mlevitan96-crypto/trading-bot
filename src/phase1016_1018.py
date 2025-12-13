"""
Phase 10.16-10.18: Final Institutional Enhancements
- 10.16: Meta-Expectancy Router (global capital routing based on expectancy buckets)
- 10.17: Adaptive Correlation Hedger (dynamic hedge positioning)
- 10.18: Autonomous Governance & Self-Healing (system monitoring and auto-repair)
"""

import time
import json
import os
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Optional, Tuple
from src.reentry_logger import get_arizona_time

# ======================================================================================
# Phase 10.16: Meta-Expectancy Router
# ======================================================================================

class Config1016:
    """Phase 10.16 Configuration"""
    # Bucket tiers based on expectancy metrics
    high_expectancy_threshold = 0.65  # WR >= 65% or Sharpe >= 1.5
    medium_expectancy_threshold = 0.50  # WR >= 50% or Sharpe >= 0.8
    
    # Capital routing multipliers
    high_bucket_multiplier = 1.5
    medium_bucket_multiplier = 1.0
    low_bucket_multiplier = 1.0  # No suppression (was 0.5)
    
    # Minimum samples required for bucket classification
    min_trades_for_classification = 10
    
    # Lookback windows
    win_rate_lookback_trades = 50
    sharpe_lookback_hours = 48
    
    # Decay for expectancy tracking (recent trades weighted higher)
    expectancy_decay_alpha = 0.95

class MetaExpectancyRouter:
    """
    Routes capital based on global expectancy analysis.
    Buckets are defined by (symbol, venue, strategy) combinations.
    """
    
    def __init__(self):
        self.bucket_metrics = {}  # (symbol, venue, strategy) -> metrics
        self.bucket_tiers = {}     # (symbol, venue, strategy) -> tier (high/medium/low)
        self.routing_weights = {}  # (symbol, venue, strategy) -> multiplier
        self.trade_history = []    # List of trade results
        self.last_route_ts = 0
        
    def on_trade_close(self, trade: Dict):
        """Update bucket metrics when trade closes"""
        symbol = trade.get("symbol")
        venue = trade.get("venue", "futures")
        strategy = trade.get("strategy", "unknown")
        bucket = (symbol, venue, strategy)
        
        # Record trade for this bucket
        self.trade_history.append({
            "bucket": bucket,
            "pnl_usd": float(trade.get("pnl_usd", 0)),
            "win": float(trade.get("pnl_usd", 0)) > 0,
            "ts": int(time.time())
        })
        
        # Update bucket metrics
        self._update_bucket_metrics(bucket)
    
    def _update_bucket_metrics(self, bucket: Tuple[str, str, str]):
        """Calculate win rate, avg P&L, and Sharpe for a bucket"""
        symbol, venue, strategy = bucket
        
        # Get trades for this bucket
        bucket_trades = [t for t in self.trade_history if t["bucket"] == bucket]
        
        if len(bucket_trades) < 3:
            return  # Not enough data
        
        # Calculate win rate (recent window)
        recent_trades = bucket_trades[-Config1016.win_rate_lookback_trades:]
        wins = sum(1 for t in recent_trades if t["win"])
        win_rate = wins / len(recent_trades) if recent_trades else 0.0
        
        # Calculate average P&L
        avg_pnl = sum(t["pnl_usd"] for t in recent_trades) / len(recent_trades) if recent_trades else 0.0
        
        # Calculate Sharpe (simplified: mean/std of P&L)
        pnls = [t["pnl_usd"] for t in recent_trades]
        mean_pnl = sum(pnls) / len(pnls) if pnls else 0
        std_pnl = (sum((x - mean_pnl) ** 2 for x in pnls) / len(pnls)) ** 0.5 if pnls else 1.0
        sharpe = mean_pnl / std_pnl if std_pnl > 0 else 0.0
        
        # Store metrics
        self.bucket_metrics[bucket] = {
            "win_rate": win_rate,
            "avg_pnl": avg_pnl,
            "sharpe": sharpe,
            "trade_count": len(bucket_trades),
            "updated_ts": int(time.time())
        }
    
    def route_tick(self):
        """Recompute bucket tiers and routing weights"""
        # Update tiers for all buckets
        for bucket, metrics in self.bucket_metrics.items():
            if metrics["trade_count"] < Config1016.min_trades_for_classification:
                tier = "low"  # Not enough data = conservative
            elif metrics["win_rate"] >= Config1016.high_expectancy_threshold or metrics["sharpe"] >= 1.5:
                tier = "high"
            elif metrics["win_rate"] >= Config1016.medium_expectancy_threshold or metrics["sharpe"] >= 0.8:
                tier = "medium"
            else:
                tier = "low"
            
            self.bucket_tiers[bucket] = tier
        
        # Assign routing weights based on tiers
        for bucket, tier in self.bucket_tiers.items():
            if tier == "high":
                self.routing_weights[bucket] = Config1016.high_bucket_multiplier
            elif tier == "medium":
                self.routing_weights[bucket] = Config1016.medium_bucket_multiplier
            else:
                self.routing_weights[bucket] = Config1016.low_bucket_multiplier
        
        self.last_route_ts = int(time.time())
        
        # Log routing results
        _log_event("phase1016_route_tick", {
            "bucket_count": len(self.bucket_tiers),
            "high_buckets": sum(1 for t in self.bucket_tiers.values() if t == "high"),
            "medium_buckets": sum(1 for t in self.bucket_tiers.values() if t == "medium"),
            "low_buckets": sum(1 for t in self.bucket_tiers.values() if t == "low")
        })
    
    def apply_bucket_weight(self, signal: Dict) -> float:
        """Apply bucket multiplier to planned size"""
        symbol = signal.get("symbol")
        venue = signal.get("venue", "futures")
        strategy = signal.get("strategy", "unknown")
        bucket = (symbol, venue, strategy)
        
        planned_size = signal.get("planned_size_usd", 0.0)
        
        # Get routing weight for this bucket
        multiplier = self.routing_weights.get(bucket, 1.0)
        
        adjusted_size = planned_size * multiplier
        
        # Log if routing occurred
        if multiplier != 1.0:
            tier = self.bucket_tiers.get(bucket, "unknown")
            _log_event("phase1016_routing_applied", {
                "symbol": symbol,
                "venue": venue,
                "strategy": strategy,
                "tier": tier,
                "multiplier": multiplier,
                "planned": planned_size,
                "adjusted": adjusted_size
            })
        
        return adjusted_size
    
    def get_state(self) -> Dict:
        """Get current state for dashboard"""
        return {
            "bucket_count": len(self.bucket_metrics),
            "tiers": {
                "high": sum(1 for t in self.bucket_tiers.values() if t == "high"),
                "medium": sum(1 for t in self.bucket_tiers.values() if t == "medium"),
                "low": sum(1 for t in self.bucket_tiers.values() if t == "low")
            },
            "routing_weights": {f"{b[0]}_{b[1]}_{b[2]}": w for b, w in self.routing_weights.items()},
            "last_route_ts": self.last_route_ts
        }

# ======================================================================================
# Phase 10.17: Adaptive Correlation Hedger
# ======================================================================================

class Config1017:
    """Phase 10.17 Configuration"""
    # Correlation thresholds
    high_correlation_threshold = 0.75
    moderate_correlation_threshold = 0.50
    
    # Hedge sizing
    max_hedge_ratio = 0.30  # Max 30% of cluster exposure
    min_hedge_size_usd = 100.0
    
    # Lookback for correlation calculation
    correlation_lookback_candles = 200

class CorrelationHedger:
    """
    Identifies correlated clusters and recommends hedge positions.
    """
    
    def __init__(self):
        self.correlation_matrix = {}
        self.active_hedges = []  # List of hedge recommendations
        self.cluster_exposures = {}
        self.last_hedge_ts = 0
    
    def hedge_tick(self):
        """Evaluate correlations and recommend hedges"""
        from src.position_manager import get_open_positions
        from src.blofin_client import BlofinClient
        
        try:
            positions = get_open_positions()
            if not positions:
                return
            
            # Get unique symbols with positions
            symbols = list(set(p.get("symbol") for p in positions))
            if len(symbols) < 2:
                return  # Need at least 2 symbols to hedge
            
            # Calculate correlation matrix
            self._calculate_correlations(symbols)
            
            # Identify highly correlated clusters
            clusters = self._identify_clusters()
            
            # For each cluster, check if hedge is needed
            new_hedges = []
            for cluster in clusters:
                hedge = self._evaluate_cluster_hedge(cluster, positions)
                if hedge:
                    new_hedges.append(hedge)
            
            self.active_hedges = new_hedges
            self.last_hedge_ts = int(time.time())
            
            # Log hedge recommendations
            if new_hedges:
                _log_event("phase1017_hedges_recommended", {
                    "hedge_count": len(new_hedges),
                    "hedges": new_hedges
                })
        
        except Exception as e:
            _log_event("phase1017_error", {"error": str(e)})
    
    def _calculate_correlations(self, symbols: List[str]):
        """Calculate pairwise correlations between symbols"""
        from src.blofin_client import BlofinClient
        import statistics
        
        # Fetch price data for all symbols
        price_series = {}
        client = BlofinClient()
        for symbol in symbols:
            try:
                df = client.fetch_ohlcv(symbol, timeframe="1m", limit=Config1017.correlation_lookback_candles)
                candles = df.values.tolist()  # Convert DataFrame to list of lists
                if candles and len(candles) >= 100:
                    prices = [float(c[4]) for c in candles]  # Close prices
                    price_series[symbol] = prices
            except Exception:
                pass
        
        # Calculate correlations
        for s1 in price_series:
            for s2 in price_series:
                if s1 >= s2:
                    continue
                
                p1 = price_series[s1]
                p2 = price_series[s2]
                
                # Align lengths
                min_len = min(len(p1), len(p2))
                p1 = p1[-min_len:]
                p2 = p2[-min_len:]
                
                # Calculate correlation
                mean1 = statistics.mean(p1)
                mean2 = statistics.mean(p2)
                
                numerator = sum((p1[i] - mean1) * (p2[i] - mean2) for i in range(min_len))
                denom1 = sum((p1[i] - mean1) ** 2 for i in range(min_len)) ** 0.5
                denom2 = sum((p2[i] - mean2) ** 2 for i in range(min_len)) ** 0.5
                
                if denom1 > 0 and denom2 > 0:
                    corr = numerator / (denom1 * denom2)
                    self.correlation_matrix[(s1, s2)] = corr
    
    def _identify_clusters(self) -> List[List[str]]:
        """Identify clusters of highly correlated symbols"""
        clusters = []
        processed = set()
        
        for (s1, s2), corr in self.correlation_matrix.items():
            if corr >= Config1017.high_correlation_threshold:
                # Find existing cluster
                found_cluster = None
                for cluster in clusters:
                    if s1 in cluster or s2 in cluster:
                        found_cluster = cluster
                        break
                
                if found_cluster:
                    found_cluster.add(s1)
                    found_cluster.add(s2)
                else:
                    clusters.append({s1, s2})
        
        return [list(c) for c in clusters]
    
    def _evaluate_cluster_hedge(self, cluster: List[str], positions: List[Dict]) -> Optional[Dict]:
        """Evaluate if cluster needs hedging"""
        # Calculate total exposure in cluster
        cluster_exposure = sum(
            abs(p.get("size", 0))
            for p in positions
            if p.get("symbol") in cluster
        )
        
        if cluster_exposure < 500:  # Too small to hedge
            return None
        
        # Recommend hedge: short a small portion of cluster leader
        hedge_size = min(cluster_exposure * Config1017.max_hedge_ratio, cluster_exposure * 0.3)
        
        if hedge_size < Config1017.min_hedge_size_usd:
            return None
        
        # Pick the most liquid symbol in cluster as hedge instrument
        hedge_symbol = cluster[0]  # Simplified: pick first
        
        return {
            "cluster": cluster,
            "hedge_symbol": hedge_symbol,
            "hedge_size_usd": hedge_size,
            "cluster_exposure": cluster_exposure,
            "reason": "high_correlation_cluster",
            "ts": int(time.time())
        }
    
    def get_state(self) -> Dict:
        """Get current state for dashboard"""
        return {
            "correlation_pairs": len(self.correlation_matrix),
            "active_hedges": len(self.active_hedges),
            "hedges": self.active_hedges,
            "last_hedge_ts": self.last_hedge_ts
        }

# ======================================================================================
# Phase 10.18: Autonomous Governance & Self-Healing
# ======================================================================================

class Config1018:
    """Phase 10.18 Configuration"""
    # Health check thresholds
    min_system_health = 0.60
    critical_health = 0.40
    
    # Auto-repair triggers
    max_consecutive_errors = 5
    max_failed_orders_pct = 0.15  # 15% order failure rate triggers intervention
    
    # Circuit breaker
    max_daily_loss_pct = 0.10  # 10% daily loss triggers circuit breaker

class AutonomousGovernance:
    """
    Monitors system health and applies automatic fixes.
    """
    
    def __init__(self):
        self.health_score = 1.0
        self.consecutive_errors = 0
        self.interventions = []
        self.circuit_breaker_active = False
        self.last_governance_ts = 0
    
    def governance_tick(self):
        """Run health checks and apply fixes if needed"""
        # Calculate health score
        self._calculate_health()
        
        # Check for interventions
        self._check_interventions()
        
        # Log governance state
        _log_event("phase1018_governance_tick", {
            "health_score": self.health_score,
            "circuit_breaker": self.circuit_breaker_active,
            "interventions": len(self.interventions)
        })
        
        self.last_governance_ts = int(time.time())
    
    def _calculate_health(self):
        """Calculate overall system health score"""
        from src.portfolio_tracker import load_portfolio
        
        try:
            portfolio = load_portfolio()
            
            # Component health scores
            health_components = []
            
            # 1. P&L health (not in major drawdown)
            daily_pnl_pct = portfolio.get("session_pnl", 0) / 10000.0  # Assuming 10k starting capital
            if daily_pnl_pct < -Config1018.max_daily_loss_pct:
                pnl_health = 0.0
            elif daily_pnl_pct < 0:
                pnl_health = 0.5
            else:
                pnl_health = 1.0
            health_components.append(pnl_health)
            
            # 2. Error rate health
            if self.consecutive_errors >= Config1018.max_consecutive_errors:
                error_health = 0.0
            elif self.consecutive_errors >= 3:
                error_health = 0.5
            else:
                error_health = 1.0
            health_components.append(error_health)
            
            # 3. Position health (not over-leveraged)
            total_exposure = sum(abs(p.get("size", 0)) for p in _get_positions())
            pv = portfolio.get("portfolio_value", 10000)
            leverage = total_exposure / pv if pv > 0 else 0
            if leverage > 3.0:
                position_health = 0.0
            elif leverage > 2.0:
                position_health = 0.5
            else:
                position_health = 1.0
            health_components.append(position_health)
            
            # Composite health
            self.health_score = sum(health_components) / len(health_components) if health_components else 1.0
        
        except Exception as e:
            self.health_score = 0.5
            _log_event("phase1018_health_calc_error", {"error": str(e)})
    
    def _check_interventions(self):
        """Check if automatic interventions are needed"""
        # Circuit breaker for critical health
        if self.health_score < Config1018.critical_health and not self.circuit_breaker_active:
            self._activate_circuit_breaker("critical_health")
        
        # Reset circuit breaker if health recovered
        if self.health_score > Config1018.min_system_health and self.circuit_breaker_active:
            self._deactivate_circuit_breaker()
        
        # Error recovery
        if self.consecutive_errors >= Config1018.max_consecutive_errors:
            self._apply_error_recovery()
    
    def _activate_circuit_breaker(self, reason: str):
        """Halt trading temporarily"""
        self.circuit_breaker_active = True
        intervention = {
            "type": "circuit_breaker_activated",
            "reason": reason,
            "health_score": self.health_score,
            "ts": int(time.time())
        }
        self.interventions.append(intervention)
        _log_event("phase1018_circuit_breaker", intervention)
    
    def _deactivate_circuit_breaker(self):
        """Resume trading"""
        self.circuit_breaker_active = False
        intervention = {
            "type": "circuit_breaker_deactivated",
            "health_score": self.health_score,
            "ts": int(time.time())
        }
        self.interventions.append(intervention)
        _log_event("phase1018_circuit_breaker_off", intervention)
    
    def _apply_error_recovery(self):
        """Reset error counters and apply conservative mode"""
        self.consecutive_errors = 0
        intervention = {
            "type": "error_recovery",
            "action": "reset_errors_conservative_mode",
            "ts": int(time.time())
        }
        self.interventions.append(intervention)
        _log_event("phase1018_error_recovery", intervention)
    
    def record_error(self):
        """Record an error occurrence"""
        self.consecutive_errors += 1
    
    def record_success(self):
        """Record successful operation"""
        self.consecutive_errors = max(0, self.consecutive_errors - 1)
    
    def get_state(self) -> Dict:
        """Get current state for dashboard"""
        return {
            "health_score": self.health_score,
            "circuit_breaker_active": self.circuit_breaker_active,
            "consecutive_errors": self.consecutive_errors,
            "interventions": self.interventions[-10:],  # Last 10 interventions
            "last_governance_ts": self.last_governance_ts
        }

# ======================================================================================
# Global Instances
# ======================================================================================

META_ROUTER = MetaExpectancyRouter()
CORRELATION_HEDGER = CorrelationHedger()
AUTONOMOUS_GOV = AutonomousGovernance()

# ======================================================================================
# State Persistence
# ======================================================================================

STATE_PATH = "logs/phase1016_1018_state.json"
EVENTS_PATH = "logs/phase1016_1018_events.jsonl"

def _log_event(event: str, payload: dict):
    """Log event to JSONL file"""
    os.makedirs(os.path.dirname(EVENTS_PATH), exist_ok=True)
    with open(EVENTS_PATH, "a") as f:
        f.write(json.dumps({
            "ts": int(time.time()),
            "event": event,
            "payload": payload
        }) + "\n")

def _save_state():
    """Save state to JSON"""
    state = {
        "phase1016": META_ROUTER.get_state(),
        "phase1017": CORRELATION_HEDGER.get_state(),
        "phase1018": AUTONOMOUS_GOV.get_state(),
        "updated_ts": int(time.time())
    }
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)

def _get_positions() -> List[Dict]:
    """Helper to get positions"""
    try:
        from src.position_manager import get_open_positions
        return get_open_positions()
    except Exception:
        return []

# ======================================================================================
# Public API (called from unified orchestration)
# ======================================================================================

def phase1016_on_trade_close(trade: Dict):
    """Phase 10.16: Update bucket metrics on trade close"""
    META_ROUTER.on_trade_close(trade)
    _save_state()

def phase1016_route_tick():
    """Phase 10.16: Recompute bucket routing"""
    META_ROUTER.route_tick()
    _save_state()

def phase1016_apply_bucket_weight(signal: Dict) -> float:
    """Phase 10.16: Apply bucket multiplier to size"""
    return META_ROUTER.apply_bucket_weight(signal)

def phase1017_hedge_tick():
    """Phase 10.17: Evaluate correlation hedges"""
    CORRELATION_HEDGER.hedge_tick()
    _save_state()

def phase1018_governance_tick():
    """Phase 10.18: Run autonomous governance"""
    AUTONOMOUS_GOV.governance_tick()
    _save_state()

def phase1018_record_error():
    """Phase 10.18: Record error for health monitoring"""
    AUTONOMOUS_GOV.record_error()

def phase1018_record_success():
    """Phase 10.18: Record success for health monitoring"""
    AUTONOMOUS_GOV.record_success()

def get_phase1016_1018_state() -> Dict:
    """Get combined state for dashboard"""
    return {
        "phase1016": META_ROUTER.get_state(),
        "phase1017": CORRELATION_HEDGER.get_state(),
        "phase1018": AUTONOMOUS_GOV.get_state()
    }

# ======================================================================================
# Initialization
# ======================================================================================

def start_phase1016_1018():
    """Initialize Phases 10.16-10.18"""
    print("⚡ Starting Phase 10.16-10.18 (Meta Router + Hedger + Governance)...")
    print("   ℹ️  Phase 10.16 - Meta-Expectancy Router: bucket-based capital routing")
    print("   ℹ️  Phase 10.17 - Correlation Hedger: auto-hedge correlated clusters")
    print("   ℹ️  Phase 10.18 - Autonomous Governance: health monitoring + circuit breakers")
    print("✅ Phase 10.16-10.18 started")
    _log_event("phase1016_1018_started", {"ts": int(time.time())})
