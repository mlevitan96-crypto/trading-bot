"""
Correlation Throttle Module - Reduces exposure when assets are highly correlated.

This module prevents over-concentration in correlated assets by:
1. Tracking correlation clusters (BTC, ALT, MEME, STABLE)
2. Reducing position sizes when correlated assets are already open
3. Enforcing cluster exposure limits (30% of portfolio per cluster)
4. Logging all throttle decisions for analysis

Usage:
    from src.correlation_throttle import get_correlation_throttle, check_throttle
    
    # Check if a new position should be throttled
    result = check_throttle("ETHUSDT", "LONG", 100.0, open_positions)
    final_size = result["throttled_size"]
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from collections import defaultdict

from src.data_registry import DataRegistry as DR
from src.file_locks import atomic_json_save, locked_json_read

CORRELATION_STATE_PATH = DR.CORRELATION_THROTTLE_STATE
CORRELATION_LOG_PATH = DR.CORRELATION_THROTTLE_LOG
CORRELATION_REPORT_PATH = DR.CORRELATION_REPORT

# EXPLORATION MODE 2025-12-03: Maximize data collection (paper trading)
# User directive: Learn as much as possible, this is not real money
# Previous: 0.8, 0.90, 5, 0.50 → Now: 0.95, 0.98, 10, 0.80
HIGH_CORRELATION_THRESHOLD = 0.95
EXTREME_CORRELATION_THRESHOLD = 0.98
MAX_POSITIONS_PER_CLUSTER = 10
MAX_CLUSTER_EXPOSURE_PCT = 0.80
DEFAULT_PORTFOLIO_VALUE = 1000.0

CORRELATION_CLUSTERS = {
    "BTC": {
        "name": "BTC Cluster",
        "leader": "BTCUSDT",
        "members": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        "description": "High correlation major assets following BTC"
    },
    "ALT": {
        "name": "ALT Cluster", 
        "leader": "AVAXUSDT",
        "members": ["AVAXUSDT", "DOTUSDT", "ARBUSDT", "OPUSDT"],
        "description": "Layer 1/2 altcoins with moderate correlation"
    },
    "MEME": {
        "name": "MEME Cluster",
        "leader": "DOGEUSDT",
        "members": ["DOGEUSDT", "PEPEUSDT"],
        "description": "Meme coins with high intra-cluster correlation"
    },
    "STABLE": {
        "name": "STABLE Alts",
        "leader": "BNBUSDT",
        "members": ["BNBUSDT", "XRPUSDT", "ADAUSDT", "TRXUSDT", "LINKUSDT", "MATICUSDT"],
        "description": "Established altcoins with lower volatility"
    }
}

SYMBOL_TO_CLUSTER = {}
for cluster_name, cluster_data in CORRELATION_CLUSTERS.items():
    for symbol in cluster_data["members"]:
        SYMBOL_TO_CLUSTER[symbol] = cluster_name


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _log(msg: str):
    ts = datetime.utcnow().isoformat() + "Z"
    print(f"[{ts}] [CORR-THROTTLE] {msg}")


def _append_jsonl(path: str, record: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'a') as f:
        f.write(json.dumps(record) + '\n')


class CorrelationThrottle:
    """
    Intelligent correlation-based position throttling.
    
    Strategy:
    - REDUCE size when avg correlation with open > 0.7 (50% reduction)
    - REDUCE more when avg correlation > 0.85 (70% reduction)
    - CAP at 0.3x when cluster has 3+ positions
    - LIMIT cluster exposure to 30% of portfolio
    """
    
    def __init__(self):
        self.correlation_matrix = {}
        self.cluster_definitions = CORRELATION_CLUSTERS.copy()
        self.symbol_to_cluster = SYMBOL_TO_CLUSTER.copy()
        self.stats = {
            "total_checks": 0,
            "throttled_count": 0,
            "total_reduction_usd": 0.0,
            "by_cluster": defaultdict(lambda: {"checks": 0, "throttled": 0}),
            "by_reason": defaultdict(int),
            "last_updated": _now()
        }
        self.load_data()
    
    def load_data(self):
        """Load correlation matrix and previous state."""
        try:
            report = locked_json_read(CORRELATION_REPORT_PATH, default={})
            self._build_correlation_matrix(report)
        except Exception as e:
            _log(f"Warning: Could not load correlation report: {e}")
            self.correlation_matrix = {}
        
        try:
            state = locked_json_read(CORRELATION_STATE_PATH, default={})
            if "stats" in state:
                saved_stats = state["stats"]
                self.stats["total_checks"] = saved_stats.get("total_checks", 0)
                self.stats["throttled_count"] = saved_stats.get("throttled_count", 0)
                self.stats["total_reduction_usd"] = saved_stats.get("total_reduction_usd", 0.0)
        except Exception as e:
            _log(f"Warning: Could not load throttle state: {e}")
        
        _log(f"Loaded correlation data for {len(self.correlation_matrix)} symbol pairs")
    
    def _build_correlation_matrix(self, report: Dict):
        """Build correlation matrix from report data."""
        self.correlation_matrix = {}
        
        pattern_stats = report.get("pattern_stats", {})
        unprofitable = pattern_stats.get("unprofitable", [])
        profitable = pattern_stats.get("profitable", [])
        
        all_patterns = unprofitable + profitable
        for pattern in all_patterns:
            pattern_name = pattern.get("pattern", "")
            if "_" in pattern_name:
                symbol = pattern_name.split("_")[0]
                if symbol not in self.correlation_matrix:
                    self.correlation_matrix[symbol] = {}
        
        for cluster_name, cluster_data in self.cluster_definitions.items():
            members = cluster_data["members"]
            for i, sym1 in enumerate(members):
                if sym1 not in self.correlation_matrix:
                    self.correlation_matrix[sym1] = {}
                for sym2 in members[i+1:]:
                    if sym2 not in self.correlation_matrix:
                        self.correlation_matrix[sym2] = {}
                    
                    if cluster_name == "BTC":
                        corr = 0.85 if sym2 != "SOLUSDT" else 0.78
                    elif cluster_name == "MEME":
                        corr = 0.82
                    elif cluster_name == "ALT":
                        corr = 0.72
                    else:
                        corr = 0.65
                    
                    self.correlation_matrix[sym1][sym2] = corr
                    self.correlation_matrix[sym2][sym1] = corr
        
        for sym in self.symbol_to_cluster.keys():
            if sym not in self.correlation_matrix:
                self.correlation_matrix[sym] = {}
            self.correlation_matrix[sym][sym] = 1.0
    
    def get_symbol_cluster(self, symbol: str) -> Optional[str]:
        """Get the cluster name for a symbol."""
        return self.symbol_to_cluster.get(symbol)
    
    def get_cluster_exposure(self, cluster_name: str, open_positions: List[Dict]) -> float:
        """Calculate total exposure in USD for a cluster."""
        if cluster_name not in self.cluster_definitions:
            return 0.0
        
        members = self.cluster_definitions[cluster_name]["members"]
        total_exposure = 0.0
        
        for pos in open_positions:
            symbol = pos.get("symbol", "")
            if symbol in members:
                size_usd = abs(float(pos.get("size_usd", 0)))
                total_exposure += size_usd
        
        return total_exposure
    
    def get_cluster_positions(self, cluster_name: str, open_positions: List[Dict]) -> List[Dict]:
        """Get all open positions in a cluster."""
        if cluster_name not in self.cluster_definitions:
            return []
        
        members = self.cluster_definitions[cluster_name]["members"]
        return [pos for pos in open_positions if pos.get("symbol", "") in members]
    
    def get_correlation_with_open(self, symbol: str, open_positions: List[Dict]) -> float:
        """Calculate average correlation with all open positions."""
        if not open_positions:
            return 0.0
        
        correlations = []
        symbol_corrs = self.correlation_matrix.get(symbol, {})
        
        for pos in open_positions:
            pos_symbol = pos.get("symbol", "")
            if pos_symbol == symbol:
                continue
            
            corr = symbol_corrs.get(pos_symbol)
            if corr is not None:
                correlations.append(corr)
            else:
                if self.get_symbol_cluster(symbol) == self.get_symbol_cluster(pos_symbol):
                    correlations.append(0.7)
                else:
                    correlations.append(0.4)
        
        if not correlations:
            return 0.0
        
        return sum(correlations) / len(correlations)
    
    def calculate_size_reduction(self, correlation: float, cluster_exposure: float,
                                  cluster_position_count: int, 
                                  portfolio_value: float = DEFAULT_PORTFOLIO_VALUE) -> Tuple[float, str]:
        """
        Calculate the size reduction factor based on correlation and exposure.
        
        Returns:
            (reduction_factor, reason) where factor is 0.0 to 1.0
        """
        reduction = 1.0
        reasons = []
        
        if correlation > EXTREME_CORRELATION_THRESHOLD:
            reduction = min(reduction, 0.3)
            reasons.append(f"extreme_corr_{correlation:.2f}")
        elif correlation > HIGH_CORRELATION_THRESHOLD:
            reduction = min(reduction, 0.5)
            reasons.append(f"high_corr_{correlation:.2f}")
        
        if cluster_position_count >= MAX_POSITIONS_PER_CLUSTER:
            reduction = min(reduction, 0.3)
            reasons.append(f"max_positions_{cluster_position_count}")
        
        max_cluster_exposure = portfolio_value * MAX_CLUSTER_EXPOSURE_PCT
        if cluster_exposure > 0:
            exposure_ratio = cluster_exposure / max_cluster_exposure
            if exposure_ratio >= 1.0:
                reduction = min(reduction, 0.1)
                reasons.append(f"cluster_limit_exceeded_{exposure_ratio:.1f}x")
            elif exposure_ratio >= 0.8:
                reduction = min(reduction, 0.3)
                reasons.append(f"cluster_near_limit_{exposure_ratio:.1%}")
            elif exposure_ratio >= 0.6:
                reduction = min(reduction, 0.5)
                reasons.append(f"cluster_high_{exposure_ratio:.1%}")
        
        reason = "|".join(reasons) if reasons else "no_throttle"
        return reduction, reason
    
    def check_throttle(self, symbol: str, side: str, proposed_size_usd: float,
                       open_positions: List[Dict], 
                       portfolio_value: float = DEFAULT_PORTFOLIO_VALUE) -> Dict:
        """
        Check if a new position should be throttled.
        
        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            side: "LONG" or "SHORT"
            proposed_size_usd: Proposed position size in USD
            open_positions: List of current open positions
            portfolio_value: Total portfolio value for exposure calculations
        
        Returns:
            Dict with throttled_size, reduction_pct, reason, correlated_positions
        """
        self.stats["total_checks"] += 1
        
        cluster_name = self.get_symbol_cluster(symbol)
        
        if cluster_name:
            self.stats["by_cluster"][cluster_name]["checks"] += 1
            cluster_exposure = self.get_cluster_exposure(cluster_name, open_positions)
            cluster_positions = self.get_cluster_positions(cluster_name, open_positions)
            cluster_position_count = len(cluster_positions)
        else:
            cluster_exposure = 0.0
            cluster_positions = []
            cluster_position_count = 0
        
        avg_correlation = self.get_correlation_with_open(symbol, open_positions)
        
        reduction_factor, reason = self.calculate_size_reduction(
            correlation=avg_correlation,
            cluster_exposure=cluster_exposure,
            cluster_position_count=cluster_position_count,
            portfolio_value=portfolio_value
        )
        
        throttled_size = proposed_size_usd * reduction_factor
        
        # CHANGED 2025-12-02: Enforce minimum $200 floor to prevent zero-size positions
        # Per user policy: minimum position size is $200, not $0
        MIN_POSITION_SIZE_USD = 200.0
        if throttled_size < MIN_POSITION_SIZE_USD and proposed_size_usd >= MIN_POSITION_SIZE_USD:
            throttled_size = MIN_POSITION_SIZE_USD
            reduction_factor = MIN_POSITION_SIZE_USD / proposed_size_usd if proposed_size_usd > 0 else 1.0
            _log(f"📏 FLOOR APPLIED {symbol}: ${proposed_size_usd:.0f} throttled to min ${MIN_POSITION_SIZE_USD}")
        
        reduction_pct = (1.0 - reduction_factor) * 100
        
        correlated_positions = []
        for pos in open_positions:
            pos_symbol = pos.get("symbol", "")
            corr = self.correlation_matrix.get(symbol, {}).get(pos_symbol, 0)
            if corr > HIGH_CORRELATION_THRESHOLD:
                correlated_positions.append({
                    "symbol": pos_symbol,
                    "correlation": corr,
                    "size_usd": pos.get("size_usd", 0),
                    "side": pos.get("side", "")
                })
        
        result = {
            "symbol": symbol,
            "side": side,
            "proposed_size_usd": proposed_size_usd,
            "throttled_size": throttled_size,
            "reduction_factor": reduction_factor,
            "reduction_pct": reduction_pct,
            "reason": reason,
            "avg_correlation": avg_correlation,
            "cluster": cluster_name,
            "cluster_exposure": cluster_exposure,
            "cluster_positions": cluster_position_count,
            "correlated_positions": correlated_positions,
            "was_throttled": reduction_factor < 1.0,
            "ts": _now()
        }
        
        if reduction_factor < 1.0:
            self.stats["throttled_count"] += 1
            self.stats["total_reduction_usd"] += (proposed_size_usd - throttled_size)
            if cluster_name:
                self.stats["by_cluster"][cluster_name]["throttled"] += 1
            self.stats["by_reason"][reason.split("|")[0]] += 1
            
            self.log_throttle(symbol, proposed_size_usd, throttled_size, reason)
            
            _log(f"⚡ THROTTLED {symbol} {side}: ${proposed_size_usd:.2f} → ${throttled_size:.2f} "
                 f"(-{reduction_pct:.0f}%) | {reason}")
        
        return result
    
    def log_throttle(self, symbol: str, original_size: float, final_size: float, reason: str):
        """Write throttle decision to log file."""
        record = {
            "ts": _now(),
            "symbol": symbol,
            "original_size_usd": original_size,
            "final_size_usd": final_size,
            "reduction_pct": ((original_size - final_size) / original_size * 100) if original_size > 0 else 0,
            "reason": reason,
            "cluster": self.get_symbol_cluster(symbol)
        }
        
        try:
            _append_jsonl(CORRELATION_LOG_PATH, record)
        except Exception as e:
            _log(f"Warning: Could not write to log: {e}")
    
    def save_state(self):
        """Save current state to file using atomic writes."""
        state = {
            "stats": {
                "total_checks": self.stats["total_checks"],
                "throttled_count": self.stats["throttled_count"],
                "total_reduction_usd": self.stats["total_reduction_usd"],
                "by_cluster": dict(self.stats["by_cluster"]),
                "by_reason": dict(self.stats["by_reason"]),
                "last_updated": _now()
            },
            "cluster_definitions": self.cluster_definitions,
            "symbol_mapping": self.symbol_to_cluster
        }
        
        try:
            atomic_json_save(CORRELATION_STATE_PATH, state)
            _log("State saved successfully")
        except Exception as e:
            _log(f"Warning: Could not save state: {e}")
    
    def get_stats(self) -> Dict:
        """Get throttle statistics."""
        total = self.stats["total_checks"]
        throttled = self.stats["throttled_count"]
        
        return {
            "total_checks": total,
            "throttled_count": throttled,
            "throttle_rate": (throttled / total * 100) if total > 0 else 0,
            "total_reduction_usd": self.stats["total_reduction_usd"],
            "avg_reduction_per_throttle": (
                self.stats["total_reduction_usd"] / throttled if throttled > 0 else 0
            ),
            "by_cluster": dict(self.stats["by_cluster"]),
            "by_reason": dict(self.stats["by_reason"]),
            "cluster_count": len(self.cluster_definitions),
            "tracked_symbols": len(self.symbol_to_cluster),
            "last_updated": self.stats.get("last_updated", _now())
        }
    
    def get_cluster_summary(self, open_positions: List[Dict], 
                            portfolio_value: float = DEFAULT_PORTFOLIO_VALUE) -> Dict:
        """Get summary of exposure by cluster."""
        summary = {}
        max_exposure = portfolio_value * MAX_CLUSTER_EXPOSURE_PCT
        
        for cluster_name, cluster_data in self.cluster_definitions.items():
            exposure = self.get_cluster_exposure(cluster_name, open_positions)
            positions = self.get_cluster_positions(cluster_name, open_positions)
            
            summary[cluster_name] = {
                "name": cluster_data["name"],
                "exposure_usd": exposure,
                "exposure_pct": (exposure / portfolio_value * 100) if portfolio_value > 0 else 0,
                "max_exposure_usd": max_exposure,
                "utilization": (exposure / max_exposure * 100) if max_exposure > 0 else 0,
                "position_count": len(positions),
                "max_positions": MAX_POSITIONS_PER_CLUSTER,
                "positions": [
                    {"symbol": p.get("symbol"), "size_usd": p.get("size_usd", 0)}
                    for p in positions
                ],
                "members": cluster_data["members"]
            }
        
        return summary
    
    def print_status(self, open_positions: List[Dict] = None, 
                     portfolio_value: float = DEFAULT_PORTFOLIO_VALUE):
        """Print current throttle status."""
        print("\n" + "="*60)
        print("⚡ CORRELATION THROTTLE STATUS")
        print("="*60)
        
        stats = self.get_stats()
        print(f"\n📊 Overall Statistics:")
        print(f"   Total Checks: {stats['total_checks']}")
        print(f"   Throttled: {stats['throttled_count']} ({stats['throttle_rate']:.1f}%)")
        print(f"   Total Reduction: ${stats['total_reduction_usd']:.2f}")
        
        print(f"\n🎯 Cluster Definitions:")
        for cluster_name, cluster_data in self.cluster_definitions.items():
            print(f"   {cluster_name}: {', '.join(cluster_data['members'])}")
        
        if open_positions:
            print(f"\n📈 Current Cluster Exposure:")
            summary = self.get_cluster_summary(open_positions, portfolio_value)
            for cluster_name, data in summary.items():
                emoji = "🔴" if data["utilization"] >= 80 else "🟡" if data["utilization"] >= 50 else "🟢"
                print(f"   {emoji} {cluster_name}: ${data['exposure_usd']:.2f} "
                      f"({data['exposure_pct']:.1f}% of portfolio, "
                      f"{data['utilization']:.0f}% of limit)")
                if data["positions"]:
                    for pos in data["positions"]:
                        print(f"      └─ {pos['symbol']}: ${pos['size_usd']:.2f}")
        
        print("="*60 + "\n")


_throttle_instance: Optional[CorrelationThrottle] = None


def get_correlation_throttle() -> CorrelationThrottle:
    """Get or create the singleton throttle instance."""
    global _throttle_instance
    if _throttle_instance is None:
        _throttle_instance = CorrelationThrottle()
    return _throttle_instance


def refresh_throttle() -> CorrelationThrottle:
    """Reload all data into the throttle."""
    global _throttle_instance
    _throttle_instance = CorrelationThrottle()
    return _throttle_instance


def check_throttle(symbol: str, side: str, proposed_size_usd: float,
                   open_positions: List[Dict],
                   portfolio_value: float = DEFAULT_PORTFOLIO_VALUE) -> Dict:
    """Quick check if a position should be throttled."""
    return get_correlation_throttle().check_throttle(
        symbol, side, proposed_size_usd, open_positions, portfolio_value
    )


def get_cluster_exposure(cluster_name: str, open_positions: List[Dict]) -> float:
    """Get exposure for a specific cluster."""
    return get_correlation_throttle().get_cluster_exposure(cluster_name, open_positions)


def get_cluster_summary(open_positions: List[Dict],
                        portfolio_value: float = DEFAULT_PORTFOLIO_VALUE) -> Dict:
    """Get summary of all cluster exposures."""
    return get_correlation_throttle().get_cluster_summary(open_positions, portfolio_value)


if __name__ == "__main__":
    throttle = CorrelationThrottle()
    
    print("\n🎯 CORRELATION CLUSTERS:")
    for cluster_name, cluster_data in throttle.cluster_definitions.items():
        print(f"   {cluster_name}: {cluster_data['name']}")
        print(f"      Leader: {cluster_data['leader']}")
        print(f"      Members: {', '.join(cluster_data['members'])}")
        print()
    
    mock_positions = [
        {"symbol": "BTCUSDT", "side": "LONG", "size_usd": 150.0},
        {"symbol": "ETHUSDT", "side": "LONG", "size_usd": 100.0},
    ]
    
    print("\n📊 Test Throttle Checks:")
    for symbol in ["SOLUSDT", "AVAXUSDT", "DOGEUSDT"]:
        result = throttle.check_throttle(symbol, "LONG", 100.0, mock_positions, 1000.0)
        print(f"\n   {symbol} LONG $100:")
        print(f"      Throttled Size: ${result['throttled_size']:.2f}")
        print(f"      Reduction: {result['reduction_pct']:.0f}%")
        print(f"      Reason: {result['reason']}")
        print(f"      Avg Correlation: {result['avg_correlation']:.2f}")
        print(f"      Cluster: {result['cluster']}")
    
    throttle.print_status(mock_positions, 1000.0)
    
    print("\n📈 Throttle Statistics:")
    stats = throttle.get_stats()
    for key, value in stats.items():
        if not isinstance(value, dict):
            print(f"   {key}: {value}")
